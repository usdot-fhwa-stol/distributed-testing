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
    """Concatenates latency data for a site pair across all runs.

    Args:
        source_site: Source site name.
        destination_site: Destination site name.
        run_data_frames: Nested mapping of run number to site pair DataFrames.

    Returns:
        Series of non-negative, non-null latency values concatenated in
        ascending run order, or an empty Series if no data exists for
        the given pair.
    """
    all_runs_data = pd.Series(dtype="float64")

    for run_number in sorted(
        run_data_frames.keys(), key=_run_sort_key
    ):
        run_data = run_data_frames[run_number]
        if source_site not in run_data or destination_site not in run_data[source_site]:
            continue

        _, df = run_data[source_site][destination_site][0]
        all_runs_data = (
            df["Latency"]
            if all_runs_data.empty
            else pd.concat([all_runs_data, df["Latency"]], ignore_index=True)
        )

    return all_runs_data[all_runs_data >= 0].dropna()


def plot_grouped_histogram(
    plots_dir: Path,
    data_type: str,
    run_data_frames: RunDataFrames,
    all_source_sites: set[str],
    all_destination_sites: set[str],
    max_bin_value: int,
    destination_colors: dict[str, tuple],
) -> None:

    """Generates and saves a grouped bar histogram of latency for a source site.

    Args:
        plots_dir: Directory where plot images will be saved.
        data_type: Message type label used in the plot title and filename.
        run_data_frames: Nested mapping of run number to site pair DataFrames.
        all_source_sites: Set of all source site names to iterate over.
        all_destination_sites: Set of all destination site names to plot against.
        max_bin_value: Upper bin limit in milliseconds.
        destination_colors: Mapping of destination site name to its assigned color.
    """

    for source_site in all_source_sites:
        print(f"source_site: {source_site}")

        dest_dfs: list[pd.DataFrame] = []
        palette: dict[str, tuple] = {}
        total_samples = 0

        for destination_site in sorted(all_destination_sites):
            if source_site == destination_site:
                continue

            latency = _gather_latency_data(
                source_site, destination_site, run_data_frames
            )
            if latency.empty:
                continue

            label = f"{source_site} → {destination_site}"
            palette[label] = destination_colors[destination_site]
            n_samples = latency.size
            total_samples += n_samples
            print(f"\t{label}: {n_samples} samples")

            dest_dfs.append(
                pd.DataFrame(
                    {
                        "Latency": np.clip(latency.to_numpy(), 0, max_bin_value),
                        "Pair": label,
                    }
                )
            )

        if not dest_dfs:
            print(f"\tNo data to plot for {source_site}, skipping.")
            continue

        plot_df = pd.concat(dest_dfs, ignore_index=True)
        fig, ax = plt.subplots(figsize=(16, 9))

        bin_width = max_bin_value / _NUM_BINS
        bins = _NUM_BINS + 1
        binrange = (-bin_width, max_bin_value)
        
        sns.histplot(
            data=plot_df,
            x="Latency",
            hue="Pair",
            palette=palette,
            alpha=0.85,
            bins=bins,
            binrange=binrange,
            multiple="dodge",
            stat="count",
            shrink=0.85,
            ax=ax,
        )

        y_max = ax.get_ylim()[-1]
        ax.set_ylim(top=y_max * 1.18)

        ax.set_xlim(-bin_width/2, max_bin_value)
        ax.set_xticks(np.arange(0, max_bin_value + 1, max_bin_value / 10))

        for container in getattr(ax, "containers", []):
            labels = [
                f"{int(bar.get_height())}" if bar.get_height() > 0 else ""
                for bar in container
            ]
            ax.bar_label(container, labels=labels, rotation=90, padding=4, fontsize=7)

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

        plot_path = (
            plots_dir / f"{source_site}_all_runs_{max_bin_value}_GHIST_{data_type}.png"
        )
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

    """Generates and saves a cumulative proportion histogram of latency for a source site.

    Args:
        plots_dir: Directory where plot images will be saved.
        data_type: Message type label used in the plot title and filename.
        run_data_frames: Nested mapping of run number to site pair DataFrames.
        all_source_sites: Set of all source site names to iterate over.
        all_destination_sites: Set of all destination site names to plot against.
        max_bin_value: Upper bin limit in milliseconds.
        destination_colors: Mapping of destination site name to its assigned color.
    """
    
    for source_site in all_source_sites:
        print(f"source_site: {source_site}")

        dest_data: list[np.ndarray] = []
        dest_labels: list[str] = []
        dest_colors: list[tuple] = []
        total_samples = 0

        for destination_site in sorted(all_destination_sites):
            if source_site == destination_site:
                continue

            latency = _gather_latency_data(
                source_site, destination_site, run_data_frames
            )
            if latency.empty:
                continue

            latency_np = latency.to_numpy()
            
            
            if latency_np.size == 0:
                continue

            label = f"{source_site} → {destination_site}"
            n_samples = latency_np.size
            total_samples += n_samples
            print(f"\t{label}: {n_samples} samples")

            dest_labels.append(label)
            dest_data.append(np.clip(latency_np, 0, max_bin_value))
            dest_colors.append(destination_colors[destination_site])

        if not dest_data:
            print(f"\tNo data to plot for {source_site}, skipping.")
            continue

        fig, ax = plt.subplots(figsize=(16, 9))

        bin_width = max_bin_value / _NUM_BINS
        bins = _NUM_BINS + 1
        binrange = (-bin_width, max_bin_value)

        for data, label, color in zip(dest_data, dest_labels, dest_colors):
            sns.histplot(
                data=data,
                bins=bins,
                binrange=binrange,
                cumulative=True,
                stat="proportion",
                element="step",
                fill=False,
                color=color,
                alpha=0.75,
                ax=ax,
                label=label,
            )

        ax.yaxis.grid(True, linestyle="--", linewidth=0.6, alpha=0.6, color="gray")
        ax.set_axisbelow(True)
        ax.set_ylim(0, 1.05)

        ax.set_xlim(-bin_width/2, max_bin_value)
        ax.set_xticks(np.arange(0, max_bin_value + 1, max_bin_value / 10))

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
        ax.set_ylabel(
            "Cumulative Proportion", fontsize=_AXIS_FONT_SIZE, fontweight="bold"
        )
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

        plot_path = (
            plots_dir / f"{source_site}_all_runs_{max_bin_value}_CHIST_{data_type}.png"
        )
        fig.savefig(str(plot_path), dpi=150, bbox_inches="tight")
        plt.close(fig)


def plot_timeseries_by_destination(
    plots_dir: Path,
    data_type: str,
    run_data_frames: RunDataFrames,
    destination_colors: dict[str, tuple],
) -> None:
    for run_number, run_data in run_data_frames.items():
        for source_site, destinations in run_data.items():
            fig, ax = plt.subplots(figsize=(10, 6))
            plotted_destinations = set()

            for destination_site, dfs in destinations.items():
                color = destination_colors[destination_site]
                alpha = 1.0

                for _, df in dfs:
                    df = df.copy()
                    label = (
                        f"{source_site} to {destination_site}"
                        if destination_site not in plotted_destinations
                        else "_nolegend_"
                    )
                    plotted_destinations.add(destination_site)

                    sns.lineplot(
                        data=df,
                        x="Datetime",
                        y="Latency",
                        color=color,
                        alpha=alpha,
                        label=label,
                        estimator=None,
                        errorbar=None,
                        ax=ax,
                    )

            ax.set_title(f"Latency from {source_site} — Run {run_number} ({data_type})")
            ax.set_xlabel("Datetime")
            ax.set_ylabel("Latency (ms)")
            ax.legend(
                loc="upper left",
                bbox_to_anchor=(1.02, 1),
                borderaxespad=0,
                ncol=1,
                title="Route",
            )
            fig.autofmt_xdate()

            single_run_plot_path = (
                plots_dir / f"{source_site}_single_run_{run_number}_{data_type}.png"
            )
            fig.savefig(str(single_run_plot_path), bbox_inches="tight")
            plt.close(fig)


def plot_timeseries_by_run(
    plots_dir: Path,
    data_type: str,
    run_data_frames: RunDataFrames,
    all_source_sites: set[str],
    all_destination_sites: set[str],
    run_colors: dict[str, tuple],
) -> None:
    
    for source_site in all_source_sites:
        for destination_site in all_destination_sites:
            if source_site == destination_site:
                continue

            fig, ax = plt.subplots(figsize=(10, 6))

            if len(run_data_frames) <= 1:
                plt.close(fig)
                continue

            plotted_runs = set()
            for run_number in sorted(
                run_data_frames.keys(),
                key=lambda x: int(x) if x.isdigit() else 0,
            ):
                run_data = run_data_frames[run_number]
                if (
                    source_site not in run_data
                    or destination_site not in run_data[source_site]
                ):
                    continue

                color = run_colors[run_number]

                for run_num, df in run_data[source_site][destination_site]:
                    df = df.copy()
                    df["Timestamp_in_s"] -= df["Timestamp_in_s"].iloc[0]

                    label = (
                        f"Run {run_num}"
                        if run_num not in plotted_runs
                        else "_nolegend_"
                    )
                    plotted_runs.add(run_num)

                    sns.lineplot(
                        data=df,
                        x="Timestamp_in_s",
                        y="Latency",
                        color=color,
                        label=label,
                        estimator=None,
                        errorbar=None,
                        ax=ax,
                    )

            ax.set_title(f"Latency: {source_site} → {destination_site} ({data_type})")
            ax.set_xlabel("Time (s)")
            ax.set_ylabel("Latency (ms)")
            ax.legend(
                loc="upper left",
                bbox_to_anchor=(1.02, 1),
                borderaxespad=0,
                ncol=1,
                title="Run",
            )

            all_runs_plot_path = (
                plots_dir
                / f"{source_site}_to_{destination_site}_all_runs_{data_type}.png"
            )
            fig.savefig(all_runs_plot_path, bbox_inches="tight")
            plt.close(fig)
