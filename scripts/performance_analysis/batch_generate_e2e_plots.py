import os
import glob
import argparse
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patches as patches
import pandas as pd
import time
import numpy as np
import math
from typing import Optional, Sequence


def generate_latency_plots(
    root_dir: str,
    folder_prefix: str,
    data_type: str,
    generate_histogram: bool = True,
    generate_cdf: bool = True,
    annotate_cdf: bool = False,
    max_bins: Optional[Sequence[int]] = None,
) -> None:

    # Create the plots directory if it doesn't exist
    plots_dir = os.path.join(root_dir, "plots", folder_prefix[0:-1])
    os.makedirs(plots_dir, exist_ok=True)

    run_data_frames, all_source_sites, all_destination_sites = import_csv_results(
        root_dir, folder_prefix, data_type
    )

    plot_styles = generate_styles(run_data_frames)

    # generate_single_run_all_dest_plot(plots_dir,data_type,run_data_frames,plot_styles)

    # generate_single_destination_all_runs_plot(plots_dir,data_type,run_data_frames,plot_styles,all_source_sites,all_destination_sites)

    if generate_histogram or generate_cdf:
        for max_bin in max_bins:
            generate_all_dest_all_runs_hist_plot(
                plots_dir,
                data_type,
                run_data_frames,
                plot_styles,
                all_source_sites,
                all_destination_sites,
                max_bin,
                annotate_cdf,
                generate_histogram=generate_histogram,
                generate_cdf=generate_cdf,
            )


def import_csv_results(root_dir, folder_prefix, data_type):

    # Step 1: Traverse the directories and find CSV files
    run_dirs = glob.glob(os.path.join(root_dir, folder_prefix + "*"))

    run_data_frames = {}
    all_source_sites = set()
    all_destination_sites = set()

    for run_dir in run_dirs:
        # Extract run number from directory name
        run_number = os.path.basename(run_dir).replace(folder_prefix, "")[0:2]
        csv_files = glob.glob(os.path.join(run_dir, "*.csv"))
        data_frames = {}
        for csv_file in csv_files:
            print(f"csv_file: {csv_file}")

            # Ignore files that end with results_summary.csv
            if csv_file.endswith("results_summary.csv"):
                continue
            # only want to consider files with the proper data type
            if (data_type.lower() + "_") not in csv_file:
                continue

            # Extract source and destination site names from the file name
            filename_to_split_parts = os.path.basename(csv_file).split("_to_")
            # print(f'filename_to_split_parts: {filename_to_split_parts}')

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

            # print(f'filename_type_split_parts: {filename_type_split_parts}')

            destination_site = filename_type_split_parts[0]
            
            if "2024" in destination_site or "_" in destination_site:
                destination_site = destination_site.split("_")[0]
            elif "-" in destination_site:
                destination_site = destination_site.split("-")[0]

            destination_site = destination_site.upper()
            print(f"destination_site: {destination_site}")

            df = pd.read_csv(csv_file)
            # Get and keep time and latency related columns
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
            # Rename columns for consistency
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

    # print(f'all_source_sites: {all_source_sites}')
    # print(f'all_destination_sites: {all_destination_sites}')
    if not run_data_frames:
        print("No data found for the specified source site.")
        return

    return run_data_frames, all_source_sites, all_destination_sites


def generate_styles(run_data_frames):
    # normal colors
    # colors_to_use = [
    #     'tab:blue', 'tab:orange', 'tab:green', 'tab:red', 'tab:purple',
    #     'tab:brown', 'tab:pink', 'tab:gray', 'tab:olive', 'tab:cyan'
    # ]

    # shades of a color
    color_to_use = "blue"
    base_color = mcolors.to_rgba(color_to_use)  # Convert to RGBA
    number_of_shades = 9
    colors_to_use = [
        (base_color[0], base_color[1], base_color[2], i / (number_of_shades - 1))
        for i in range(number_of_shades)
    ]
    print(f"colors_to_use: {colors_to_use}")

    # greyscale
    # colors_to_use = [
    #     (1,1,1),
    #     (0.8,0.8,0.8),
    #     (0.6,0.6,0.6),
    #     (0.4,0.4,0.4),
    #     (0.2,0.2,0.2),
    # ]

    # all white
    # colors_to_use = [
    #     (1,1,1),
    #     (1,1,1),
    #     (1,1,1),
    #     (1,1,1),
    #     (1,1,1),
    #     (1,1,1),
    #     (1,1,1),
    # ]

    hatch_types = ["/", "+", ".", "O", "X", "\\", "-", "*", "|"]

    # Define a color cycle for plotting source-to-destination combinations
    source_dest_color_cycle = iter(colors_to_use)
    source_destination_colors = {}

    # Define a color cycle for plotting source-to-destination combinations
    source_dest_hatch_cycle = iter(hatch_types)
    source_dest_hatches = {}

    line_styles = [
        "solid",
        (0, (1, 1)),  # Dotted
        (0, (5, 5)),  # Dashed
        (0, (3, 1, 1, 1)),  # Dash-dot
        (0, (5, 1)),  # Dash with small gaps
        # (0, (1, 2)),   # Dotted with larger gaps
        (0, (5, 2, 1, 2)),  # Long dash, short dash
        (0, (2, 1)),  # Dash with short gaps
        (0, (1, 1, 1, 1, 1, 1)),  # Dense dash-dot
    ]

    # Define a color cycle for plotting source-to-destination combinations
    source_dest_linestyle_cycle = iter(line_styles)
    source_destination_linestyles = {}

    # assign color, linestyle, and hatch to each destination
    for run_number, run_data in run_data_frames.items():
        for source_site, destinations in run_data.items():
            for destination_site, dfs in destinations.items():
                if destination_site not in source_destination_colors:
                    source_destination_colors[destination_site] = next(
                        source_dest_color_cycle
                    )

                if destination_site not in source_destination_linestyles:
                    source_destination_linestyles[destination_site] = next(
                        source_dest_linestyle_cycle
                    )

                if destination_site not in source_dest_hatches:
                    source_dest_hatches[destination_site] = next(
                        source_dest_hatch_cycle
                    )

    # Define a color cycle for plotting runs
    run_linestyle_cycle = iter(line_styles)
    run_linestyles = {}

    # Define a color cycle for plotting runs
    run_color_cycle = iter(colors_to_use)
    run_colors = {}

    # assign color and linestyle for each run
    for run_number in sorted(
        run_data_frames.keys(), key=lambda x: int(float(x[1:]))
    ):  # Sort run numbers in ascending order
        if run_number not in run_colors:
            run_colors[run_number] = next(run_color_cycle)

        if run_number not in run_linestyles:
            run_linestyles[run_number] = next(run_linestyle_cycle)

    return {
        "source_destination_colors": source_destination_colors,
        "source_destination_linestyles": source_destination_linestyles,
        "source_dest_hatches": source_dest_hatches,
        "run_colors": run_colors,
        "run_linestyles": run_linestyles,
    }


def generate_single_run_all_dest_plot(
    plots_dir, data_type, run_data_frames, plot_styles
):
    # Step 2: Generate plot for each run for each source site
    for run_number, run_data in run_data_frames.items():
        for source_site, destinations in run_data.items():
            plt.figure(figsize=(10, 6))
            for destination_site, dfs in destinations.items():
                color = plot_styles["source_destination_colors"][destination_site]
                linestyle = plot_styles["source_destination_linestyles"][
                    destination_site
                ]
                hatch = plot_styles["source_dest_hatches"][destination_site]

                for _, df in dfs:
                    plt.plot(
                        df["Datetime"],
                        df["Latency"],
                        label=f"{source_site} to {destination_site}",
                        color=color,
                        linestyle=linestyle,
                    )
            plt.xlabel("Datetime")
            # plt.yscale('log') # sets scale to log
            # plt.ylim(10**1, 10**4)  # Set y-axis limits for logarithmic scale
            plt.ylabel("Latency (ms)")
            # plt.title(f'Latency from {source_site} for Run {run_number}')
            plt.legend(loc="upper right")
            # Save the plot as a PNG file in the plots directory
            single_run_plot_path = os.path.join(
                plots_dir, f"{source_site}_single_run_{run_number}_{data_type}.png"
            )
            plt.savefig(single_run_plot_path)
            plt.close()


def generate_single_destination_all_runs_plot(
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
                plt.figure(figsize=(10, 6))
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

                            plt.plot(
                                df["Timestamp_in_s"],
                                df["Latency"],
                                label=f"Run {run_num}",
                                color=color,
                                linestyle=linestyle,
                            )
                plt.xlabel("Time (normalized in s)")
                plt.ylabel("Latency (ms)")
                # plt.yscale('log') # sets scale to log
                # plt.ylim(10**1, 10**4)  # Set y-axis limits for logarithmic scale
                # plt.title(f'Latency from {source_site} to {destination_site} for All Runs')
                plt.legend(loc="upper right")
                # Save the plot as a PNG file in the plots directory
                all_runs_plot_path = os.path.join(
                    plots_dir,
                    f"{source_site}_to_{destination_site}_all_runs_{data_type}.png",
                )
                plt.savefig(all_runs_plot_path)
                plt.close()


def generate_all_dest_all_runs_hist_plot(
    plots_dir,
    data_type,
    run_data_frames,
    plot_styles,
    all_source_sites,
    all_destination_sites,
    max_bin_value,
    annotate,
    generate_histogram=True,
    generate_cdf=True,
):
    concat_plot_path = os.path.join(plots_dir, "concat_plots")
    os.makedirs(concat_plot_path, exist_ok=True)
    # Step 4: Generate separate plots for each destination site across all runs CONCATINATED
    print("\nMAKING CONCAT PLOT")

    font_size = 14
    axis_font_size = 16

    for source_site in all_source_sites:
        print(f"\tsource_site: {source_site}")

        ## COMPILE COMBINED AND CLIPPED DATA FOR ALL RUNS
        list_of_all_dest = []
        list_of_all_dest_clipped = []
        list_of_all_dest_names = []
        list_of_all_dest_names_labels = []
        for destination_site in all_destination_sites:

            # if destination_site == "FHWA":
            #     continue
            print(f"\t\tdestination_site: {destination_site}")
            if (
                source_site == destination_site
            ):  # Skip plots where source and destination are the same
                continue
            fig, ax = plt.subplots(figsize=(16, 12))
            plt.rcParams.update({"font.size": font_size})
            plt.rc("axes", labelsize=axis_font_size, labelweight="bold")
            # print(f'run_data_frames: {run_data_frames}')

            # if len(run_data_frames) <= 1:
            #     print(f'\t\tONLY ONE RUN, SKIPPING RUN PLOTS')
            #     continue

            all_runs_concat_data = pd.Series()
            for run_number in sorted(
                run_data_frames.keys(), key=lambda x: int(float(x[1:]))
            ):  # Sort run numbers in ascending order
                print(f"\t\t run_number: {run_number}")
                run_data = run_data_frames[run_number]

                # print(f'run_data: {run_data}')
                # print(f'run_data[source_site]: {run_data[source_site]}')
                if (
                    source_site in run_data
                    and destination_site in run_data[source_site]
                ):

                    # for run_num, df in run_data[source_site][destination_site]:
                    # print(f'\t\trun_num: {run_num}')
                    # print(f't\t\df:\n{df}')
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

                    # print(f'\t\t  Total {run_number}: {all_runs_concat_data.size}')
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
            # print(f'max: {all_runs_concat_data.max()}')
            all_runs_concat_data_clipped = np.clip(
                all_runs_concat_data_droppedna, 0, max_bin_value + 1
            )
            # print(f'max: {all_runs_concat_data_clipped.max()}')

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

        # bin_width = 15
        # num_bins = math.ceil(max_bin_value/bin_width)
        # max_bin_value = num_bins*bin_width

        # bin_width = max(20, np.round(max_x / 25 / 20) * 20) # round to multiple of 20, use max(20, ...) to avoid rounding to zero
        # bins = np.arange(0, max_x + bin_width, bin_width)

        # bins = np.append(np.arange(0, max_bin_value, max_bin_value/num_bins), np.inf)
        bins = np.arange(
            math.floor(min_x / bin_width) * bin_width,
            max_bin_value + bin_width * 2,
            bin_width,
        )

        # bins.append(np.inf)
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

        # bins = [bin for bin in bins if bin >= min_x]
        # if bins[0] != 0:
        #     bins = np.append(0,bins)

        if generate_histogram:
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
        else:
            hist_patches = []

        # total = len(list_of_all_dest[0])
        # ax.set_xticks(bins)
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
                        fontsize=patch.get_width() * 4,
                    )

                    # greyscale_value = 1/len(list_of_all_dest_names_labels)*(i % len(list_of_all_dest_names_labels))

                    # patch.set_color((greyscale_value,greyscale_value,greyscale_value))
                    # patch.set_hatch(list_of_all_dest_hatches[i % len(list_of_all_dest_names_labels)])
                else:
                    patch.set_height(0)

        # if the first bin is larger than bin width (since the multiple starting bins are empty), hatch it
        if int(bin_labels[1]) - int(bin_labels[0]) > bin_width:
            #     print(f'\tADDING FIRST BIN HATCHING')
            #     plt.axvspan(bins[0], bins[1], hatch='-', edgecolor='black', facecolor='none', alpha=0.3)
            ax_bbox = ax.get_position().get_points()
            ax_width = ax_bbox[1][0] - ax_bbox[0][0]
            ax_height = ax_bbox[1][1] - ax_bbox[0][1]
            bin_width = ax_width / len(bins)
            box_cover_y_buffer = 0.05
            box_cover_x_buffer = 0.001
            # box = fig.add_patch(patches.Rectangle((bin_width - bin_width/8, -1*box_height/2), width=bin_width/4, height=box_height, color="grey",zorder=1000))
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
            # ax.plot([ax_bbox[0][0], ax_bbox[0][0] + bin_width/4], [ax_bbox[0][1] + ax_height/30, ax_bbox[0][1] + ax_height/30], color='black', linewidth=2, zorder=1000, transform=fig.transFigure)

            # rect.set_linewidths([2, 0, 2, 0])  # Left, bottom, right, top

        ax.grid(True, axis="both", ls=":", alpha=0.7)
        ax.set_axisbelow(True)
        for dir in ["left", "right", "top"]:
            ax.spines[dir].set_visible(False)
        # ax.tick_params(axis="y", length=0)  # Switch off y ticks
        ax.margins(x=0.02)  # tighter x margins

        plt.subplots_adjust(top=0.8, bottom=0.1)

        plt.xlabel("Latency (ms)")
        plt.ylabel("Number of Samples")
        # plt.yscale('log') # sets scale to log
        # plt.ylim(10**1, 10**4)  # Set y-axis limits for logarithmic scale
        # plt.title(f'Latency from {source_site} to {destination_site} for All Runs')

        if generate_histogram:
            plt.legend(loc="best")
            # Save the plot as a PNG file in the plots directory
            concat_plot_path_full = os.path.join(
                concat_plot_path,
                f"{source_site}_all_runs_CONCAT_{max_bin_value}_{data_type}.png",
            )
            plt.savefig(concat_plot_path_full)
        plt.close()

        ## MAKE CUMULATIVE HISTOGRAM
        if not generate_cdf:
            continue

        ecdf_fig, ecdf_ax = plt.subplots(figsize=(12, 10))
        plt.rcParams.update({"font.size": font_size})
        plt.rc("axes", labelsize=axis_font_size, labelweight="bold")

        # add labels for descriptions
        annotation_offset_x = 0.5
        annotation_offset_y = 2

        # Cumulative distributions.
        for i, data in enumerate(list_of_all_dest_clipped):
            ecdf_line = ecdf_ax.ecdf(
                data,
                label=f"{list_of_all_dest_names_labels[i]} CDF",
                # color=list_of_all_dest_colors[i],
                color=(0, 0, 0),
                linestyle=plot_styles["source_destination_linestyles"][
                    list_of_all_dest_names[i]
                ],
            )
            # Extract the x and y data from the Line2D object
            ecdf_x, ecdf_y = ecdf_line.get_data()

            ecdf_n, ecdf_bins, ecdf_patches = ecdf_ax.hist(
                data,
                bins=bins,
                density=True,
                histtype="step",
                cumulative=True,
                label=f"{list_of_all_dest_names_labels[i]} Cumulative Histogram",
                # color=list_of_all_dest_colors[i],
                color=(0, 0, 0),
                linestyle=plot_styles["source_destination_linestyles"][
                    list_of_all_dest_names[i]
                ],
            )
            if annotate:
                # if "FHWA" in list_of_all_dest_names_labels[i]:
                # Example: Annotating the ECDF and cumulative histogram
                for x, y in zip(ecdf_bins[:-1], ecdf_n):
                    # Annotate each step of the cumulative histogram
                    ecdf_ax.annotate(
                        f"{y:.2f}",  # Value to display
                        xy=(x, y),  # Coordinate for the annotation
                        xytext=(x + 2, y + 0.01),  # Slightly offset for clarity
                        fontsize=8,  # Font size
                        color="black",  # Text color
                    )

                # cdf = np.cumsum(ecdf_n) / np.sum(ecdf_n)

        ecdf_ax.set_xticks(bins[:-1])
        ecdf_ax.set_xticklabels(bin_labels, rotation=90)
        plt.xlim(right=bins[-1])

        ecdf_ax.grid(True, axis="both", ls=":", alpha=0.7)
        ecdf_ax.set_axisbelow(True)
        for dir in ["left", "right", "top"]:
            ecdf_ax.spines[dir].set_visible(False)
        # ax.tick_params(axis="y", length=0)  # Switch off y ticks
        ecdf_ax.margins(x=0.02)  # tighter x margins

        # if the first bin is larger than bin width (since the multiple starting bins are empty), hatch it
        if int(bin_labels[1]) - int(bin_labels[0]) > bin_width:
            print(f"\tADDING BIN GAP")
            #     plt.axvspan(bins[0], bins[1], hatch='-', edgecolor='black', facecolor='none', alpha=0.3)
            ax_bbox = ecdf_ax.get_position().get_points()
            ax_width = ax_bbox[1][0] - ax_bbox[0][0]
            ax_height = ax_bbox[1][1] - ax_bbox[0][1]
            bin_width = ax_width / len(bins)
            box_cover_y_buffer = 0.05
            box_cover_x_buffer = 0.002
            # box = fig.add_patch(patches.Rectangle((bin_width - bin_width/8, -1*box_height/2), width=bin_width/4, height=box_height, color="grey",zorder=1000))
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
            # ax.plot([ax_bbox[0][0], ax_bbox[0][0] + bin_width/4], [ax_bbox[0][1] + ax_height/30, ax_bbox[0][1] + ax_height/30], color='black', linewidth=2, zorder=1000, transform=fig.transFigure)

            # rect.set_linewidths([2, 0, 2, 0])  # Left, bottom, right, top

        ecdf_ax.legend(loc="lower right")
        ecdf_ax.set_xlabel("Latency (ms)")
        ecdf_ax.set_ylabel("Probability of Occurrence")
        ecdf_ax.label_outer()
        concat_cdf_plot_path_full = os.path.join(
            concat_plot_path,
            f"{source_site}_all_runs_CONCAT_{max_bin_value}_CDF_{data_type}.png",
        )
        plt.savefig(concat_cdf_plot_path_full)
        plt.close()


def main():
    parser = argparse.ArgumentParser(
        description="Generate latency plots for distributed connected autonomous vehicle test runs.",
        epilog=(
            "Positional arguments: results_dir is the root directory containing run folders, "
            "run_prefix is the folder name prefix used to find matching runs, and message_type "
            "selects which CSV latency files to process (for example, BSM). Optional flags "
            "control which plots are generated.\n\n"
            "Common option combinations from the previous plotting script:\n"
            '  plot_performance_data("results/P2E2-RFR2-DOWNLOAD", "P2E2-RFR2-", "BSM", True)\n'
            '    -> results_dir="results/P2E2-RFR2-DOWNLOAD", run_prefix="P2E2-RFR2-", message_type="BSM", generate_histogram=True, generate_cdf=True\n'
            '  plot_performance_data("results", "SPAT")\n'
            '    -> results_dir="results", run_prefix="SPAT", message_type defaults to "BSM" unless overridden\n'
            '  plot_performance_data("results", "P2E0-", "Vehicle")\n'
            '    -> results_dir="results", run_prefix="P2E0-", message_type="Vehicle"\n'
            '  plot_performance_data("results", "P2E0-", "J2735-BSM")\n'
            '    -> results_dir="results", run_prefix="P2E0-", message_type="J2735-BSM"\n'
            '  plot_performance_data("results", "P2E1-", "SPAT")\n'
            '    -> results_dir="results", run_prefix="P2E1-", message_type="SPAT"\n'
            "\nFlags: --histogram generates histogram plots, --cdf generates CDF plots, and --annotate-cdf adds percentage labels to the CDF."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "results_dir",
        nargs="?",
        default="results/P2E2-RFR2-DOWNLOAD",
        help="Root directory containing the run result folders.",
    )
    parser.add_argument(
        "run_prefix",
        nargs="?",
        default="P2E2-RFR2-",
        help="Prefix used to match run folders inside results_dir.",
    )
    parser.add_argument(
        "message_type",
        nargs="?",
        default="BSM",
        help="Message type to filter CSV files by, such as BSM or CAM.",
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
        "--annotate-cdf",
        action="store_true",
        help="Annotate the CDF plot with percentage labels.",
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

    generate_latency_plots(
        args.results_dir,
        args.run_prefix,
        args.message_type,
        generate_histogram=generate_histogram,
        generate_cdf=generate_cdf,
        annotate_cdf=args.annotate_cdf,
        max_bins=args.max_bins,
    )

    return


if __name__ == "__main__":
    main()
