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
    """Create a latency histogram"""
    latencies = latency_data[LATENCY_COLUMN]

    n_overflow = (latencies > max_latency_ms).sum()

    bin_edges = np.linspace(0.0, max_latency_ms, HISTOGRAM_BINS + 1)

    if n_overflow > 0:
        # Add one extra bin at the end to catch everything above max_latency_ms
        bin_width = bin_edges[1] - bin_edges[0]
        overflow_edge = bin_edges[-1] + bin_width
        bin_edges = np.append(bin_edges, overflow_edge)
        display_latencies = latencies.clip(lower=0.0, upper=overflow_edge - 1e-6)
    else:
        display_latencies = latencies.clip(lower=0.0, upper=max_latency_ms)

    figure, axis = plt.subplots(figsize=(12, 7))

    sns.histplot(
        display_latencies,
        bins=bin_edges,
        edgecolor="white",
        ax=axis,
    )

    if n_overflow > 0:
        patches = axis.patches
        patches[-1].set_facecolor("orange")
    
        xticks = list(bin_edges[:-1])
        axis.set_xticks(xticks)
        axis.set_xticklabels(
            [
                f"{max_latency_ms:.0f}+" if abs(t - max_latency_ms) < 1e-6 else f"{t:.0f}"
                for t in xticks
            ],
            rotation=45,
            ha="right",
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

# SPDU chain plots. Stage colours follow a fixed categorical order; the reference
# stage (0 ms) is drawn in neutral ink.
CHAIN_REFERENCE_COLOR = "#52514e"
CHAIN_STAGE_COLORS = ("#2a78d6", "#eb6834", "#1baf7a")
CHAIN_SURFACE = "#fcfcfb"
CHAIN_TEXT = "#0b0b0b"
CHAIN_TEXT_MUTED = "#52514e"
CHAIN_GRID = "#e4e3df"


def _chain_style(axis) -> None:
    """Apply the chain plot styling to an axis."""
    axis.set_facecolor(CHAIN_SURFACE)
    for side in ("top", "right"):
        axis.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axis.spines[side].set_color(CHAIN_TEXT_MUTED)
    axis.tick_params(colors=CHAIN_TEXT_MUTED, labelcolor=CHAIN_TEXT_MUTED)
    axis.xaxis.label.set_color(CHAIN_TEXT_MUTED)
    axis.yaxis.label.set_color(CHAIN_TEXT_MUTED)
    axis.grid(color=CHAIN_GRID, linewidth=0.8)
    axis.set_axisbelow(True)


def _chain_boxplot(axis, values, color: str, **kwargs) -> None:
    """Draw one boxplot with outliers in a single colour."""
    axis.boxplot(
        values,
        widths=0.5,
        patch_artist=True,
        showfliers=True,
        boxprops=dict(facecolor=color + "33", edgecolor=color, linewidth=1.5),
        medianprops=dict(color=color, linewidth=2),
        whiskerprops=dict(color=color, linewidth=1.5),
        capprops=dict(color=color, linewidth=1.5),
        flierprops=dict(marker="o", markersize=4, markerfacecolor="none",
                        markeredgecolor=color, alpha=0.7),
        **kwargs,
    )


def _chain_stages(labels: dict[str, str]) -> tuple[str, dict[str, str], dict[str, str]]:
    """Split ordered stage labels into (reference, downstream labels, downstream colours)."""
    reference, *downstream = labels
    return (
        reference,
        {stage: labels[stage] for stage in downstream},
        dict(zip(downstream, CHAIN_STAGE_COLORS)),
    )


def _chain_x_limits(table: pd.DataFrame, stages) -> tuple[float, float]:
    """Return a shared x-range covering every stage latency and 0 ms."""
    values = pd.concat([table[f"lat_{stage}_ms"] for stage in stages]).dropna()
    high = max(float(values.max()), 1.0) if not values.empty else 1.0
    low = min(float(values.min()), 0.0) if not values.empty else 0.0
    return low - 0.03 * high, high * 1.03


def _save_chain_figure(figure, path: Path) -> None:
    figure.savefig(path, dpi=150, bbox_inches="tight", facecolor=CHAIN_SURFACE)
    plt.close(figure)


def plot_chain_e2e_histogram(table: pd.DataFrame, output_dir: Path, labels: dict[str, str]) -> None:
    """Save a histogram of reference-to-last-stage latency with a boxplot (outliers shown) above it.

    Args:
        table: Output of analysis_spdu_chain.match_chain.
        output_dir: Directory for spdu_e2e_latency.png.
        labels: Ordered stage -> label, reference stage first.
    """
    reference, downstream, colors = _chain_stages(labels)
    last = list(downstream)[-1]
    latencies = table[f"lat_{last}_ms"].dropna()
    if latencies.empty:
        return

    color = colors[last]
    figure, (box_axis, hist_axis) = plt.subplots(
        2, 1, sharex=True, figsize=(8, 5), facecolor=CHAIN_SURFACE,
        gridspec_kw=dict(height_ratios=[1, 4], hspace=0.05),
    )
    _chain_boxplot(box_axis, latencies, color, orientation="horizontal")

    bin_ms = 5
    low = bin_ms * np.floor(latencies.min() / bin_ms)
    high = bin_ms * (np.floor(latencies.max() / bin_ms) + 1)
    hist_axis.hist(latencies, bins=np.arange(low, high + bin_ms, bin_ms), color=color,
                   edgecolor=CHAIN_SURFACE, linewidth=0.5)

    # Stagger the labels vertically so they never collide.
    for value, name, offset in ((latencies.median(), "median", -4),
                                (latencies.quantile(0.95), "p95", -20)):
        hist_axis.axvline(value, color=CHAIN_TEXT_MUTED, linestyle="--", linewidth=1)
        hist_axis.annotate(f"{name} {value:.1f} ms", xy=(value, 1),
                           xycoords=("data", "axes fraction"), xytext=(4, offset),
                           textcoords="offset points", va="top", color=CHAIN_TEXT_MUTED, fontsize=9)

    for axis in (box_axis, hist_axis):
        _chain_style(axis)
    box_axis.set_yticks([])
    box_axis.grid(axis="y", visible=False)
    hist_axis.grid(axis="x", visible=False)
    hist_axis.set_xlabel(f"End-to-end latency, {labels[reference]} → {labels[last]} (ms)")
    hist_axis.set_ylabel(f"Messages per {bin_ms} ms bin")
    figure.suptitle(f"End-to-end latency (n={len(latencies)}, {len(table) - len(latencies)} not received)",
                    x=0.125, ha="left", color=CHAIN_TEXT)
    _save_chain_figure(figure, output_dir / "spdu_e2e_latency.png")


def plot_chain_stage_boxplot(table: pd.DataFrame, output_dir: Path, labels: dict[str, str]) -> None:
    """Save a horizontal boxplot (outliers shown) of latency from the reference stage, one box per stage.

    Args:
        table: Output of analysis_spdu_chain.match_chain.
        output_dir: Directory for spdu_latency_by_stage.png.
        labels: Ordered stage -> label, reference stage first.
    """
    _, downstream, colors = _chain_stages(labels)
    stages = [stage for stage in downstream if table[f"lat_{stage}_ms"].notna().any()]
    if not stages:
        return

    figure, axis = plt.subplots(figsize=(8, 4), facecolor=CHAIN_SURFACE)
    positions = list(range(len(stages), 0, -1))
    for position, stage in zip(positions, stages):
        latencies = table[f"lat_{stage}_ms"].dropna()
        _chain_boxplot(axis, [latencies], colors[stage], positions=[position], orientation="horizontal")
        median = latencies.median()
        axis.annotate(f"median {median:.1f}", xy=(median, position + 0.3), va="bottom",
                      color=CHAIN_TEXT_MUTED, fontsize=9)

    axis.set_yticks(positions, [f"{downstream[s]}\n(n={table[f'lat_{s}_ms'].notna().sum()})"
                                for s in stages])
    axis.set_ylim(0.4, len(stages) + 0.8)
    axis.set_xlim(*_chain_x_limits(table, downstream))
    _chain_style(axis)
    axis.grid(axis="y", visible=False)
    axis.set_xlabel("Latency from reference send (ms)")
    axis.set_title("Latency by stage (outliers shown)", loc="left", color=CHAIN_TEXT)
    _save_chain_figure(figure, output_dir / "spdu_latency_by_stage.png")


def plot_chain_per_message(table: pd.DataFrame, output_dir: Path, labels: dict[str, str]) -> None:
    """Save a dot plot with one row per message and one dot per stage at its latency.

    Rows are sorted by latency at the last stage, lowest on top; messages that never
    reached the last stage are sorted by their highest latency and placed last.

    Args:
        table: Output of analysis_spdu_chain.match_chain.
        output_dir: Directory for spdu_latency_per_message.png.
        labels: Ordered stage -> label, reference stage first.
    """
    reference, downstream, colors = _chain_stages(labels)
    last = list(downstream)[-1]
    latency_columns = [f"lat_{stage}_ms" for stage in downstream]
    ordered = table.assign(
        _unreached=table[f"lat_{last}_ms"].isna(),
        _key=table[f"lat_{last}_ms"].fillna(table[latency_columns].max(axis=1)),
    ).sort_values(["_unreached", "_key"], ignore_index=True)
    if ordered.empty:
        return

    figure, axis = plt.subplots(figsize=(8, 4.5), facecolor=CHAIN_SURFACE)
    axis.scatter(np.zeros(len(ordered)), ordered.index, s=4, color=CHAIN_REFERENCE_COLOR,
                 linewidths=0, label=f"{labels[reference]} (0 ms reference)")
    for stage, label in downstream.items():
        reached = ordered[f"lat_{stage}_ms"].dropna()
        axis.scatter(reached, reached.index, s=4, color=colors[stage], linewidths=0,
                     label=f"{label} (n={len(reached)})")

    axis.set_xlim(*_chain_x_limits(table, downstream))
    axis.set_ylim(len(ordered), -1)
    _chain_style(axis)
    axis.grid(axis="y", visible=False)
    axis.set_xlabel("Latency from reference send (ms)")
    axis.set_ylabel("Message rank by end-to-end latency\n(lowest on top)")
    axis.set_title(f"Per-message latency at each stage (n={len(ordered)})", loc="left", color=CHAIN_TEXT)
    axis.legend(loc="upper right", frameon=False, markerscale=3, labelcolor=CHAIN_TEXT_MUTED)
    _save_chain_figure(figure, output_dir / "spdu_latency_per_message.png")
