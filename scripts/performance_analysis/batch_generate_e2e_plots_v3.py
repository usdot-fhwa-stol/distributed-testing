import sys
import os
import fnmatch
import json
import csv
import re
import argparse
import glob
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patches as patches
import pandas as pd
import itertools
import time
import numpy as np
import math



def load_and_correct_pair(file_a, file_b, window_s):
    """Load two direction CSVs for the same site pair + run, and return both
    with a 'corrected_latency_ms' column (offset removed, per-window)."""
    df_a_raw = pd.read_csv(file_a)
    df_b_raw = pd.read_csv(file_b)

    ts_cols_a = [c for c in df_a_raw.columns if "timestamp" in c]
    lat_cols_a = [c for c in df_a_raw.columns if "_total_latency" in c]
    ts_cols_b = [c for c in df_b_raw.columns if "timestamp" in c]
    lat_cols_b = [c for c in df_b_raw.columns if "_total_latency" in c]

    if not ts_cols_a or not lat_cols_a or not ts_cols_b or not lat_cols_b:
        print(f"\tSkipping pair (missing timestamp/_total_latency column): {file_a} / {file_b}")
        return None, None

    df_a = pd.DataFrame({
        "timestamp_s": pd.to_numeric(df_a_raw[ts_cols_a[0]], errors="coerce"),
        "latency_ms": pd.to_numeric(df_a_raw[lat_cols_a[-1]], errors="coerce"),
    }).dropna()
    df_b = pd.DataFrame({
        "timestamp_s": pd.to_numeric(df_b_raw[ts_cols_b[0]], errors="coerce"),
        "latency_ms": pd.to_numeric(df_b_raw[lat_cols_b[-1]], errors="coerce"),
    }).dropna()

    if df_a.empty or df_b.empty:
        print(f"\tSkipping pair (no valid numeric rows): {file_a} / {file_b}")
        return None, None

    t_zero = min(df_a["timestamp_s"].min(), df_b["timestamp_s"].min())
    df_a["elapsed_s"] = df_a["timestamp_s"] - t_zero
    df_b["elapsed_s"] = df_b["timestamp_s"] - t_zero
    df_a["window"] = (df_a["elapsed_s"] // window_s) * window_s
    df_b["window"] = (df_b["elapsed_s"] // window_s) * window_s

    wa = df_a.groupby("window")["latency_ms"].mean().rename("mean_a")
    wb = df_b.groupby("window")["latency_ms"].mean().rename("mean_b")
    win = pd.concat([wa, wb], axis=1).dropna()

    if win.empty:
        print(f"\tSkipping pair (no overlapping time windows between directions): {file_a} / {file_b}")
        return None, None

    win["offset"] = (win["mean_b"] - win["mean_a"]) / 2

    df_a["offset"] = df_a["window"].map(win["offset"])
    df_b["offset"] = df_b["window"].map(win["offset"])

    df_a = df_a.dropna(subset=["offset"])
    df_b = df_b.dropna(subset=["offset"])

    # A->B measured = L - O  =>  L = measured + O
    # B->A measured = L + O  =>  L = measured - O
    df_a["corrected_latency_ms"] = df_a["latency_ms"] + df_a["offset"]
    df_b["corrected_latency_ms"] = df_b["latency_ms"] - df_b["offset"]

    return df_a, df_b


def find_direction_pairs(csv_files, data_type):
    """Group a run folder's CSV files into (A->B, B->A) pairs for the given
    data type, using the same source/destination filename parsing the rest
    of this script already uses. Returns dict {(source,dest): filepath} plus
    a list of (file_a, file_b, source, dest) pairs found."""
    data_type_lower = data_type.lower()
    parsed = {}

    for csv_file in csv_files:
        basename = os.path.basename(csv_file)
        if basename.endswith("results_summary.csv"):
            continue
        if (data_type_lower + "_") not in csv_file and not csv_file.lower().endswith(data_type_lower + ".csv"):
            continue

        filename_to_split_parts = basename.split("_to_")
        if len(filename_to_split_parts) < 2:
            continue

        source_site = filename_to_split_parts[0]
        if "2024" in source_site:
            source_site = source_site.split("_")[0]
        if "-" in source_site:
            source_site = source_site.split("-")[0]
        if "_" in source_site:
            source_site = source_site.split("_")[0]
        source_site = source_site.upper()

        filename_type_split_parts = filename_to_split_parts[1].split("_" + data_type_lower + "_")
        destination_site = filename_type_split_parts[0]
        if "2024" in destination_site:
            destination_site = destination_site.split("_")[0]
        if "-" in destination_site:
            destination_site = destination_site.split("-")[0]
        if "_" in destination_site:
            destination_site = destination_site.split("_")[0]
        destination_site = destination_site.upper()

        parsed[(source_site, destination_site)] = csv_file

    pairs = []
    seen = set()
    for (src, dst), fpath in parsed.items():
        if (src, dst) in seen or (dst, src) in seen:
            continue
        if (dst, src) in parsed:
            pairs.append((fpath, parsed[(dst, src)], src, dst))
            seen.add((src, dst))
            seen.add((dst, src))
        else:
            print(f"\tNo reverse-direction file found for {src}->{dst} ({fpath}), skipping (need both directions to correct offset)")

    return pairs


def plot_performance_data(root_dir, folder_prefix, data_type, annotate, window_s=5.0):
    # Create the plots directory if it doesn't exist
    plots_dir = os.path.join(root_dir, 'plots', folder_prefix.rstrip('-_') + "_corrected")
    os.makedirs(plots_dir, exist_ok=True)

    run_data_frames, all_source_sites, all_destination_sites = import_csv_results(root_dir, folder_prefix, data_type, window_s)

    plot_styles = generate_styles(run_data_frames)

    generate_all_dest_all_runs_hist_plot(plots_dir,data_type,run_data_frames,plot_styles,all_source_sites,all_destination_sites,200,annotate)
    generate_all_dest_all_runs_hist_plot(plots_dir,data_type,run_data_frames,plot_styles,all_source_sites,all_destination_sites,1000,annotate)

def import_csv_results(root_dir, folder_prefix, data_type, window_s):

    run_dirs = glob.glob(os.path.join(root_dir,folder_prefix + "*"))

    run_data_frames = {}
    all_source_sites = set()
    all_destination_sites = set()

    for run_dir in run_dirs:
        run_number_digits = re.search(r'(\d+)', os.path.basename(run_dir).replace(folder_prefix, "", 1))
        run_number = "R" + run_number_digits.group(1) if run_number_digits else os.path.basename(run_dir)
        csv_files = glob.glob(os.path.join(run_dir, '*.csv'))
        data_frames = {}

        pairs = find_direction_pairs(csv_files, data_type)

        for file_a, file_b, source_site, destination_site in pairs:
            print(f'Correcting pair: {source_site}->{destination_site} / {destination_site}->{source_site}')

            df_a, df_b = load_and_correct_pair(file_a, file_b, window_s)
            if df_a is None:
                continue

            for site_pair_source, site_pair_dest, df in [
                (source_site, destination_site, df_a),
                (destination_site, source_site, df_b),
            ]:
                out_df = pd.DataFrame()
                out_df['Timestamp_in_s'] = df['timestamp_s']
                out_df['Datetime'] = pd.to_datetime(df['timestamp_s'], unit='s', errors='coerce')
                out_df['Latency'] = df['corrected_latency_ms']

                if site_pair_source not in data_frames:
                    data_frames[site_pair_source] = {}
                if site_pair_dest not in data_frames[site_pair_source]:
                    data_frames[site_pair_source][site_pair_dest] = []
                data_frames[site_pair_source][site_pair_dest].append((run_number, out_df))
                all_source_sites.add(site_pair_source)
                all_destination_sites.add(site_pair_dest)

        if data_frames:
            run_data_frames[run_number] = data_frames

    print(f'\n\n-----------IMPORT SUMMARY (offset-corrected)-----------')
    for run_number in run_data_frames:
        print(f'RUN: {run_number}')
        for source_site in run_data_frames[run_number]:
            print(f'\tsource_site: {source_site}')
            for dest_site in run_data_frames[run_number][source_site]:
                print(f'\t\tdest_site: {dest_site}')

    if not run_data_frames:
        print("No data found for the specified source site.")
        return {}, set(), set()

    return run_data_frames, all_source_sites, all_destination_sites

def generate_styles(run_data_frames):
    color_to_use = "blue"
    base_color = mcolors.to_rgba(color_to_use)
    number_of_shades = 9
    colors_to_use = [(base_color[0], base_color[1], base_color[2], i / (number_of_shades - 1)) for i in range(number_of_shades)]

    hatch_types = ["/","+",".","O","X",'\\','-','*',"|"]

    source_dest_color_cycle = iter(colors_to_use)
    source_destination_colors = {}

    source_dest_hatch_cycle = iter(hatch_types)
    source_dest_hatches = {}

    line_styles = [
            "solid",
            (0, (1, 1)),
            (0, (5, 5)),
            (0, (3, 1, 1, 1)),
            (0, (5, 1)),
            (0, (5, 2, 1, 2)),
            (0, (2, 1)),
            (0, (1, 1, 1, 1, 1, 1))
        ]

    source_dest_linestyle_cycle = iter(line_styles)
    source_destination_linestyles = {}

    for run_number, run_data in run_data_frames.items():
        for source_site, destinations in run_data.items():
            for destination_site, dfs in destinations.items():
                if destination_site not in source_destination_colors:
                    source_destination_colors[destination_site] = next(source_dest_color_cycle)

                if destination_site not in source_destination_linestyles:
                    source_destination_linestyles[destination_site] = next(source_dest_linestyle_cycle)

                if destination_site not in source_dest_hatches:
                    source_dest_hatches[destination_site] = next(source_dest_hatch_cycle)

    run_linestyle_cycle = iter(line_styles)
    run_linestyles = {}

    run_color_cycle = iter(colors_to_use)
    run_colors = {}

    for run_number in sorted(run_data_frames.keys(), key=lambda x: int(float(x[1:]))):
        if run_number not in run_colors:
            run_colors[run_number] = next(run_color_cycle)

        if run_number not in run_linestyles:
            run_linestyles[run_number] = next(run_linestyle_cycle)

    return {
        "source_destination_colors" : source_destination_colors,
        "source_destination_linestyles" : source_destination_linestyles,
        "source_dest_hatches" : source_dest_hatches,
        "run_colors" : run_colors,
        "run_linestyles" : run_linestyles,
    }

def generate_all_dest_all_runs_hist_plot(plots_dir,data_type,run_data_frames,plot_styles,all_source_sites,all_destination_sites,max_bin_value,annotate):
    concat_plot_path = os.path.join(plots_dir,"concat_plots")
    os.makedirs(concat_plot_path, exist_ok=True)
    print("\nMAKING CONCAT PLOT (offset-corrected)")

    font_size = 14
    axis_font_size = 16

    for source_site in all_source_sites:
        print(f'\tsource_site: {source_site}')

        list_of_all_dest = []
        list_of_all_dest_clipped = []
        list_of_all_dest_names = []
        list_of_all_dest_names_labels = []
        for destination_site in all_destination_sites:

            print(f'\t\tdestination_site: {destination_site}')
            if source_site == destination_site:
                continue
            fig, ax = plt.subplots(figsize=(16, 12))
            plt.rcParams.update({'font.size': font_size})
            plt.rc('axes', labelsize=axis_font_size, labelweight='bold')

            all_runs_concat_data = pd.Series(dtype='float64')
            for run_number in sorted(run_data_frames.keys(), key=lambda x: int(float(x[1:]))):
                print(f'\t\t run_number: {run_number}')
                run_data = run_data_frames[run_number]

                if source_site in run_data and destination_site in run_data[source_site]:
                    if len(run_data[source_site][destination_site]) > 1:
                        print(f'Length: {len(run_data[source_site][destination_site])}')
                    run_num,df = run_data[source_site][destination_site][0]
                    if all_runs_concat_data.empty:
                        print(f'\t\t   Initialized: {df["Latency"].size}')
                        all_runs_concat_data = df["Latency"]
                    else:
                        print(f'\t\t   Added: {df["Latency"].size}')
                        all_runs_concat_data = pd.concat([all_runs_concat_data,df["Latency"]], ignore_index=True)
                else:
                    print(f'\tNo data found for {source_site} to {destination_site} for {run_number}')

            print(f'\t\t Total {destination_site}: {all_runs_concat_data.size}')

            # NOTE: corrected latency can legitimately still be negative for
            # individual messages (real jitter around a small true value) --
            # unlike the raw script, we do NOT clip out negative values here,
            # since that was specifically compensating for the raw offset bug
            # this correction already fixes.
            all_runs_concat_data_droppedna = all_runs_concat_data.dropna()

            if all_runs_concat_data_droppedna.empty:
                print(f'\t\tNo corrected data remaining for {source_site} to {destination_site} -- skipping this pair')
                continue

            list_of_all_dest_names.append(destination_site)
            list_of_all_dest_names_labels.append(f'{source_site} to {destination_site} (corrected)')

            list_of_all_dest.append(all_runs_concat_data_droppedna)

            all_runs_concat_data_clipped = np.clip(all_runs_concat_data_droppedna,-1,max_bin_value + 1)

            list_of_all_dest_clipped.append(all_runs_concat_data_clipped)

        if not list_of_all_dest_clipped:
            plt.close()
            continue

        max_x = 0
        min_x = 100

        for series in list_of_all_dest:
            if series.max() > max_x:
                max_x = series.max()
            if series.min() < min_x:
                min_x = series.min()

        print(f'\tmax_x: {max_x}')
        print(f'\tmin_x: {min_x}')

        num_bins = 10
        bin_width = int(max_bin_value/num_bins)

        bins = np.arange(math.floor(min_x/bin_width)*bin_width, max_bin_value + bin_width*2, bin_width)

        if bins[0] > 0:
            bins = np.append(bins[0] - bin_width,bins)
        print(f'\tbins: {bins}')

        n, _, hist_patches = ax.hist(
            list_of_all_dest_clipped,
            bins=bins,
            histtype='bar',
            label=list_of_all_dest_names_labels,
            rwidth=0.9,
            edgecolor='black',
            )

        # See compute_clock_offset_v3/v4 and batch_generate_e2e_plots_v2 notes:
        # BarContainer subclasses tuple, so isinstance(x, tuple) can't tell single
        # vs multi-dataset apart -- use the known dataset count instead.
        if len(list_of_all_dest_clipped) == 1:
            hist_patches = [hist_patches]

        print(f'\tbins: {bins}')
        if max_x > max_bin_value:
            print(f'\tLargest value greater than largest bin, capping values')
            bin_labels = [f'{int(b)}' for b in bins[:-2]] + [f'>{max_bin_value}']
        else:
            bin_labels = [f'{int(b)}' for b in bins[:-1]]

        bin_labels[0] = str(int(bins[0]))

        print(f'\tbin_labels: {bin_labels}')

        ax.set_xticks(bins[:-1])
        ax.set_xticklabels(bin_labels, rotation=90)

        min_samples_in_bin = ax.get_ylim()[-1]/1500

        for i, patch_group in enumerate(hist_patches):
            for patch in patch_group:
                height = patch.get_height()

                if height > min_samples_in_bin:
                    ax.text(
                        patch.get_x() + patch.get_width() / 2 + 0.5,
                        height + ax.get_ylim()[-1]/100,
                        f'{list_of_all_dest_names_labels[i % len(list_of_all_dest_names_labels)]} ({int(height)})',
                        ha='center',
                        va='bottom',
                        rotation=90,
                        fontsize=9,
                    )
                else:
                    patch.set_height(0)

        if len(bin_labels) > 1 and int(bin_labels[1]) - int(bin_labels[0]) > bin_width:
            ax_bbox = ax.get_position().get_points()
            ax_width = ax_bbox[1][0] - ax_bbox[0][0]
            ax_height = ax_bbox[1][1] - ax_bbox[0][1]
            bin_width_fig = ax_width/len(bins)
            box_cover_y_buffer = 0.05
            box_cover_x_buffer = 0.001
            fig.patches.extend([
                                    plt.Rectangle(
                                        (ax_bbox[0][0] + bin_width_fig/2 + box_cover_x_buffer/2,ax_bbox[0][1] - ax_height/40 - box_cover_y_buffer/2),
                                        bin_width_fig/4 - box_cover_x_buffer,ax_height/40 + box_cover_y_buffer,
                                        fill=True,
                                        facecolor='white',
                                        edgecolor='none',
                                        alpha=1,
                                        zorder=1000,
                                        transform=fig.transFigure,
                                        figure=fig
                                    )
                                ])
            fig.patches.extend([
                                    plt.Rectangle(
                                        (ax_bbox[0][0] + bin_width_fig/2,ax_bbox[0][1] - ax_height/40),
                                        bin_width_fig/4,ax_height/40,
                                        fill=True,
                                        facecolor='black',
                                        edgecolor='black',
                                        alpha=1,
                                        zorder=999,
                                        transform=fig.transFigure,
                                        figure=fig
                                    )
                                ])

        ax.grid(True, axis='both', ls=':', alpha=0.7)
        ax.set_axisbelow(True)
        for dir in ['left', 'right', 'top']:
            ax.spines[dir].set_visible(False)
        ax.margins(x=0.02)

        plt.subplots_adjust( top=0.8, bottom=0.1)

        plt.xlabel('Corrected Latency (ms)')
        plt.ylabel('Number of Samples')

        plt.legend(loc="best")
        concat_plot_path_full = os.path.join(concat_plot_path, f'{source_site}_all_runs_CONCAT_CORRECTED_{max_bin_value}_{data_type}.png')
        plt.savefig(concat_plot_path_full)
        plt.close()

        ## MAKE CUMULATIVE HISTOGRAM
        ecdf_fig, ecdf_ax = plt.subplots(figsize=(12, 10))
        plt.rcParams.update({'font.size': font_size})
        plt.rc('axes', labelsize=axis_font_size, labelweight='bold')

        for i,data in enumerate(list_of_all_dest_clipped):
            sorted_data = np.sort(np.asarray(data))
            ecdf_x = sorted_data
            ecdf_y = np.arange(1, len(sorted_data) + 1) / len(sorted_data)
            ecdf_ax.step(
                        ecdf_x, ecdf_y,
                        where='post',
                        label=f'{list_of_all_dest_names_labels[i]} CDF',
                        color=(0,0,0),
                        linestyle=plot_styles["source_destination_linestyles"][list_of_all_dest_names[i]],
                    )

            ecdf_n, ecdf_bins, ecdf_patches = ecdf_ax.hist( data,
                                        bins=bins,
                                        density=True,
                                        histtype="step",
                                        cumulative=True,
                                        label=f'{list_of_all_dest_names_labels[i]} Cumulative Histogram',
                                        color=(0,0,0),
                                        linestyle=plot_styles["source_destination_linestyles"][list_of_all_dest_names[i]],
                                    )
            if annotate:
                for x, y in zip(ecdf_bins[:-1], ecdf_n):
                    ecdf_ax.annotate(
                        f"{y:.2f}",
                        xy=(x, y),
                        xytext=(x + 2, y + 0.01),
                        fontsize=8,
                        color="black",
                    )

                target_values = [0.005, 0.2, 0.4, 0.5, 0.6, 0.8, 0.995]
                for target in target_values:
                    crossing_idx_arr = np.where(ecdf_y >= target)[0]
                    if len(crossing_idx_arr) == 0:
                        continue
                    crossing_idx = crossing_idx_arr[0]
                    crossing_x = ecdf_x[crossing_idx]
                    crossing_y = ecdf_y[crossing_idx]

                    offset_x = 10
                    offset_y = - 0.02 - 0.02*i

                    ecdf_ax.annotate(
                        f"{crossing_x:.1f} ms",
                        xy=(crossing_x, crossing_y),
                        xytext=(crossing_x + offset_x, crossing_y + offset_y),
                        arrowprops=dict(arrowstyle="->", color="red"),
                        fontsize=8,
                        color="red",
                    )

        ecdf_ax.set_xticks(bins[:-1])
        ecdf_ax.set_xticklabels(bin_labels, rotation=90)
        plt.xlim(right=bins[-1])

        ecdf_ax.grid(True, axis='both', ls=':', alpha=0.7)
        ecdf_ax.set_axisbelow(True)
        for dir in ['left', 'right', 'top']:
            ecdf_ax.spines[dir].set_visible(False)
        ecdf_ax.margins(x=0.02)

        if len(bin_labels) > 1 and int(bin_labels[1]) - int(bin_labels[0]) > bin_width:
            ax_bbox = ecdf_ax.get_position().get_points()
            ax_width = ax_bbox[1][0] - ax_bbox[0][0]
            ax_height = ax_bbox[1][1] - ax_bbox[0][1]
            bin_width_fig = ax_width/len(bins)
            box_cover_y_buffer = 0.05
            box_cover_x_buffer = 0.002
            ecdf_fig.patches.extend([
                                    plt.Rectangle(
                                        (ax_bbox[0][0] + bin_width_fig + box_cover_x_buffer/2,ax_bbox[0][1] - ax_height/80 - box_cover_y_buffer/2),
                                        bin_width_fig/4 - box_cover_x_buffer,ax_height/40 + box_cover_y_buffer,
                                        fill=True,
                                        facecolor='white',
                                        edgecolor='none',
                                        alpha=1,
                                        zorder=1000,
                                        transform=ecdf_fig.transFigure,
                                        figure=ecdf_fig
                                    )
                                ])
            ecdf_fig.patches.extend([
                                    plt.Rectangle(
                                        (ax_bbox[0][0] + bin_width_fig,ax_bbox[0][1] - ax_height/80),
                                        bin_width_fig/4,ax_height/40,
                                        fill=True,
                                        facecolor='black',
                                        edgecolor='black',
                                        alpha=1,
                                        zorder=999,
                                        transform=ecdf_fig.transFigure,
                                        figure=ecdf_fig
                                    )
                                ])

        ecdf_ax.legend(loc="lower right")
        ecdf_ax.set_xlabel("Corrected Latency (ms)")
        ecdf_ax.set_ylabel("Probability of Occurrence")
        ecdf_ax.label_outer()
        concat_cdf_plot_path_full = os.path.join(concat_plot_path, f'{source_site}_all_runs_CONCAT_CORRECTED_{max_bin_value}_CDF_{data_type}.png')
        plt.savefig(concat_cdf_plot_path_full)
        plt.close()

def main():
    # root_dir="results" (parent folder), folder_prefix="Run" matches your
    # Run1_results, Run2_results, Run3_results, ... folders automatically.
    # window_s controls how finely the dynamic offset is estimated (same
    # meaning as compute_clock_offset_v4.py's --window).
    plot_performance_data("results", "Run", "Vehicle", True, window_s=5.0)
    plot_performance_data("results", "Run", "J2735-BSM", True, window_s=5.0)
    return

if __name__ == '__main__':
    main()