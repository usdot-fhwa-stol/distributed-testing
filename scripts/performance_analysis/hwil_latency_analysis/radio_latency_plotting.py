"""
Messaging Performance Analyzer
This script analyzes messaging performance between a message source and a message destination
by reading log files, calculating message latency,
and generating plots for visualization.
"""

import argparse
import logging
import re
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from numpy.typing import NDArray

sns.set_theme(style="whitegrid")

_ENTRY_PATTERN = re.compile(r"^(\d+)\s+:\s+(.*)")
_QUOTED_SCALAR_PATTERN = re.compile(
    r'"(-?[0-9]+(?:\.[0-9]+)?|null|true|false)"'
)

_NUM_BINS = 20
_AXIS_FONT_SIZE = 14


@dataclass(frozen=True)
class LogEntry:
    """Message entry from a V2X log."""

    timestamp_ms: int
    payload: str

    @property
    def match_key(self) -> str:
        """Return a case-insensitive key for message matching."""
        return self.payload.casefold()


@dataclass(frozen=True)
class LatencyResult:
    """Matched transmit and receive message pair."""
    
    tx_timestamp_ms: int
    rx_timestamp_ms: int
    latency_ms: int


def clean_payload(payload: str) -> str:
    """Normalize quoted JSON scalar values."""
    return _QUOTED_SCALAR_PATTERN.sub(r"\1", payload)


def read_log_entries(log_file: Path) -> list[LogEntry]:
    """Read JSON entries from a log."""
    entries: list[LogEntry] = []
    current_timestamp: int | None = None
    current_payload_parts: list[str] = []

    with log_file.open("r", encoding="utf-8", errors="replace") as file_handle:
        for raw_line in file_handle:
            line = raw_line.rstrip("\n")
            match = _ENTRY_PATTERN.match(line)

            if match is not None:
                if current_timestamp is not None:
                    entries.append(
                        LogEntry(
                            timestamp_ms=current_timestamp,
                            payload=clean_payload(
                                "".join(current_payload_parts).strip()
                            ),
                        )
                    )

                current_timestamp = int(match.group(1))
                current_payload_parts = [match.group(2)]
            elif current_timestamp is not None:
                current_payload_parts.append(line)

    if current_timestamp is not None:
        entries.append(
            LogEntry(
                timestamp_ms=current_timestamp,
                payload=clean_payload("".join(current_payload_parts).strip()),
            )
        )

    return entries


def calculate_latency(
    tx_entries: Sequence[LogEntry],
    rx_entries: Sequence[LogEntry],
) -> list[LatencyResult]:
    """Calculate latency for matching messages.

    Receive timestamps are indexed by payload once, avoiding repeated scans of
    the receive log. For duplicate messages, each receive entry is consumed
    only once.

    Unmatched TX messages are ignored. RX messages occurring before their
    matching TX message are also ignored.
    """
    rx_by_payload: dict[str, deque[int]] = defaultdict(deque)

    for rx_entry in rx_entries:
        rx_by_payload[rx_entry.match_key].append(rx_entry.timestamp_ms)

    results: list[LatencyResult] = []

    for tx_entry in tx_entries:
        rx_timestamps = rx_by_payload.get(tx_entry.match_key)

        if not rx_timestamps:
            continue

        while rx_timestamps and rx_timestamps[0] < tx_entry.timestamp_ms:
            rx_timestamps.popleft()

        if not rx_timestamps:
            continue

        rx_timestamp_ms = rx_timestamps.popleft()
        results.append(
            LatencyResult(
                tx_timestamp_ms=tx_entry.timestamp_ms,
                rx_timestamp_ms=rx_timestamp_ms,
                latency_ms=rx_timestamp_ms - tx_entry.timestamp_ms,
            )
        )

    return results


def results_to_dataframe(results: Sequence[LatencyResult]) -> pd.DataFrame:
    """Convert latency results into a DataFrame."""
    latency_df = pd.DataFrame(
        {
            "Tx Timestamp (ms)": [result.tx_timestamp_ms for result in results],
            "Rx Timestamp (ms)": [result.rx_timestamp_ms for result in results],
            "Latency (ms)": [result.latency_ms for result in results],
        }
    )

    if not latency_df.empty:
        latency_df["Datetime"] = pd.to_datetime(
            latency_df["Tx Timestamp (ms)"],
            unit="ms",
            utc=True,
        )

    return latency_df


def plot_latency_histogram(
    latency_df: pd.DataFrame,
    plots_dir: Path,
    max_latency_ms: int,
) -> None:
    """Generate a histogram of overall message latency."""
    latency_values: NDArray[np.float64] = latency_df["Latency (ms)"].to_numpy(
        dtype=np.float64
    )
    clipped_values = np.clip(latency_values, 0, max_latency_ms)

    fig, ax = plt.subplots(figsize=(12, 7))

    sns.histplot(
        x=clipped_values,
        bins=_NUM_BINS,
        binrange=(0, max_latency_ms),
        stat="count",
        color=sns.color_palette("muted")[0],
        edgecolor="white",
        linewidth=0.75,
        ax=ax,
    )

    ax.set_title(
        "Overall Message Latency Histogram\n"
        f"Samples: {len(latency_values):,} | "
        f"Mean: {np.mean(latency_values):.2f} ms | "
        f"P95: {np.percentile(latency_values, 95):.2f} ms",
        fontsize=_AXIS_FONT_SIZE,
        fontweight="bold",
    )
    ax.set_xlabel("Latency (ms)", fontsize=_AXIS_FONT_SIZE)
    ax.set_ylabel("Number of Samples", fontsize=_AXIS_FONT_SIZE)
    sns.despine(ax=ax, top=True, right=True)

    fig.savefig(
        plots_dir / "latency_histogram.png",
        dpi=150,
        bbox_inches="tight",
    )
    plt.close(fig)


def plot_latency_cdf(
    latency_df: pd.DataFrame,
    plots_dir: Path,
    max_latency_ms: int,
) -> None:
    """Plot the cumulative distribution function (CDF) for overall latency."""
    latency_values: NDArray[np.float64] = latency_df["Latency (ms)"].to_numpy(
        dtype=np.float64
    )
    clipped_values = np.clip(latency_values, 0, max_latency_ms)

    fig, ax = plt.subplots(figsize=(12, 7))

    sns.histplot(
        x=clipped_values,
        bins=_NUM_BINS,
        binrange=(0, max_latency_ms),
        cumulative=True,
        stat="probability",
        element="step",
        fill=False,
        linewidth=2,
        color=sns.color_palette("muted")[1],
        ax=ax,
    )

    ax.set_title(
        "Overall Message Latency Cumulative Distribution",
        fontsize=_AXIS_FONT_SIZE,
        fontweight="bold",
    )
    ax.set_xlabel("Latency (ms)", fontsize=_AXIS_FONT_SIZE)
    ax.set_ylabel("Cumulative Probability", fontsize=_AXIS_FONT_SIZE)
    ax.set_ylim(0, 1.05)
    sns.despine(ax=ax, top=True, right=True)

    fig.savefig(
        plots_dir / "latency_cdf.png",
        dpi=150,
        bbox_inches="tight",
    )
    plt.close(fig)


def plot_latency_timeseries(
    latency_df: pd.DataFrame,
    plots_dir: Path,
    rolling_window: int,
) -> None:
    """Generate a latency time series with rolling-mean."""
    plot_df = latency_df.copy().sort_values("Datetime")
    plot_df["Rolling Mean (ms)"] = (
        plot_df["Latency (ms)"]
        .rolling(window=rolling_window, min_periods=1)
        .mean()
    )

    fig, ax = plt.subplots(figsize=(14, 7))
    colors = sns.color_palette("muted")

    sns.scatterplot(
        data=plot_df,
        x="Datetime",
        y="Latency (ms)",
        color=colors[0],
        alpha=0.45,
        s=24,
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
        estimator=None,
        errorbar=None,
        label=f"Rolling Mean ({rolling_window} samples)",
        ax=ax,
    )

    ax.set_title(
        "Overall Message Latency Over Time",
        fontsize=_AXIS_FONT_SIZE,
        fontweight="bold",
    )
    ax.set_xlabel("Time (UTC)", fontsize=_AXIS_FONT_SIZE)
    ax.set_ylabel("Latency (ms)", fontsize=_AXIS_FONT_SIZE)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S", tz="UTC"))
    ax.legend(loc="upper left")
    fig.autofmt_xdate()
    sns.despine(ax=ax, top=True, right=True)

    fig.savefig(
        plots_dir / "latency_timeseries.png",
        dpi=150,
        bbox_inches="tight",
    )
    plt.close(fig)


def main() -> None:
    """Run overall latency analysis."""
    parser = argparse.ArgumentParser(
        description="Calculate overall latency from V2X transmit and receive logs."
    )
    parser.add_argument(
        "--transmit-log",
        type=Path,
        required=True,
        help="Path to the transmit log.",
    )
    parser.add_argument(
        "--receive-log",
        type=Path,
        required=True,
        help="Path to the receive log.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("."),
        help="Output directory for CSV data and plots.",
    )
    parser.add_argument(
        "--max-latency-ms",
        type=int,
        default=200,
        help="Maximum displayed x-axis value for histogram and CDF plots.",
    )
    parser.add_argument(
        "--rolling-window",
        type=int,
        default=20,
        help="Number of samples used for the rolling latency mean.",
    )
    parser.add_argument("--debug", action="store_true")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if not args.transmit_log.is_file():
        parser.error(f"Transmit log does not exist: {args.transmit_log}")

    if not args.receive_log.is_file():
        parser.error(f"Receive log does not exist: {args.receive_log}")

    if args.max_latency_ms <= 0:
        parser.error("--max-latency-ms must be greater than zero.")

    if args.rolling_window <= 0:
        parser.error("--rolling-window must be greater than zero.")

    data_dir = args.output_dir / "data"
    plots_dir = args.output_dir / "plots"
    data_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    tx_entries = read_log_entries(args.transmit_log)
    rx_entries = read_log_entries(args.receive_log)

    logging.info(
        "Loaded %d TX messages and %d RX messages.",
        len(tx_entries),
        len(rx_entries),
    )

    latency_results = calculate_latency(tx_entries, rx_entries)
    latency_df = results_to_dataframe(latency_results)

    if latency_df.empty:
        logging.warning("No matching TX/RX messages found.")
        return

    latency_df.to_csv(data_dir / "latency_results.csv", index=False)

    latency_series = latency_df["Latency (ms)"]
    mean_latency = float(latency_series.mean())
    median_latency = float(latency_series.median())
    p95_latency = float(latency_series.quantile(0.95))
    p99_latency = float(latency_series.quantile(0.99))

    logging.info("Matched messages: %d", len(latency_df))
    logging.info(
        "Mean: %.2f ms | Median: %.2f ms | P95: %.2f ms | P99: %.2f ms",
        mean_latency,
        median_latency,
        p95_latency,
        p99_latency,
    )

    plot_latency_histogram(latency_df, plots_dir, args.max_latency_ms)
    plot_latency_cdf(latency_df, plots_dir, args.max_latency_ms)
    plot_latency_timeseries(latency_df, plots_dir, args.rolling_window)

    print(
        "RESULT_SUMMARY: "
        f"mean={mean_latency:.2f} ms, "
        f"median={median_latency:.2f} ms, "
        f"p95={p95_latency:.2f} ms, "
        f"p99={p99_latency:.2f} ms"
    )


if __name__ == "__main__":
    main()