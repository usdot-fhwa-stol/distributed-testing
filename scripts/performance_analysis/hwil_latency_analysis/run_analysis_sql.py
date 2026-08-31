"""
Unified Performance & Latency Analyzer for VOICES Radio and
SecureV2XMessage.

Supports:
- Single-site internal latency calculation.
- Multi-site end-to-end matching.
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from dataclasses import dataclass
import fnmatch
import logging
from pathlib import Path
import re
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

sns.set_theme(style="whitegrid")

_NUM_BINS = 25
_AXIS_FONT_SIZE = 12
_DEFAULT_MAX_LATENCY_MS = 200.0
_DEFAULT_ROLLING_WINDOW = 20

DATA_TYPES: dict[str, dict[str, Any]] = {
    "Radio": {
        "patterns": ["*Entities-Radio*.csv", "*Radio*.csv"],
        "id_cols": ["const^identifier,String", "Metadata,StateVersion"],
        "skip_events": {"Discovery", "Destruction"},
    },
    "SecureV2XMessage": {
        "patterns": [
            "*TV2XMsg-SecureV2XMsg*.csv",
            "*SecureV2XMsg*.csv",
            "*SecureV2X*.csv",
        ],
        "id_cols": [
            "Metadata,MessageCount",
            "senderIdentifier,String",
            "uuid,String",
        ],
        "skip_events": set(),
    },
}


@dataclass(frozen=True, slots=True)
class LogRecord:
    tx_time_ms: float
    rx_time_ms: float
    latency_ms: float
    match_key: str
    row_id: str
    ip_address: str


# =============================================================================
# GENERAL HELPERS
# =============================================================================
def clean_value(value: Any) -> str:
    """Convert a CSV value to a normalized string without exposing NaN."""
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def safe_filename(value: str) -> str:
    """Convert a descriptive analysis name into a portable filename."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("._") or "analysis"


def normalize_timestamp_ms(value: Any) -> float:
    """
    Normalize an epoch timestamp to milliseconds.

    Common epoch magnitudes:
    - Seconds:      approximately 1e9
    - Milliseconds: approximately 1e12
    - Microseconds: approximately 1e15
    - Nanoseconds:  approximately 1e18

    Smaller values are retained to support relative millisecond timestamps.
    """
    numeric = float(value)

    if not np.isfinite(numeric):
        raise ValueError("Timestamp is not finite")

    magnitude = abs(numeric)

    if magnitude >= 1e17:
        return numeric / 1e6
    if magnitude >= 1e14:
        return numeric / 1e3
    if 1e8 <= magnitude < 1e11:
        return numeric * 1e3

    return numeric


def extract_host(value: Any) -> str:
    """Extract a host from common endpoint representations."""
    endpoint = clean_value(value)
    if not endpoint:
        return ""

    endpoint = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", endpoint)

    if endpoint.startswith("["):
        closing_bracket = endpoint.find("]")
        if closing_bracket != -1:
            return endpoint[1:closing_bracket]

    # Remove a port from IPv4 or hostname endpoints, but preserve bare IPv6.
    if endpoint.count(":") == 1:
        return endpoint.rsplit(":", maxsplit=1)[0]

    return endpoint


def calculate_jitter(df: pd.DataFrame) -> float:
    """Calculate mean absolute latency change in chronological order."""
    if len(df) < 2:
        return float("nan")

    ordered = df.sort_values("Tx Timestamp (ms)")
    latency = ordered["Latency (ms)"].astype(float)
    return float(latency.diff().abs().dropna().mean())


def calculate_statistics(
    df: pd.DataFrame,
    *,
    message_type: str,
    mode: str,
    source: str,
    destination: str,
) -> dict[str, Any]:
    """Create one results-summary record."""
    latency = pd.to_numeric(df["Latency (ms)"], errors="coerce")
    latency = latency[np.isfinite(latency)]

    jitter = calculate_jitter(df)
    standard_deviation = float(latency.std()) if len(latency) > 1 else 0.0

    return {
        "message_type": message_type,
        "mode": mode,
        "source": source,
        "destination": destination,
        "samples": len(latency),
        "min_ms": round(float(latency.min()), 2),
        "max_ms": round(float(latency.max()), 2),
        "mean_ms": round(float(latency.mean()), 2),
        "median_ms": round(float(latency.median()), 2),
        "p95_ms": round(float(latency.quantile(0.95)), 2),
        "p99_ms": round(float(latency.quantile(0.99)), 2),
        "jitter_ms": (
            round(jitter, 2) if np.isfinite(jitter) else "NA"
        ),
        "std_dev": round(standard_deviation, 2),
    }


# =============================================================================
# CSV INGESTION AND PARSING
# =============================================================================
def find_csv_files(
    directory: Path,
    patterns: Iterable[str],
    *,
    recursive: bool = True,
) -> list[Path]:
    """Find all CSV files matching at least one configured pattern."""
    if not directory.is_dir():
        return []

    candidates = directory.rglob("*.csv") if recursive else directory.glob("*.csv")
    sorted_candidates = sorted(
        candidates,
        key=lambda path: str(path).casefold(),
    )

    return [
        path
        for path in sorted_candidates
        if any(fnmatch.fnmatch(path.name, pattern) for pattern in patterns)
    ]


def find_csv_file(
    directory: Path,
    patterns: Iterable[str],
    *,
    recursive: bool = True,
) -> Path | None:
    """
    Return the first deterministic CSV match.

    A warning is emitted when multiple files match because silently selecting a
    random filesystem result can make analysis non-reproducible.
    """
    matches = find_csv_files(
        directory,
        patterns,
        recursive=recursive,
    )

    if not matches:
        return None

    if len(matches) > 1:
        logging.warning(
            "Multiple CSV files matched in %s; using %s. Matches: %s",
            directory,
            matches[0],
            ", ".join(str(path) for path in matches),
        )

    return matches[0]


def read_records(csv_file: Path, msg_type: str) -> list[LogRecord]:
    """Read and normalize relevant log records from one CSV file."""
    cfg = DATA_TYPES[msg_type]

    try:
        df = pd.read_csv(csv_file, dtype=str, low_memory=False)
    except (OSError, pd.errors.ParserError, UnicodeDecodeError) as error:
        logging.error("Failed to read %s: %s", csv_file, error)
        return []

    tx_col = next(
        (
            column
            for column in (
                "Metadata,TimeOfTransmission",
                "Metadata,TimeOfCommit",
                "const^Metadata,TimeOfCreation",
            )
            if column in df.columns
        ),
        None,
    )
    rx_col = next(
        (
            column
            for column in (
                "Metadata,TimeOfReceipt",
                "packetTimestamp",
            )
            if column in df.columns
        ),
        None,
    )

    if tx_col is None or rx_col is None:
        logging.warning(
            "Missing timing columns in %s (TX: %s, RX: %s)",
            csv_file,
            tx_col,
            rx_col,
        )
        return []

    event_col = "Metadata,Enum,Middleware::EventType"
    skip_events = cfg["skip_events"]

    if event_col in df.columns and skip_events:
        df = df.loc[~df[event_col].isin(skip_events)]

    ip_col = next(
        (
            column
            for column in (
                "const^Metadata,SDOid.hostIPaddress",
                "Metadata,Endpoint",
                "const^Metadata,Endpoint",
            )
            if column in df.columns
        ),
        None,
    )

    available_id_cols = [
        column for column in cfg["id_cols"] if column in df.columns
    ]

    if not available_id_cols:
        logging.warning(
            "No configured identifier columns found in %s; falling back to rowID",
            csv_file,
        )

    records: list[LogRecord] = []
    invalid_timestamp_count = 0
    missing_key_count = 0

    for row_index, row in df.iterrows():
        try:
            tx_ms = normalize_timestamp_ms(row[tx_col])
            rx_ms = normalize_timestamp_ms(row[rx_col])
        except (TypeError, ValueError, OverflowError):
            invalid_timestamp_count += 1
            continue

        key_parts = [
            clean_value(row.get(column))
            for column in available_id_cols
        ]
        key_parts = [part for part in key_parts if part]

        row_id = clean_value(row.get("rowID"))
        fallback_id = row_id or str(row_index)

        if key_parts:
            match_key = f"{msg_type}::{'::'.join(key_parts)}"
        else:
            match_key = f"{msg_type}::row::{fallback_id}"
            missing_key_count += 1

        ip_address = extract_host(row.get(ip_col)) if ip_col else ""

        records.append(
            LogRecord(
                tx_time_ms=tx_ms,
                rx_time_ms=rx_ms,
                latency_ms=rx_ms - tx_ms,
                match_key=match_key,
                row_id=row_id,
                ip_address=ip_address,
            )
        )

    records.sort(
        key=lambda record: (
            record.tx_time_ms,
            record.rx_time_ms,
            record.match_key,
        )
    )

    if invalid_timestamp_count:
        logging.warning(
            "Skipped %d rows with invalid timestamps in %s",
            invalid_timestamp_count,
            csv_file,
        )

    if missing_key_count:
        logging.info(
            "%d rows in %s used a row-based fallback match key",
            missing_key_count,
            csv_file,
        )

    logging.info("Read %d valid records from %s", len(records), csv_file)
    return records


# =============================================================================
# LATENCY CALCULATION
# =============================================================================
def process_single_site(records: list[LogRecord]) -> pd.DataFrame:
    """Calculate commit-to-receipt latency for a single log."""
    rows = [
        {
            "Tx Timestamp (ms)": record.tx_time_ms,
            "Rx Timestamp (ms)": record.rx_time_ms,
            "Latency (ms)": record.latency_ms,
            "Match Key": record.match_key,
            "Row ID": record.row_id,
            "IP Address": record.ip_address,
            "Datetime": pd.to_datetime(
                record.tx_time_ms,
                unit="ms",
                utc=True,
                errors="coerce",
            ),
        }
        for record in records
        if np.isfinite(record.latency_ms) and record.latency_ms >= 0
    ]

    return pd.DataFrame(rows)


def match_multi_site(
    tx_records: list[LogRecord],
    rx_records: list[LogRecord],
) -> pd.DataFrame:
    """
    Match transmissions from one site to receipts at another site.

    Candidate receipts are sorted by receipt timestamp. Each receipt can be
    consumed at most once.
    """
    rx_by_key: dict[str, deque[LogRecord]] = defaultdict(deque)

    for record in sorted(
        rx_records,
        key=lambda item: (
            item.match_key,
            item.rx_time_ms,
            item.tx_time_ms,
        ),
    ):
        rx_by_key[record.match_key].append(record)

    matched: list[dict[str, Any]] = []

    for tx_record in sorted(
        tx_records,
        key=lambda item: (
            item.tx_time_ms,
            item.match_key,
        ),
    ):
        candidates = rx_by_key.get(tx_record.match_key)
        if not candidates:
            continue

        while (
            candidates
            and candidates[0].rx_time_ms < tx_record.tx_time_ms
        ):
            candidates.popleft()

        if not candidates:
            continue

        rx_record = candidates.popleft()
        latency_ms = rx_record.rx_time_ms - tx_record.tx_time_ms

        if not np.isfinite(latency_ms) or latency_ms < 0:
            continue

        matched.append(
            {
                "Tx Timestamp (ms)": tx_record.tx_time_ms,
                "Rx Timestamp (ms)": rx_record.rx_time_ms,
                "Latency (ms)": latency_ms,
                "Match Key": tx_record.match_key,
                "Tx Row ID": tx_record.row_id,
                "Rx Row ID": rx_record.row_id,
                "Datetime": pd.to_datetime(
                    tx_record.tx_time_ms,
                    unit="ms",
                    utc=True,
                    errors="coerce",
                ),
            }
        )

    return pd.DataFrame(matched)


# =============================================================================
# PLOTTING
# =============================================================================
def generate_plots(
    df: pd.DataFrame,
    plots_dir: Path,
    title_prefix: str,
    max_latency_ms: float = _DEFAULT_MAX_LATENCY_MS,
    rolling_window: int = _DEFAULT_ROLLING_WINDOW,
) -> None:
    """Generate histogram, empirical CDF, and time-series plots."""
    if df.empty or "Latency (ms)" not in df.columns:
        return

    latency = pd.to_numeric(df["Latency (ms)"], errors="coerce")
    latency = latency[np.isfinite(latency)].to_numpy(dtype=np.float64)

    if latency.size == 0:
        return

    plots_dir.mkdir(parents=True, exist_ok=True)

    output_prefix = safe_filename(title_prefix)
    clipped = np.clip(latency, 0, max_latency_ms)
    clipped_count = int(np.count_nonzero(latency > max_latency_ms))
    colors = sns.color_palette("muted")

    # Histogram
    fig, ax = plt.subplots(figsize=(10, 5))
    sns.histplot(
        x=clipped,
        bins=_NUM_BINS,
        binrange=(0, max_latency_ms),
        color=colors[0],
        edgecolor="white",
        ax=ax,
    )
    ax.set_title(
        (
            f"{title_prefix} - Latency Distribution\n"
            f"Samples: {latency.size:,} | "
            f"Mean: {np.mean(latency):.2f} ms"
        ),
        fontsize=_AXIS_FONT_SIZE,
        fontweight="bold",
    )
    ax.set_xlabel(
        f"Latency (ms, values above {max_latency_ms:g} clipped)",
        fontsize=_AXIS_FONT_SIZE,
    )
    ax.set_ylabel("Count", fontsize=_AXIS_FONT_SIZE)

    if clipped_count:
        ax.text(
            0.99,
            0.95,
            f"{clipped_count:,} sample(s) above plot limit",
            transform=ax.transAxes,
            horizontalalignment="right",
            verticalalignment="top",
        )

    sns.despine(ax=ax)
    fig.tight_layout()
    fig.savefig(
        plots_dir / f"{output_prefix}_histogram.png",
        dpi=150,
        bbox_inches="tight",
    )
    plt.close(fig)

    # Exact empirical CDF
    sorted_latency = np.sort(clipped)
    probabilities = np.arange(1, sorted_latency.size + 1) / sorted_latency.size

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.step(
        sorted_latency,
        probabilities,
        where="post",
        linewidth=2,
        color=colors[1],
    )
    ax.set_title(
        f"{title_prefix} - Empirical Cumulative Distribution (CDF)",
        fontsize=_AXIS_FONT_SIZE,
        fontweight="bold",
    )
    ax.set_xlabel(
        f"Latency (ms, values above {max_latency_ms:g} clipped)",
        fontsize=_AXIS_FONT_SIZE,
    )
    ax.set_ylabel("Probability", fontsize=_AXIS_FONT_SIZE)
    ax.set_xlim(0, max_latency_ms)
    ax.set_ylim(0, 1.05)
    sns.despine(ax=ax)
    fig.tight_layout()
    fig.savefig(
        plots_dir / f"{output_prefix}_cdf.png",
        dpi=150,
        bbox_inches="tight",
    )
    plt.close(fig)

    # Time series
    plot_df = df.copy()
    plot_df["Latency (ms)"] = pd.to_numeric(
        plot_df["Latency (ms)"],
        errors="coerce",
    )
    plot_df["Datetime"] = pd.to_datetime(
        plot_df["Datetime"],
        utc=True,
        errors="coerce",
    )
    plot_df = plot_df.dropna(subset=["Latency (ms)", "Datetime"])
    plot_df = plot_df.sort_values("Datetime")

    if plot_df.empty:
        return

    plot_df["Rolling Mean (ms)"] = (
        plot_df["Latency (ms)"]
        .rolling(window=rolling_window, min_periods=1)
        .mean()
    )

    fig, ax = plt.subplots(figsize=(12, 5))
    sns.scatterplot(
        data=plot_df,
        x="Datetime",
        y="Latency (ms)",
        color=colors[0],
        alpha=0.4,
        s=20,
        edgecolor="none",
        label="Latency",
        ax=ax,
    )
    sns.lineplot(
        data=plot_df,
        x="Datetime",
        y="Rolling Mean (ms)",
        color=colors[3],
        linewidth=2,
        label=f"Rolling Mean ({rolling_window})",
        ax=ax,
    )
    ax.set_title(
        f"{title_prefix} - Latency Over Time",
        fontsize=_AXIS_FONT_SIZE,
        fontweight="bold",
    )
    ax.set_xlabel("Time (UTC)", fontsize=_AXIS_FONT_SIZE)
    ax.set_ylabel("Latency (ms)", fontsize=_AXIS_FONT_SIZE)
    ax.xaxis.set_major_formatter(
        mdates.DateFormatter("%H:%M:%S", tz="UTC")
    )
    fig.autofmt_xdate()
    sns.despine(ax=ax)
    fig.tight_layout()
    fig.savefig(
        plots_dir / f"{output_prefix}_timeseries.png",
        dpi=150,
        bbox_inches="tight",
    )
    plt.close(fig)


# =============================================================================
# PIPELINE HELPERS
# =============================================================================
def save_analysis(
    df: pd.DataFrame,
    *,
    analysis_name: str,
    message_type: str,
    mode: str,
    source: str,
    destination: str,
    data_out: Path,
    plots_out: Path,
    max_latency_ms: float,
    rolling_window: int,
) -> dict[str, Any]:
    """Save an analysis CSV and its plots, then return summary statistics."""
    filename = safe_filename(analysis_name)

    df.to_csv(data_out / f"{filename}.csv", index=False)
    generate_plots(
        df,
        plots_out,
        analysis_name,
        max_latency_ms=max_latency_ms,
        rolling_window=rolling_window,
    )

    return calculate_statistics(
        df,
        message_type=message_type,
        mode=mode,
        source=source,
        destination=destination,
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Unified Latency Analysis for Radio & SecureV2XMessage."
    )
    parser.add_argument(
        "-r",
        "--run-dir",
        type=Path,
        required=True,
        help="Target folder containing CSV files or site subfolders.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("results/Run1_output"),
        help="Output folder for CSV data and visual plots.",
    )
    parser.add_argument(
        "--max-latency-ms",
        type=float,
        default=_DEFAULT_MAX_LATENCY_MS,
        help="Maximum displayed latency in histogram and CDF plots.",
    )
    parser.add_argument(
        "--rolling-window",
        type=int,
        default=_DEFAULT_ROLLING_WINDOW,
        help="Sample count used for the time-series rolling mean.",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="WARNING",
        help="Logging verbosity.",
    )

    args = parser.parse_args()

    if args.max_latency_ms <= 0:
        parser.error("--max-latency-ms must be greater than zero")

    if args.rolling_window <= 0:
        parser.error("--rolling-window must be greater than zero")

    return args


# =============================================================================
# PIPELINE ORCHESTRATOR
# =============================================================================
def main() -> int:
    args = parse_arguments()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s: %(message)s",
    )

    if not args.run_dir.is_dir():
        logging.error("Run directory does not exist: %s", args.run_dir)
        return 2

    data_out = args.output_dir / "data"
    plots_out = args.output_dir / "plots"
    data_out.mkdir(parents=True, exist_ok=True)
    plots_out.mkdir(parents=True, exist_ok=True)

    sub_sites = sorted(
        (
            directory
            for directory in args.run_dir.iterdir()
            if directory.is_dir()
            and not directory.name.startswith(".")
            and directory.name not in {"data", "plots"}
            and directory.resolve() != args.output_dir.resolve()
        ),
        key=lambda path: path.name.casefold(),
    )

    # Cache parsed records so each site/type CSV is read only once.
    record_cache: dict[tuple[Path, str], list[LogRecord]] = {}
    summary_records: list[dict[str, Any]] = []

    for msg_type, cfg in DATA_TYPES.items():
        print()
        print("=" * 55)
        print(f"       ANALYZING: {msg_type}")
        print("=" * 55)

        # Only root-level CSVs select single-site mode. The previous recursive
        # check could accidentally find a site CSV and disable multi-site mode.
        root_csv = find_csv_file(
            args.run_dir,
            cfg["patterns"],
            recursive=False,
        )

        if root_csv is not None or not sub_sites:
            if root_csv is None:
                # Preserve support for a single log stored below the run folder.
                root_csv = find_csv_file(
                    args.run_dir,
                    cfg["patterns"],
                    recursive=True,
                )

            if root_csv is None:
                print(f"  [-] No CSV matching {cfg['patterns']} found.")
                continue

            print(f"  [+] Found log: {root_csv}")

            cache_key = (root_csv, msg_type)
            records = record_cache.setdefault(
                cache_key,
                read_records(root_csv, msg_type),
            )

            if not records:
                print("  [-] No valid records extracted.")
                continue

            df = process_single_site(records)
            if df.empty:
                print("  [-] Could not calculate non-negative latency.")
                continue

            analysis_name = f"{args.run_dir.name}_{msg_type}"
            summary = save_analysis(
                df,
                analysis_name=analysis_name,
                message_type=msg_type,
                mode="Single-Site / Ingestion Latency",
                source=args.run_dir.name,
                destination=args.run_dir.name,
                data_out=data_out,
                plots_out=plots_out,
                max_latency_ms=args.max_latency_ms,
                rolling_window=args.rolling_window,
            )
            summary_records.append(summary)

            print(
                f"  [✓] Processed {len(df):,} messages | "
                f"Mean: {summary['mean_ms']:.2f} ms | "
                f"P95: {summary['p95_ms']:.2f} ms"
            )
            continue

        # Build the site record map once for this message type.
        site_records: dict[Path, list[LogRecord]] = {}

        for site_dir in sub_sites:
            csv_path = find_csv_file(
                site_dir,
                cfg["patterns"],
                recursive=True,
            )
            if csv_path is None:
                continue

            cache_key = (csv_path, msg_type)
            records = record_cache.setdefault(
                cache_key,
                read_records(csv_path, msg_type),
            )

            if records:
                site_records[site_dir] = records

        if len(site_records) < 2:
            print("  [-] Fewer than two sites contain valid matching logs.")
            continue

        for src_dir, tx_records in site_records.items():
            for dst_dir, rx_records in site_records.items():
                if src_dir == dst_dir:
                    continue

                df = match_multi_site(tx_records, rx_records)
                if df.empty:
                    logging.info(
                        "No matches for %s to %s (%s)",
                        src_dir.name,
                        dst_dir.name,
                        msg_type,
                    )
                    continue

                pair_name = (
                    f"{src_dir.name}_to_{dst_dir.name}_{msg_type}"
                )
                summary = save_analysis(
                    df,
                    analysis_name=pair_name,
                    message_type=msg_type,
                    mode="Multi-Site E2E",
                    source=src_dir.name,
                    destination=dst_dir.name,
                    data_out=data_out,
                    plots_out=plots_out,
                    max_latency_ms=args.max_latency_ms,
                    rolling_window=args.rolling_window,
                )
                summary_records.append(summary)

                print(
                    f"  [✓] {pair_name} | "
                    f"Packets: {len(df):,} | "
                    f"Mean: {summary['mean_ms']:.2f} ms | "
                    f"P95: {summary['p95_ms']:.2f} ms"
                )

    if not summary_records:
        print("\n[!] No matching records found.")
        return 1

    summary_df = pd.DataFrame(summary_records)
    summary_df = summary_df.sort_values(
        ["message_type", "mode", "source", "destination"],
        kind="stable",
    )

    summary_path = args.output_dir / "results_summary.csv"
    summary_df.to_csv(summary_path, index=False)

    print(f"\n[✓] Analysis complete! Summary saved to: {summary_path}")
    print(f"[✓] Charts saved to: {plots_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())