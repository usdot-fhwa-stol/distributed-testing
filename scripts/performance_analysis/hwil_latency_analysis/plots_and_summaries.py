"""
Messaging Performance Analyzer
This script analyzes messaging performance between a message source and a message destination
by reading log files, calculating message latency,
and generating plots for visualization.
"""

import re
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

def add_threshold_summary(
    summary: dict[str, Any],
    df: pd.DataFrame,
    *,
    threshold: float | None,
) -> dict[str, Any]:
    """Add latency threshold counts, percentage, and result to a summary.

    If ``threshold`` is None, the summary is marked as "NOT_CONFIGURED"
    rather than PASS/FAIL.
    """
    if threshold is None:
        summary.update(
            {
                "latency_threshold_ms": None,
                "passed_samples": None,
                "failed_samples": None,
                "pass_percent": None,
                "threshold_result": "NOT_CONFIGURED",
            }
        )
        return summary

    latencies = pd.to_numeric(
        df["Latency (ms)"],
        errors="coerce",
    ).dropna()

    total_samples = len(latencies)
    passed_samples = int((latencies < threshold).sum())
    failed_samples = total_samples - passed_samples
    pass_percent = passed_samples / total_samples * 100.0 if total_samples else 0.0

    summary.update(
        {
            "latency_threshold_ms": threshold,
            "passed_samples": passed_samples,
            "failed_samples": failed_samples,
            "pass_percent": round(pass_percent, 2),
            "threshold_result": (
                "PASS" if total_samples > 0 and failed_samples == 0 else "FAIL"
            ),
        }
    )

    return summary


def create_plots_and_report(
    df: pd.DataFrame,
    output_dir: Path,
    *,
    message_type: str,
    run_name: str,
    max_latency_ms: float,
    rolling_window: int,
    threshold: float | None,
) -> dict[str, Any]:
    """
    Persist a latency DataFrame as the standard report: the raw results CSV,
    the histogram/CDF/timeseries plots, and a results_summary.csv (with
    threshold pass/fail info). Returns the summary dict.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    df.to_csv(
        output_dir / "latency_results.csv",
        index=False,
    )

    plot_latency_histogram(df, output_dir, max_latency_ms)
    plot_latency_cdf(df, output_dir, max_latency_ms)
    plot_latency_timeseries(df, output_dir, rolling_window)

    summary = calculate_statistics(
        df,
        message_type=message_type,
        run_name=run_name,
    )
    summary = add_threshold_summary(
        summary,
        df,
        threshold=threshold,
    )

    pd.DataFrame([summary]).to_csv(
        output_dir / "results_summary.csv",
        index=False,
    )

    return summary


def calculate_jitter(df: pd.DataFrame) -> float:
    if len(df) < 2:
        return float("nan")

    ordered = df.sort_values("Tx Timestamp (ms)")
    latency = ordered["Latency (ms)"].astype(float)
    return float(latency.diff().abs().dropna().mean())
    
def calculate_statistics(
    df: pd.DataFrame,
    *,
    message_type: str,
    run_name: str,
) -> dict[str, Any]:
    latency = pd.to_numeric(df["Latency (ms)"], errors="coerce")
    latency = latency[np.isfinite(latency)]

    jitter = calculate_jitter(df)
    standard_deviation = float(latency.std()) if len(latency) > 1 else 0.0

    return {
        "message_type": message_type,
        "run_name": run_name,
        "samples": len(latency),
        "min_ms": round(float(latency.min()), 2),
        "max_ms": round(float(latency.max()), 2),
        "mean_ms": round(float(latency.mean()), 2),
        "median_ms": round(float(latency.median()), 2),
        "p95_ms": round(float(latency.quantile(0.95)), 2),
        "p99_ms": round(float(latency.quantile(0.99)), 2),
        "jitter_ms": round(jitter, 2) if np.isfinite(jitter) else "NA",
        "std_dev": round(standard_deviation, 2),
    }