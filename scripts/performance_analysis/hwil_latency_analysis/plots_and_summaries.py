"""Create plots and summary reports from latency data."""

from pathlib import Path
from typing import Any

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

LATENCY_COLUMN = "Latency (ms)"
TX_TIMESTAMP_COLUMN = "Tx Timestamp (ms)"
DATETIME_COLUMN = "Datetime"
HISTOGRAM_BINS = 20


def format_route(route: str) -> str:
    """Format an endpoint route string for plot title."""
    endpoints = [endpoint.strip() for endpoint in route.split("->")]

    if len(endpoints) == 2:
        return f"{endpoints[0]} \u2192 {endpoints[1]}"

    return route


def plot_latency_histogram(
    latency_data: pd.DataFrame,
    output_dir: Path,
    route: str,
    max_latency_ms: float,
    threshold: float | None,
) -> None:
    """Create a latency histogram."""
    latencies = latency_data[LATENCY_COLUMN]
    display_latencies = latencies.clip(
        lower=0.0,
        upper=max_latency_ms,
    )

    figure, axis = plt.subplots(figsize=(12, 7))

    sns.histplot(
        display_latencies,
        bins=HISTOGRAM_BINS,
        binrange=(0.0, max_latency_ms),
        edgecolor="white",
        ax=axis,
    )

    if threshold is not None:
        axis.axvline(
            threshold,
            color="red",
            linestyle="--",
            linewidth=2,
            label=f"Threshold: {threshold:.2f} ms",
        )
        axis.legend()

    axis.set_title(
        f"Latency Distribution\n{format_route(route)}",
        fontweight="bold",
    )
    axis.set_xlabel("Latency (ms)")
    axis.set_ylabel("Number of Messages")

    figure.tight_layout()
    figure.savefig(
        output_dir / "latency_histogram.png",
        dpi=150,
    )
    plt.close(figure)


def plot_latency_timeseries(
    latency_data: pd.DataFrame,
    output_dir: Path,
    route: str,
    rolling_window: int,
    threshold: float | None,
) -> None:
    """Create a latency time-series plot."""
    plot_data = latency_data.sort_values(
        TX_TIMESTAMP_COLUMN
    ).copy()

    plot_data["Rolling Mean (ms)"] = (
        plot_data[LATENCY_COLUMN]
        .rolling(
            window=rolling_window,
            min_periods=1,
        )
        .mean()
    )

    figure, axis = plt.subplots(figsize=(14, 7))

    axis.scatter(
        plot_data[DATETIME_COLUMN],
        plot_data[LATENCY_COLUMN],
        alpha=0.45,
        s=24,
        label="Latency",
    )
    axis.plot(
        plot_data[DATETIME_COLUMN],
        plot_data["Rolling Mean (ms)"],
        color="red",
        linewidth=2,
        label=f"Rolling Mean ({rolling_window} samples)",
    )

    if threshold is not None:
        axis.axhline(
            threshold,
            color="green",
            linestyle="--",
            linewidth=2,
            label=f"Threshold: {threshold:.2f} ms",
        )

    axis.set_title(
        f"Latency Over Time\n{format_route(route)}",
        fontweight="bold",
    )
    axis.set_xlabel("Transmission Time (UTC)")
    axis.set_ylabel("Latency (ms)")
    axis.xaxis.set_major_formatter(
        mdates.DateFormatter(
            "%H:%M:%S",
            tz="UTC",
        )
    )
    axis.legend()

    figure.autofmt_xdate()
    figure.tight_layout()
    figure.savefig(
        output_dir / "latency_timeseries.png",
        dpi=150,
    )
    plt.close(figure)


def calculate_jitter(latency_data: pd.DataFrame) -> float:
    """Calculate mean absolute latency variation."""
    ordered_latencies = latency_data.sort_values(
        TX_TIMESTAMP_COLUMN
    )[LATENCY_COLUMN]

    if len(ordered_latencies) < 2:
        return 0.0

    return float(
        ordered_latencies.diff().abs().dropna().mean()
    )


def calculate_statistics(
    latency_data: pd.DataFrame,
    message_type: str,
    run_name: str,
) -> dict[str, Any]:
    """Calculate latency summary statistics."""
    latencies = latency_data[LATENCY_COLUMN]

    return {
        "message_type": message_type,
        "run_name": run_name,
        "samples": len(latencies),
        "min_ms": round(float(latencies.min()), 2),
        "max_ms": round(float(latencies.max()), 2),
        "mean_ms": round(float(latencies.mean()), 2),
        "median_ms": round(float(latencies.median()), 2),
        "p95_ms": round(float(latencies.quantile(0.95)), 2),
        "p99_ms": round(float(latencies.quantile(0.99)), 2),
        "jitter_ms": round(calculate_jitter(latency_data), 2),
        "std_dev_ms": round(float(latencies.std()), 2),
    }


def add_threshold_summary(
    summary: dict[str, Any],
    latency_data: pd.DataFrame,
    threshold: float | None,
) -> None:
    """Add threshold results to a report summary."""
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
        return

    latencies = latency_data[LATENCY_COLUMN]
    passed_samples = int((latencies <= threshold).sum())
    failed_samples = len(latencies) - passed_samples
    pass_percent = passed_samples / len(latencies) * 100.0

    summary.update(
        {
            "latency_threshold_ms": threshold,
            "passed_samples": passed_samples,
            "failed_samples": failed_samples,
            "pass_percent": round(pass_percent, 2),
            "threshold_result": (
                "PASS" if failed_samples == 0 else "FAIL"
            ),
        }
    )


def create_plots_and_report(
    latency_data: pd.DataFrame,
    output_dir: Path,
    message_type: str,
    run_name: str,
    max_latency_ms: float,
    rolling_window: int,
    threshold: float | None,
) -> dict[str, Any]:
    """Create latency plots, data output, and summary output."""
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    latency_data.to_csv(
        output_dir / "latency_results.csv",
        index=False,
    )

    plot_latency_histogram(
        latency_data,
        output_dir,
        route=message_type,
        max_latency_ms=max_latency_ms,
        threshold=threshold,
    )
    plot_latency_timeseries(
        latency_data,
        output_dir,
        route=message_type,
        rolling_window=rolling_window,
        threshold=threshold,
    )

    summary = calculate_statistics(
        latency_data,
        message_type=message_type,
        run_name=run_name,
    )
    add_threshold_summary(
        summary,
        latency_data,
        threshold=threshold,
    )

    pd.DataFrame([summary]).to_csv(
        output_dir / "results_summary.csv",
        index=False,
    )

    return summary