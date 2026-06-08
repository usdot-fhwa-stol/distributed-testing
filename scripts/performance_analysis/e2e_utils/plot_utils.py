from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

from .data_utils import RunDataFrames

sns.set_theme(style="whitegrid")

_AXIS_FONT_SIZE = 16
_NUM_BINS = 10


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
        run_data_frames.keys(), key=lambda x: int(x) if x.isdigit() else 0
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
    plot_styles: dict,
) -> None:

    for source_site in all_source_sites:
        print(f"source_site: {source_site}")

        dest_dfs: list[pd.DataFrame] = []
        has_overflow = False

        palette: dict[str, tuple] = {}

        for destination_site in all_destination_sites:
            if source_site == destination_site:
                continue

            latency = _gather_latency_data(
                source_site, destination_site, run_data_frames
            )
            if latency.empty:
                continue

            if float(latency.max()) > max_bin_value:
                has_overflow = True

            label = f"{source_site} to {destination_site}"
            palette[label] = plot_styles["source_destination_colors"][destination_site]
            print(f"\t{label}: {latency.size} samples")
            dest_dfs.append(
                pd.DataFrame(
                    {
                        "Latency": np.clip(latency.to_numpy(), 0, max_bin_value),
                        "Route": label,
                    }
                )
            )

        if not dest_dfs:
            print(f"\tNo data to plot for {source_site}, skipping.")
            continue

        plot_df = pd.concat(dest_dfs, ignore_index=True)
        fig, ax = plt.subplots(figsize=(16, 12))

        sns.histplot(
            data=plot_df,
            x="Latency",
            hue="Route",
            palette=palette,
            alpha=0.9,
            bins=_NUM_BINS,
            binrange=(0, max_bin_value),
            multiple="dodge",
            stat="count",
            shrink=0.9,
            ax=ax,
        )

        y_max = ax.get_ylim()[-1]
        threshold = y_max / 1500
        for container in getattr(ax, "containers", []):
            labels = [
                f"{int(bar.get_height())}" if bar.get_height() > threshold else ""
                for bar in container
            ]
            ax.bar_label(container, labels=labels, rotation=90, padding=4, fontsize=8)

        if has_overflow:
            ticks = ax.get_xticks()
            ax.set_xticks(ticks)
            ax.set_xticklabels(
                [f"{int(t)}" for t in ticks[:-1]] + [f">{max_bin_value}"]
            )

        ax.set_axisbelow(True)
        ax.margins(x=0.02)
        sns.despine(ax=ax, left=True, right=True, bottom=True)

        ax.set_title(
            f"Grouped Histogram of Latency from {source_site} (max {max_bin_value} ms, {data_type})",
            fontsize=_AXIS_FONT_SIZE,
            fontweight="bold",
        )
        ax.set_xlabel("Latency (ms)", fontsize=_AXIS_FONT_SIZE, fontweight="bold")
        ax.set_ylabel("Number of Samples", fontsize=_AXIS_FONT_SIZE, fontweight="bold")
        sns.move_legend(
            ax,
            loc="upper left",
            bbox_to_anchor=(1.02, 1),
            borderaxespad=0,
            frameon=False,
        )

        plot_path = (
            plots_dir / f"{source_site}_all_runs_{max_bin_value}"
            f"_GHIST_{data_type}.png"
        )
        fig.savefig(str(plot_path), bbox_inches="tight")
        plt.close(fig)


def plot_cumulative_histogram(
    plots_dir: Path,
    data_type: str,
    run_data_frames: RunDataFrames,
    all_source_sites: set[str],
    all_destination_sites: set[str],
    max_bin_value: int,
    plot_styles: dict,
) -> None:

    for source_site in all_source_sites:
        print(f"source_site: {source_site}")

        dest_data: list[np.ndarray] = []
        dest_labels: list[str] = []
        dest_colors: list[tuple] = []

        for destination_site in all_destination_sites:
            if source_site == destination_site:
                continue

            latency = _gather_latency_data(
                source_site, destination_site, run_data_frames
            )
            if latency.empty:
                continue

            label = f"{source_site} to {destination_site}"
            print(f"\t{label}: {latency.size} samples")
            dest_labels.append(label)
            dest_data.append(np.clip(latency.to_numpy(), 0, max_bin_value))
            dest_colors.append(
                plot_styles["source_destination_colors"][destination_site]
            )

        if not dest_data:
            print(f"\tNo data to plot for {source_site}, skipping.")
            continue

        fig, ax = plt.subplots(figsize=(16, 12))

        for data, label, color in zip(dest_data, dest_labels, dest_colors):
            sns.histplot(
                data=data,
                bins=_NUM_BINS,
                binrange=(0, max_bin_value),
                cumulative=True,
                stat="proportion",
                element="step",
                fill=False,
                color=color,
                alpha=0.9,
                ax=ax,
                label=label,
            )

        ax.set_title(
            f"Cumulative Latency from {source_site}"
            f" (max {max_bin_value} ms, {data_type})",
            fontsize=_AXIS_FONT_SIZE,
            fontweight="bold",
        )
        ax.set_xlabel("Latency (ms)", fontsize=_AXIS_FONT_SIZE, fontweight="bold")
        ax.set_ylabel(
            "Cumulative Proportion",
            fontsize=_AXIS_FONT_SIZE,
            fontweight="bold",
        )
        ax.legend(
            loc="upper left",
            bbox_to_anchor=(1.02, 1),
            borderaxespad=0,
            frameon=False,
            title="Route",
        )

        plot_path = (
            plots_dir / f"{source_site}_all_runs_{max_bin_value}"
            f"_CHIST_{data_type}.png"
        )
        fig.savefig(str(plot_path), bbox_inches="tight")
        plt.close(fig)


def plot_timeseries_by_destination(
    plots_dir: Path, data_type: str, run_data_frames: dict, plot_styles: dict
):
    for run_number, run_data in run_data_frames.items():
        for source_site, destinations in run_data.items():
            fig, ax = plt.subplots(figsize=(10, 6))
            plotted_destinations = set()

            for destination_site, dfs in destinations.items():
                color = plot_styles["source_destination_colors"][destination_site]
                alpha = plot_styles["source_destination_alphas"][destination_site][
                    "cdf"
                ]

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
            fig.savefig(single_run_plot_path, bbox_inches="tight")
            plt.close(fig)


def plot_timeseries_by_run(
    plots_dir,
    data_type,
    run_data_frames,
    plot_styles,
    all_source_sites,
    all_destination_sites,
):
    for source_site in all_source_sites:
        for destination_site in all_destination_sites:
            if source_site == destination_site:
                continue

            fig, ax = plt.subplots(figsize=(10, 6))

            if len(run_data_frames) <= 1:
                print("\nONLY ONE RUN, SKIPPING RUN PLOTS")
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

                color = plot_styles["run_colors"][run_number]

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
