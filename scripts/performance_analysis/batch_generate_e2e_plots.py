from typing import Sequence
import math
import time
import argparse
from pathlib import Path 
import hashlib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns


RESULTS_DIR = Path(__file__).parent / "results"

def process_and_plot_results(
    root_dir: Path,
    folder_prefix: str,
    data_type: str,
    generate_histogram: bool = True,
    generate_cdf: bool = True,
    max_bins: Sequence[int] | None = None,
) -> None:

    # Create the plots directory if it doesn't exist
    plots_dir = root_dir / "plots" / folder_prefix[:-1]
    plots_dir.mkdir(parents=True, exist_ok=True)

    run_data_frames, all_source_sites, all_destination_sites = load_and_parse_csv_data(
        root_dir, folder_prefix, data_type
    )

    plot_styles = assign_plot_styles(run_data_frames)

    if generate_histogram or generate_cdf:
        for max_bin in max_bins:
            plot_histogram_and_cdf(
                plots_dir,
                data_type,
                run_data_frames,
                plot_styles,
                all_source_sites,
                all_destination_sites,
                max_bin,
                generate_histogram=generate_histogram,
                generate_cdf=generate_cdf,
            )


def load_and_parse_csv_data(root_dir: Path, folder_prefix: str, data_type: str) -> tuple[dict, set[str], set[str]] | None:

    # Traverse the directories and find CSV files
    run_dirs = list(root_dir.glob(f"{folder_prefix}*"))

    run_data_frames: dict[str, dict] = {}
    all_source_sites: set[str] = set()
    all_destination_sites: set[str] = set()

    for run_dir in run_dirs:
        # Extract run number from directory name
        run_number = run_dir.name.replace(folder_prefix, "")[:2]
        csv_files = list(run_dir.glob("*.csv"))
        data_frames: dict[str, dict] = {}
        for csv_file in csv_files:
            print(f"csv_file: {csv_file}")

            # Ignore files that end with results_summary.csv
            if csv_file.endswith("results_summary.csv"):
                print(f"\tSkipping results summary")
                continue

            # Only want to consider files with the proper data type
            if (data_type.lower() + "_") not in csv_file:
                print(f"\tSkipping file that does not contain {data_type.lower()}")
                continue

            # Extract source and destination site names from the file name
            filename_to_split_parts = csv_file.name.split("_to_")

            source_site = filename_to_split_parts[0]
            if "2024" in source_site or "_" in source_site:
                source_site = source_site.split("_")[0]
            elif "-" in source_site:
                source_site = source_site.split("-")[0]

            source_site = source_site.upper()
            print(f"source_site: {source_site}")
            filename_type_split_parts = filename_to_split_parts[1].split(
                "_" + data_type.lower() + "_"
            )

            destination_site = filename_type_split_parts[0]
            if "2024" in destination_site or "_" in destination_site:
                destination_site = destination_site.split("_")[0]
            elif "-" in destination_site:
                destination_site = destination_site.split("-")[0]

            destination_site = destination_site.upper()
            print(f"destination_site: {destination_site}")

            df = pd.read_csv(csv_file)
            # Identify and keep the columns of interest
            date_col = [col for col in df if "timestamp" in col][0]
            performance_metric_col = [col for col in df if "_total_latency" in col][-1]
            df = df[[date_col, performance_metric_col]]
            # Convert the data to datetime (uses ns), assuming the date is in the recent past, if the number is greater than the current timestamp in s,
            if df[date_col][10] > int(time.time()):
                df["Timestamp_in_s"] = df[date_col] / 10**9
                df[date_col] = pd.to_datetime(df[date_col], unit="ns", errors="coerce")
            else:
                df["Timestamp_in_s"] = df[date_col]
                df[date_col] = pd.to_datetime(df[date_col], unit="s", errors="coerce")
            df[performance_metric_col] = pd.to_numeric(
                df[performance_metric_col], errors="coerce"
            )
            df.columns = [
                "Datetime",
                "Latency",
                "Timestamp_in_s",
            ]

            if source_site not in data_frames:
                data_frames[source_site] = {}
            if destination_site not in data_frames[source_site]:
                data_frames[source_site][destination_site] = []
            data_frames[source_site][destination_site].append((run_number, df))
            all_source_sites.add(source_site)
            all_destination_sites.add(destination_site)
        if data_frames:
            # Store data frames for the current run
            run_data_frames[run_number] = data_frames

    print(f"\n\n-----------IMPORT SUMMARY-----------")
    for run_number in run_data_frames:
        print(f"RUN: {run_number}")
        for source_site in run_data_frames[run_number]:
            print(f"\tsource_site: {source_site}")
            for dest_site in run_data_frames[run_number][source_site]:
                print(f"\t\tdest_site: {dest_site}")

    if not run_data_frames:
        print("No data found for the specified source site.")
        return

    return run_data_frames, all_source_sites, all_destination_sites


def get_deterministic_color(target_name: str, palette_name: str = 'tab20') -> tuple:
    """
    Deterministically assigns a safe RGB color based on a string hash using Seaborn.
    """
    # 1. Load the qualitative palette from Seaborn
    # This returns a list of RGB tuples
    palette = sns.color_palette(palette_name)
    
    # 2. Hash the target string
    hash_int = int(hashlib.md5(target_name.encode('utf-8')).hexdigest(), 16)
    
    # 3. Modulo the hash integer by the total number of colors in the palette
    # len(palette) dynamically checks how many colors are available
    return palette[hash_int % len(palette)]

def assign_plot_styles(run_data_frames: dict) -> dict[str, dict]:

    source_destination_colors: dict[str, tuple] = {}
    source_destination_alphas: dict[str, dict[str, float]] = {}
    
    hatch_types = ["/", "+", ".", "O", "X", "\\", "-", "*", "|"]
    source_dest_hatch_cycle = iter(hatch_types)
    source_dest_hatches: dict[str, str] = {}

    # Assign color and opacity to each destination
    for run_number, run_data in run_data_frames.items():
        for source_site, destinations in run_data.items():
            for destination_site, dfs in destinations.items():
                
                # 1. Assign consistent color via deterministic hash
                if destination_site not in source_destination_colors:
                    source_destination_colors[destination_site] = get_deterministic_color(destination_site)
                
                # 2. Replace linestyle with opacity mapping
                if destination_site not in source_destination_alphas:
                    source_destination_alphas[destination_site] = {
                        "cdf": 1.0,   # Solid line
                        "chist": 0.4  # Less solid/transparent line
                    }

                # 3. Maintain hatches if utilized elsewhere
                if destination_site not in source_dest_hatches:
                    try:
                        source_dest_hatches[destination_site] = next(source_dest_hatch_cycle)
                    except StopIteration:
                        source_dest_hatches[destination_site] = "" # Fallback

    # Assign consistent color for each run
    run_colors: dict[str, tuple] = {}
    
    # Sort run numbers in ascending order
    for run_number in sorted(
        run_data_frames.keys(), key=lambda x: int(float(x[1:]))
    ):  
        if run_number not in run_colors:
            # Utilize a distinct colormap for runs to prevent overlap with destinations
            run_colors[run_number] = get_deterministic_color(run_number, palette_name='tab20')

    return {
        "source_destination_colors": source_destination_colors,
        "source_destination_alphas": source_destination_alphas,
        "source_dest_hatches": source_dest_hatches,
        "run_colors": run_colors,
    }


def plot_timeseries_by_destination(
    plots_dir, data_type, run_data_frames, plot_styles
):
    # Step 2: Generate plot for each run for each source site
    for run_number, run_data in run_data_frames.items():
        for source_site, destinations in run_data.items():
            fig, ax = plt.subplots(figsize=(10, 6))
            for destination_site, dfs in destinations.items():
                color = plot_styles["source_destination_colors"][destination_site]
                linestyle = plot_styles["source_destination_linestyles"][
                    destination_site
                ]
                hatch = plot_styles["source_dest_hatches"][destination_site]

                for _, df in dfs:
                    ax.plot(
                        df["Datetime"],
                        df["Latency"],
                        label=f"{source_site} to {destination_site}",
                        color=color,
                        linestyle=linestyle,
                    )
            ax.xlabel("Datetime")
            ax.ylabel("Latency (ms)")
            ax.legend(
                loc="upper left", bbox_to_anchor=(1.02, 1), borderaxespad=0, ncol=1
            )

            # Save the plot as a PNG file in the plots directory
            single_run_plot_path = plots_dir / f"{source_site}_single_run_{run_number}_{data_type}.png"

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
    # Step 3: Generate separate plots for each destination site across all runs
    for source_site in all_source_sites:
        for destination_site in all_destination_sites:
            if (
                source_site != destination_site
            ):  # Skip plots where source and destination are the same
                fig, ax = plt.subplots(figsize=(10, 6))
                # print(f'run_data_frames: {run_data_frames}')

                if len(run_data_frames) <= 1:
                    print(f"\nONLY ONE RUN, SKIPPING RUN PLOTS")
                    continue

                for run_number in sorted(
                    run_data_frames.keys(), key=lambda x: int(float(x[1:]))
                ):  # Sort run numbers in ascending order
                    run_data = run_data_frames[run_number]
                    if (
                        source_site in run_data
                        and destination_site in run_data[source_site]
                    ):
                        for run_num, df in run_data[source_site][destination_site]:

                            # Normalize the date values by subtracting the first date value
                            df["Timestamp_in_s"] -= df["Timestamp_in_s"].iloc[0]
                            color = plot_styles["run_colors"][run_number]
                            linestyle = plot_styles["run_linestyles"][run_number]

                            ax.plot(
                                df["Timestamp_in_s"],
                                df["Latency"],
                                label=f"Run {run_num}",
                                color=color,
                                linestyle=linestyle,
                            )

                ax.xlabel("Time (normalized in s)")
                ax.ylabel("Latency (ms)")

                ax.legend(
                    loc="upper left", bbox_to_anchor=(1.02, 1), borderaxespad=0, ncol=1
                )

                # Save the plot as a PNG file in the plots directory
                all_runs_plot_path = plots_dir / f"{source_site}_to_{destination_site}_all_runs_{data_type}.png"
                
                fig.savefig(all_runs_plot_path, bbox_inches="tight")
                plt.close(fig)


def plot_histogram_and_cdf(
    plots_dir: Path,
    data_type: str,
    run_data_frames: dict,
    plot_styles: dict[str, dict],
    all_source_sites: set[str],
    all_destination_sites: set[str],
    max_bin_value: int,
) -> None:
    concat_plot_path = plots_dir / "concat_plots"
    concat_plot_path.mkdir(parents=True, exist_ok=True)
    # Step 4: Generate separate plots for each destination site across all runs CONCATINATED
    print("\nMAKING CONCAT PLOT")

    font_size = 14
    axis_font_size = 16

    for source_site in all_source_sites:
        print(f"\tsource_site: {source_site}")

        ## COMPILE COMBINED AND CLIPPED DATA FOR ALL RUNS
        list_of_all_dest: list[pd.Series] = []
        list_of_all_dest_clipped: list[np.ndarray] = []
        list_of_all_dest_names: list[str] = []
        list_of_all_dest_names_labels: list[str] = []
        for destination_site in all_destination_sites:

            print(f"\t\tdestination_site: {destination_site}")
            if (
                source_site == destination_site
            ):  # Skip plots where source and destination are the same
                continue
            fig, ax = plt.subplots(figsize=(16, 12))

            all_runs_concat_data = pd.Series(dtype="float64")
            for run_number in sorted(
                run_data_frames.keys(), key=lambda x: int(float(x[1:]))
            ):  # Sort run numbers in ascending order
                print(f"\t\t run_number: {run_number}")
                run_data = run_data_frames[run_number]

                if (
                    source_site in run_data
                    and destination_site in run_data[source_site]
                ):

                    if len(run_data[source_site][destination_site]) > 1:
                        print(f"Length: {len(run_data[source_site][destination_site])}")
                    run_num, df = run_data[source_site][destination_site][0]
                    if all_runs_concat_data.empty:
                        print(f'\t\t   Initialized: {df["Latency"].size}')
                        all_runs_concat_data = df["Latency"]
                    else:
                        print(f'\t\t   Added: {df["Latency"].size}')
                        all_runs_concat_data = pd.concat(
                            [all_runs_concat_data, df["Latency"]], ignore_index=True
                        )

                else:
                    print(
                        f"\tNo data found for {source_site} to {destination_site} for {run_number}"
                    )

            print(f"\t\t Total {destination_site}: {all_runs_concat_data.size}")

            all_runs_concat_data = all_runs_concat_data[all_runs_concat_data >= 0]

            all_runs_concat_data_droppedna = all_runs_concat_data.dropna()

            list_of_all_dest_names.append(destination_site)
            list_of_all_dest_names_labels.append(f"{source_site} to {destination_site}")

            list_of_all_dest.append(all_runs_concat_data_droppedna)

            # clip data for use in plotting (changes any value over max to the max value)
            all_runs_concat_data_clipped = np.clip(
                all_runs_concat_data_droppedna, 0, max_bin_value + 1
            )

            list_of_all_dest_clipped.append(all_runs_concat_data_clipped)

        max_x = 0
        min_x = 100

        for series in list_of_all_dest:
            # print(f'series: {series}')
            if series.max() > max_x:
                max_x = series.max()
            if series.min() < min_x:
                min_x = series.min()

        print(f"\tmax_x: {max_x}")
        print(f"\tmin_x: {min_x}")

        num_bins = 10
        bin_width = int(max_bin_value / num_bins)

        bins = np.arange(
            math.floor(min_x / bin_width) * bin_width,
            max_bin_value + bin_width * 2,
            bin_width,
        )

        # add another bin of equal width as a placeholder for 0 to smallest bucket
        if bins[0] != 0:
            bins = np.append(bins[0] - bin_width, bins)
        print(f"\tbins: {bins}")

        list_of_all_dest_colors = [
            plot_styles["source_destination_colors"][site]
            for site in list_of_all_dest_names
        ]
        list_of_all_dest_hatches = [
            plot_styles["source_dest_hatches"][site] for site in list_of_all_dest_names
        ]

        n, _, hist_patches = ax.hist(
            list_of_all_dest_clipped,
            bins=bins,
            histtype="bar",
            label=list_of_all_dest_names_labels,
            # color=list_of_all_dest_colors,
            rwidth=0.9,
            # hatch=list_of_all_dest_hatches,
            edgecolor="black",
        )

        print(f"\tbins: {bins}")
        if max_x > max_bin_value:
            print(f"\tLargest value greater than largest bin, capping values")
            bin_labels = [f"{int(b)}" for b in bins[:-2]] + [f">{max_bin_value}"]
        else:
            bin_labels = [f"{int(b)}" for b in bins[:-1]]

        # replace the first bin label with 0 to make the plot look better
        bin_labels[0] = 0

        print(f"\tbin_labels: {bin_labels}")

        ax.set_xticks(bins[:-1])
        ax.set_xticklabels(bin_labels, rotation=90)

        min_samples_in_bin = ax.get_ylim()[-1] / 1500

        print(f"hist_patches: {hist_patches}")

        if len(list_of_all_dest_clipped) == 1:
            hist_patches = [hist_patches]

        for i, patch_group in enumerate(
            hist_patches
        ):  # Iterate over individual bar hist_patches directly
            print(f"patch_group: {patch_group}")
            for patch in patch_group:
                height = patch.get_height()  # Get the height of the bar

                if height > min_samples_in_bin:  # Only label non-empty bars
                    ax.text(
                        patch.get_x()
                        + patch.get_width() / 2
                        + 0.5,  # X position (center of the bar)
                        height + ax.get_ylim()[-1] / 100,  # Y position (top of the bar)
                        f"{list_of_all_dest_names_labels[i % len(list_of_all_dest_names_labels)]} ({int(height)})",  # Get the corresponding destination name
                        ha="center",  # Horizontal alignment
                        va="bottom",  # Vertical alignment
                        rotation=90,  # Rotate the label 90 degrees
                        fontsize=max(8, min(20, 200 / len(bins))),
                    )
                else:
                    patch.set_height(0)

        # if the first bin is larger than bin width (since the multiple starting bins are empty), hatch it
        if int(bin_labels[1]) - int(bin_labels[0]) > bin_width:

            ax_bbox = ax.get_position().get_points()
            ax_width = ax_bbox[1][0] - ax_bbox[0][0]
            ax_height = ax_bbox[1][1] - ax_bbox[0][1]
            bin_width = ax_width / len(bins)
            box_cover_y_buffer = 0.05
            box_cover_x_buffer = 0.001

            fig.patches.extend(
                [
                    plt.Rectangle(
                        (
                            ax_bbox[0][0] + bin_width / 2 + box_cover_x_buffer / 2,
                            ax_bbox[0][1] - ax_height / 40 - box_cover_y_buffer / 2,
                        ),
                        bin_width / 4 - box_cover_x_buffer,
                        ax_height / 40 + box_cover_y_buffer,
                        fill=True,
                        facecolor="white",
                        edgecolor="none",
                        alpha=1,
                        zorder=1000,
                        transform=fig.transFigure,
                        figure=fig,
                    )
                ]
            )
            fig.patches.extend(
                [
                    plt.Rectangle(
                        (ax_bbox[0][0] + bin_width / 2, ax_bbox[0][1] - ax_height / 40),
                        bin_width / 4,
                        ax_height / 40,
                        fill=True,
                        facecolor="black",
                        edgecolor="black",
                        alpha=1,
                        zorder=999,
                        transform=fig.transFigure,
                        figure=fig,
                    )
                ]
            )

        ax.grid(True, axis="both", ls=":", alpha=0.7)
        ax.set_axisbelow(True)
        for dir in ["left", "right", "top"]:
            ax.spines[dir].set_visible(False)

        ax.margins(x=0.02)  # tighter x margins

        ax.set_xlabel("Latency (ms)", fontsize=axis_font_size, fontweight="bold")
        ax.set_ylabel("Number of Samples", fontsize=axis_font_size, fontweight="bold")

        ax.legend(
            loc="upper left",
            bbox_to_anchor=(1.02, 1),
            borderaxespad=0,
            frameon=False,
            ncol=1,
        )

        # Save the plot as a PNG file in the plots directory
        concat_plot_path_full = concat_plot_path / f"{source_site}_all_runs_CONCAT_{max_bin_value}_{data_type}.png"

        fig.savefig(concat_plot_path_full, bbox_inches="tight")
        plt.close(fig)

        ecdf_fig, ecdf_ax = plt.subplots(figsize=(12, 10))

        # Cumulative distributions.
        for i, data in enumerate(list_of_all_dest_clipped):
            if len(data) == 0:
                continue
            # Manual ECDF calculation for compatibility with older matplotlib versions
            sorted_data = np.sort(data)
            yvals = np.arange(1, len(sorted_data) + 1) / len(sorted_data)

            (ecdf_line,) = ecdf_ax.step(
                sorted_data,
                yvals,
                label=f"{list_of_all_dest_names_labels[i]} CDF",
                color=(0, 0, 0),
                linestyle=plot_styles["source_destination_linestyles"][
                    list_of_all_dest_names[i]
                ],
                where="post",
            )
            ecdf_x, ecdf_y = sorted_data, yvals

            ecdf_n, ecdf_bins, ecdf_patches = ecdf_ax.hist(
                data,
                bins=bins,
                density=True,
                histtype="step",
                cumulative=True,
                label=f"{list_of_all_dest_names_labels[i]} Cumulative Histogram",
                color=(0, 0, 0),
                linestyle=plot_styles["source_destination_linestyles"][
                    list_of_all_dest_names[i]
                ],
            )

        ecdf_ax.set_xticks(bins[:-1])
        ecdf_ax.set_xticklabels(bin_labels, rotation=90)
        plt.xlim(right=bins[-1])

        ecdf_ax.grid(True, axis="both", ls=":", alpha=0.7)
        ecdf_ax.set_axisbelow(True)
        for dir in ["left", "right", "top"]:
            ecdf_ax.spines[dir].set_visible(False)

        ecdf_ax.margins(x=0.02)  # tighter x margins

        # if the first bin is larger than bin width (since the multiple starting bins are empty), hatch it
        if int(bin_labels[1]) - int(bin_labels[0]) > bin_width:
            print(f"\tADDING BIN GAP")

            ax_bbox = ecdf_ax.get_position().get_points()
            ax_width = ax_bbox[1][0] - ax_bbox[0][0]
            ax_height = ax_bbox[1][1] - ax_bbox[0][1]
            bin_width = ax_width / len(bins)
            box_cover_y_buffer = 0.05
            box_cover_x_buffer = 0.002

            ecdf_fig.patches.extend(
                [
                    plt.Rectangle(
                        (
                            ax_bbox[0][0] + bin_width + box_cover_x_buffer / 2,
                            ax_bbox[0][1] - ax_height / 80 - box_cover_y_buffer / 2,
                        ),
                        bin_width / 4 - box_cover_x_buffer,
                        ax_height / 40 + box_cover_y_buffer,
                        fill=True,
                        facecolor="white",
                        edgecolor="none",
                        alpha=1,
                        zorder=1000,
                        transform=ecdf_fig.transFigure,
                        figure=ecdf_fig,
                    )
                ]
            )
            ecdf_fig.patches.extend(
                [
                    plt.Rectangle(
                        (ax_bbox[0][0] + bin_width, ax_bbox[0][1] - ax_height / 80),
                        bin_width / 4,
                        ax_height / 40,
                        fill=True,
                        facecolor="black",
                        edgecolor="black",
                        alpha=1,
                        zorder=999,
                        transform=ecdf_fig.transFigure,
                        figure=ecdf_fig,
                    )
                ]
            )

        ecdf_ax.legend(
            loc="upper left",
            bbox_to_anchor=(1.02, 1),
            borderaxespad=0,
            frameon=False,
            ncol=1,
        )
        ecdf_ax.set_xlabel("Latency (ms)", fontsize=axis_font_size, fontweight="bold")
        ecdf_ax.set_ylabel(
            "Probability of Occurrence", fontsize=axis_font_size, fontweight="bold"
        )
        ecdf_ax.label_outer()
        
        concat_cdf_plot_path_full = concat_plot_path / f"{source_site}_all_runs_CONCAT_{max_bin_value}_CDF_{data_type}.png"

        ecdf_fig.savefig(concat_cdf_plot_path_full, bbox_inches="tight")
        plt.close(ecdf_fig)


def main():
    parser = argparse.ArgumentParser(
        description="Generate latency plots for distributed connected autonomous vehicle test runs.",
        epilog=(
            "Examples (use these):\n"
            '  plot_performance_data("results","Energy131-","LandVehicle",True)\n'
            '  plot_performance_data("results","Energy130-","V2XMessage",True)\n'
            '  plot_performance_data("results","Energy130-","TrafficSignalController",True)\n'
            "\nFlags: --histogram generates histogram plots, --cdf generates CDF plots"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "run_prefix",
        nargs="?",
        default="Energy131-",
        help="Prefix used to match run folders inside results_dir.",
    )
    parser.add_argument(
        "message_type",
        nargs="?",
        default="LandVehicle",
        help="Message type to filter CSV files by.",
    )
    parser.add_argument(
        "--histogram",
        action="store_true",
        help="Generate histogram plots of message latency.",
    )
    parser.add_argument(
        "--cdf",
        action="store_true",
        help="Generate cumulative distribution plots of message latency.",
    )
    parser.add_argument(
        "--max-bins",
        nargs="+",
        type=int,
        default=[200, 1000],
        help="List of maximum bin values for generating multiple zoomed levels of plots (default: 200 1000).",
    )
    args = parser.parse_args()

    generate_histogram = args.histogram or not args.cdf
    generate_cdf = args.cdf or not args.histogram

    process_and_plot_results(
        RESULTS_DIR,
        args.run_prefix,
        args.message_type,
        generate_histogram=generate_histogram,
        generate_cdf=generate_cdf,
        max_bins=args.max_bins,
    )

    return


if __name__ == "__main__":
    main()
