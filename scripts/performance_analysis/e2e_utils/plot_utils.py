## Utility functions for generating and saving plots from run data gathered with data_utils.

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

from .data_utils import RunDataFrames

sns.set_theme(style="whitegrid")

_AXIS_FONT_SIZE = 16
_NUM_BINS = 10


def _run_sort_key(run_number: str) -> int:
    s = run_number.lstrip("RrVv")
    try:
        return int(float(s))
    except ValueError:
        return 0


def _gather_latency_data(
    source_site: str,
    destination_site: str,
    run_data_frames: RunDataFrames,
) -> pd.Series:
    """Concatenate latency data for a site pair across all runs.

    Steps:
        1. Iterate over runs in ascending sort order via `_run_sort_key`.
        2. Skip runs that have no data for the given site pair.
        3. Concatenate latency values from the DataFrame of each run.
        4. Return only non-negative, non-null values.

    Args:
        source_site: Source site name.
        destination_site: Destination site name.
        run_data_frames: Nested mapping of run number to site pair DataFrames.
    """
    series = [
        run_data_frames[run_number][source_site][destination_site][0][1]["Latency"]
        for run_number in sorted(run_data_frames.keys(), key=_run_sort_key)
        if source_site in run_data_frames[run_number]
        and destination_site in run_data_frames[run_number][source_site]
    ]

    if not series:
        return pd.Series(dtype="float64")

    return pd.concat(series, ignore_index=True).pipe(lambda s: s[s >= 0].dropna())


def plot_grouped_histogram(
    plots_dir: Path,
    data_type: str,
    run_data_frames: RunDataFrames,
    all_source_sites: set[str],
    all_destination_sites: set[str],
    max_bin_value: int,
    destination_colors: dict[str, tuple],
) -> None:
    """Generate and save a grouped bar histogram of latency per source site.

    Steps:
        1. For each source site, collect clipped latency arrays for every
           destination site that has data.
        2. Concatenate all destination data into a single DataFrame for seaborn.
        3. Plot a dodged bar histogram with per-destination colouring.
        4. Annotate each bar with its sample count.
        5. Apply axis labels, tick formatting, grid, and legend.
        6. Save the figure to `plots_dir` and close it.

    Args:
        plots_dir: Directory where plot images will be saved.
        data_type: Message type label used in the plot title and filename.
        run_data_frames: Nested mapping of run number to site pair DataFrames.
        all_source_sites: Set of all source site names to iterate over.
        all_destination_sites: Set of all destination site names to plot against.
        max_bin_value: Upper bin limit in milliseconds.
        destination_colors: Mapping of destination site name to its assigned color.
    """
    bin_width = max_bin_value / _NUM_BINS
    overflow_center = max_bin_value + bin_width / 2
    n_bins = _NUM_BINS + 2
    binrange = (-bin_width, max_bin_value + bin_width)

    for source_site in all_source_sites:
        print(f"source_site: {source_site}")

        dest_dfs: list[pd.DataFrame] = []
        palette: dict[str, tuple] = {}
        total_samples = 0
        has_overflow = False

        for destination_site in sorted(all_destination_sites):
            if source_site == destination_site:
                continue

            latency = _gather_latency_data(source_site, destination_site, run_data_frames)
            if latency.empty:
                continue

            if float(latency.max()) > max_bin_value:
                has_overflow = True

            label = f"{source_site} → {destination_site}"
            palette[label] = destination_colors[destination_site]
            total_samples += latency.size
            print(f"\t{label}: {latency.size} samples")

            dest_dfs.append(
                pd.DataFrame({
                    "Latency": np.clip(latency.to_numpy(), 0, overflow_center),
                    "Pair": label,
                })
            )

        if not dest_dfs:
            print(f"\tNo data to plot for {source_site}, skipping.")
            continue

        fig, ax = plt.subplots(figsize=(16, 9))

        sns.histplot(
            data=pd.concat(dest_dfs, ignore_index=True),
            x="Latency",
            hue="Pair",
            palette=palette,
            alpha=0.85,
            bins=n_bins,
            binrange=binrange,
            multiple="dodge",
            stat="count",
            shrink=0.85,
            ax=ax,
        )

        for container in getattr(ax, "containers", []):
            labels = [f"{int(bar.get_height())}" if bar.get_height() > 0 else "" for bar in container]
            ax.bar_label(container, labels=labels, rotation=90, padding=4, fontsize=7)

        ax.set_ylim(top=ax.get_ylim()[-1] * 1.18)

        tick_positions = np.arange(0, max_bin_value + bin_width, bin_width)
        tick_labels = [f"{int(t)}" for t in tick_positions[:-1]] + (
            [f">{max_bin_value}"] if has_overflow else [f"{int(max_bin_value)}"]
        )
        ax.set_xticks(tick_positions)
        ax.set_xticklabels(tick_labels, rotation=45, ha="right", fontsize=_AXIS_FONT_SIZE - 2)
        ax.set_xlim(-bin_width / 2, max_bin_value + bin_width * 1.5)

        ax.yaxis.grid(True, linestyle="--", linewidth=0.6, alpha=0.6, color="gray")
        ax.set_axisbelow(True)
        ax.margins(x=0.02)
        ax.tick_params(axis="both", labelsize=_AXIS_FONT_SIZE - 2)
        sns.despine(ax=ax, left=False, right=True, top=True, bottom=False)

        ax.set_title(
            f"Grouped Latency Histogram — {source_site} to All Destinations\n"
            f"Max {max_bin_value} ms  |  {data_type}  |  {total_samples:,} total samples",
            fontsize=_AXIS_FONT_SIZE,
            fontweight="bold",
            pad=12,
        )
        ax.set_xlabel("Latency (ms)", fontsize=_AXIS_FONT_SIZE, fontweight="bold")
        ax.set_ylabel("Number of Samples", fontsize=_AXIS_FONT_SIZE, fontweight="bold")

        sns.move_legend(
            ax,
            loc="upper left",
            bbox_to_anchor=(1.02, 1),
            borderaxespad=0,
            frameon=True,
            framealpha=0.9,
            edgecolor="lightgray",
            title="Pair",
            title_fontsize=_AXIS_FONT_SIZE - 1,
        )

        plot_path = plots_dir / f"{source_site}_all_runs_{max_bin_value}_GHIST_{data_type}.png"
        fig.savefig(str(plot_path), dpi=150, bbox_inches="tight")
        plt.close(fig)


def plot_cumulative_histogram(
    plots_dir: Path,
    data_type: str,
    run_data_frames: RunDataFrames,
    all_source_sites: set[str],
    all_destination_sites: set[str],
    max_bin_value: int,
    destination_colors: dict[str, tuple],
) -> None:
    """Generate and save a cumulative probability histogram of latency per source site.

    Steps:
        1. For each source site, collect clipped latency arrays for every
           destination site that has data.
        2. Plot each destination as a cumulative step histogram on a shared axes.
        3. Annotate each bin with its cumulative probability value.
        4. Apply axis labels, tick formatting, grid, and legend.
        5. Save the figure to `plots_dir` and close it.

    Args:
        plots_dir: Directory where plot images will be saved.
        data_type: Message type label used in the plot title and filename.
        run_data_frames: Nested mapping of run number to site pair DataFrames.
        all_source_sites: Set of all source site names to iterate over.
        all_destination_sites: Set of all destination site names to plot against.
        max_bin_value: Upper bin limit in milliseconds.
        destination_colors: Mapping of destination site name to its assigned color.
    """
    bin_width = max_bin_value / _NUM_BINS
    n_bins = _NUM_BINS + 2
    binrange = (-bin_width, max_bin_value + bin_width)
    bin_edges = np.linspace(*binrange, n_bins + 1)

    for source_site in all_source_sites:
        print(f"source_site: {source_site}")

        dest_data: list[np.ndarray] = []
        dest_labels: list[str] = []
        dest_colors: list[tuple] = []
        total_samples = 0
        has_overflow = False

        for destination_site in sorted(all_destination_sites):
            if source_site == destination_site:
                continue

            latency = _gather_latency_data(source_site, destination_site, run_data_frames)
            if latency.empty:
                continue

            latency_np = latency.to_numpy()
            if latency_np.size == 0:
                continue

            if float(latency.max()) > max_bin_value:
                has_overflow = True

            label = f"{source_site} → {destination_site}"
            n_samples = latency_np.size
            total_samples += n_samples
            print(f"\t{label}: {n_samples} samples")

            dest_labels.append(label)
            dest_data.append(np.clip(latency_np, 0, max_bin_value + bin_width))
            dest_colors.append(destination_colors[destination_site])

        if not dest_data:
            print(f"\tNo data to plot for {source_site}, skipping.")
            continue

        fig, ax = plt.subplots(figsize=(16, 9))

        for data, label, color in zip(dest_data, dest_labels, dest_colors):
            sns.histplot(
                data=data,
                bins=n_bins,
                binrange=binrange,
                cumulative=True,
                stat="probability",
                element="step",
                fill=False,
                color=color,
                alpha=0.75,
                ax=ax,
                label=label,
            )

            counts, _ = np.histogram(data, bins=bin_edges)
            cumulative_probs = np.cumsum(counts) / counts.sum()
            bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

            for x, prob in zip(bin_centers, cumulative_probs):
                if prob == 0:
                    continue
                ax.annotate(
                    f"{prob:.2f}",
                    xy=(x, prob),
                    xytext=(0, 4),
                    textcoords="offset points",
                    ha="center",
                    va="bottom",
                    fontsize=7,
                    color=color,
                    alpha=0.85,
                )

        tick_positions = np.arange(0, max_bin_value + bin_width, bin_width)
        tick_labels = [f"{int(t)}" for t in tick_positions[:-1]] + (
            [f">{max_bin_value}"] if has_overflow else [f"{int(max_bin_value)}"]
        )
        ax.set_xticks(tick_positions)
        ax.set_xticklabels(tick_labels, rotation=45, ha="right", fontsize=_AXIS_FONT_SIZE - 2)
        ax.set_xlim(-bin_width / 2, max_bin_value + bin_width * 1.5)

        ax.yaxis.grid(True, linestyle="--", linewidth=0.6, alpha=0.6, color="gray")
        ax.set_axisbelow(True)
        ax.set_ylim(0, 1.05)
        ax.tick_params(axis="both", labelsize=_AXIS_FONT_SIZE - 2)
        sns.despine(ax=ax, left=False, right=True, top=True, bottom=False)

        ax.set_title(
            f"Cumulative Latency Histogram — {source_site} to All Destinations\n"
            f"Max {max_bin_value} ms  |  {data_type}  |  {total_samples:,} total samples",
            fontsize=_AXIS_FONT_SIZE,
            fontweight="bold",
            pad=12,
        )
        ax.set_xlabel("Latency (ms)", fontsize=_AXIS_FONT_SIZE, fontweight="bold")
        ax.set_ylabel("Probability of Occurence", fontsize=_AXIS_FONT_SIZE, fontweight="bold")
        ax.legend(
            loc="upper left",
            bbox_to_anchor=(1.02, 1),
            borderaxespad=0,
            frameon=True,
            framealpha=0.9,
            edgecolor="lightgray",
            title="Pair",
            title_fontsize=_AXIS_FONT_SIZE - 1,
        )

        plot_path = plots_dir / f"{source_site}_all_runs_{max_bin_value}_CHIST_{data_type}.png"
        fig.savefig(str(plot_path), dpi=150, bbox_inches="tight")
        plt.close(fig)


def plot_timeseries_by_destination(
    plots_dir: Path,
    data_type: str,
    run_data_frames: RunDataFrames,
    destination_colors: dict[str, tuple],
) -> None:
    """Generate and save per-run latency time series grouped by destination.

    Steps:
        1. Iterate over each run and source site.
        2. Plot one line per destination site, suppressing duplicate legend
           entries for sites that span multiple DataFrames.
        3. Apply axis labels, legend, and date formatting.
        4. Save the figure to `plots_dir` and close it.

    Args:
        plots_dir: Directory where plot images will be saved.
        data_type: Message type label used in the plot title and filename.
        run_data_frames: Nested mapping of run number to site pair DataFrames.
        destination_colors: Mapping of destination site name to its assigned color.
    """
    for run_number, run_data in run_data_frames.items():
        for source_site, destinations in run_data.items():
            fig, ax = plt.subplots(figsize=(10, 6))
            plotted_destinations: set[str] = set()

            for destination_site, dfs in destinations.items():
                color = destination_colors[destination_site]

                for _, df in dfs:
                    label = (
                        f"{source_site} to {destination_site}"
                        if destination_site not in plotted_destinations
                        else "_nolegend_"
                    )
                    plotted_destinations.add(destination_site)

                    sns.lineplot(
                        data=df.copy(),
                        x="Datetime",
                        y="Latency",
                        color=color,
                        alpha=1.0,
                        label=label,
                        estimator=None,
                        errorbar=None,
                        ax=ax,
                    )

            ax.set_title(f"Latency from {source_site} — Run {run_number} ({data_type})")
            ax.set_xlabel("Datetime")
            ax.set_ylabel("Latency (ms)")
            ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1), borderaxespad=0, ncol=1, title="Route")
            fig.autofmt_xdate()

            plot_path = plots_dir / f"{source_site}_single_run_{run_number}_{data_type}.png"
            fig.savefig(str(plot_path), bbox_inches="tight")
            plt.close(fig)


def plot_timeseries_by_run(
    plots_dir: Path,
    data_type: str,
    run_data_frames: RunDataFrames,
    all_source_sites: set[str],
    all_destination_sites: set[str],
    run_colors: dict[str, tuple],
) -> None:
    """Generate and save per-pair latency time series grouped by run.

    Steps:
        1. Skip the plot entirely when fewer than two runs are present.
        2. For each source/destination pair, plot one line per run with
           time zero-aligned to each run's first timestamp.
        3. Suppress duplicate legend entries for runs spanning multiple
           DataFrames.
        4. Apply axis labels and legend.
        5. Save the figure to `plots_dir` and close it.

    Args:
        plots_dir: Directory where plot images will be saved.
        data_type: Message type label used in the plot title and filename.
        run_data_frames: Nested mapping of run number to site pair DataFrames.
        all_source_sites: Set of all source site names to iterate over.
        all_destination_sites: Set of all destination site names to iterate over.
        run_colors: Mapping of run number to its assigned color.
    """
    if len(run_data_frames) <= 1:
        return

    for source_site in all_source_sites:
        for destination_site in all_destination_sites:
            if source_site == destination_site:
                continue

            fig, ax = plt.subplots(figsize=(10, 6))
            plotted_runs: set[str] = set()

            for run_number in sorted(run_data_frames.keys(), key=_run_sort_key):
                run_data = run_data_frames[run_number]
                if source_site not in run_data or destination_site not in run_data[source_site]:
                    continue

                for run_num, df in run_data[source_site][destination_site]:
                    df = df.copy()
                    df["Timestamp_in_s"] -= df["Timestamp_in_s"].iloc[0]

                    label = f"Run {run_num}" if run_num not in plotted_runs else "_nolegend_"
                    plotted_runs.add(run_num)

                    sns.lineplot(
                        data=df,
                        x="Timestamp_in_s",
                        y="Latency",
                        color=run_colors[run_number],
                        label=label,
                        estimator=None,
                        errorbar=None,
                        ax=ax,
                    )

            ax.set_title(f"Latency: {source_site} → {destination_site} ({data_type})")
            ax.set_xlabel("Time (s)")
            ax.set_ylabel("Latency (ms)")
            ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1), borderaxespad=0, ncol=1, title="Run")

            plot_path = plots_dir / f"{source_site}_to_{destination_site}_all_runs_{data_type}.png"
            fig.savefig(str(plot_path), bbox_inches="tight")
            plt.close(fig)