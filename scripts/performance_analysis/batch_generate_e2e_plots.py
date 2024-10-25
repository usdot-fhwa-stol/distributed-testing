import sys
import os
import fnmatch
import json
import csv
import re
import argparse
import glob
import matplotlib.pyplot as plt
import pandas as pd
import itertools
import time


def plot_performance_data(root_dir, folder_prefix, data_type):
    # Create the plots directory if it doesn't exist
    plots_dir = os.path.join(root_dir, 'plots',folder_prefix[0:-1])
    os.makedirs(plots_dir, exist_ok=True)

    # Step 1: Traverse the directories and find CSV files
    run_dirs = glob.glob(os.path.join(root_dir,folder_prefix + "*"))
    
    run_data_frames = {}
    all_source_sites = set()
    all_destination_sites = set()
    
    for run_dir in run_dirs:
        # Extract run number from directory name
        run_number = os.path.basename(run_dir).replace(folder_prefix,"")[0:2]
        csv_files = glob.glob(os.path.join(run_dir, '*.csv'))
        data_frames = {}
        for csv_file in csv_files:
            print(f'csv_file: {csv_file}')
            
            # Ignore files that end with results_summary.csv
            if csv_file.endswith('results_summary.csv'):
                print(f'\tSkipping results summary')
                continue
            
            # only want to consider files with the proper data type
            if (data_type.lower() + "_") not in csv_file:
                print(f'\tSkipping file that does not contain {data_type.lower()}')
                continue
            
            # Extract source and destination site names from the file name
            filename_to_split_parts = os.path.basename(csv_file).split('_to_')
            print(f'filename_to_split_parts: {filename_to_split_parts}')

            source_site = filename_to_split_parts[0]

            if "2024" in source_site:
                source_site = source_site.split("_")[0]

            if "-" in source_site:
                source_site = source_site.split("-")[0]

            if "_" in source_site:
                source_site = source_site.split("_")[0]
            
            source_site = source_site.upper()

            print(f'source_site: {source_site}')

            filename_type_split_parts = filename_to_split_parts[1].split("_" + data_type.lower() + "_" )

            print(f'filename_type_split_parts: {filename_type_split_parts}')

            destination_site = filename_type_split_parts[0]

            if "2024" in destination_site:
                destination_site = destination_site.split("_")[0]

            if "-" in destination_site:
                destination_site = destination_site.split("-")[0]

            if "_" in destination_site:
                destination_site = destination_site.split("_")[0]
            
            destination_site = destination_site.upper()

            print(f'destination_site: {destination_site}')
            
            # Read the CSV file into a DataFrame
            df = pd.read_csv(csv_file)
            # Identify the columns of interest
            date_col = [col for col in df if "timestamp" in col][0]
            performance_metric_col = [col for col in df if "_total_latency" in col][-1]
            # Keep only the relevant columns
            df = df[[date_col, performance_metric_col]]
            # Convert the data to datetime, assuming the date is in the recent past, if the number is greater than the current timestamp in s,
            # it is likely in ns 
            if df[date_col][10] > int(time.time()):
                df['Timestamp_in_s'] = df[date_col] / 10**9
                df[date_col] = pd.to_datetime(df[date_col], unit='ns', errors='coerce')
            else:
                df['Timestamp_in_s'] = df[date_col]
                df[date_col] = pd.to_datetime(df[date_col], unit='s', errors='coerce')
            df[performance_metric_col] = pd.to_numeric(df[performance_metric_col], errors='coerce')
            df.columns = ['Datetime', 'Latency','Timestamp_in_s',]  # Rename columns for consistency
            
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

    
    # print(f'all_source_sites: {all_source_sites}')
    # print(f'all_destination_sites: {all_destination_sites}')
    if not run_data_frames:
        print("No data found for the specified source site.")
        return
    
    colors_to_use = [
        'tab:blue', 'tab:orange', 'tab:green', 'tab:red', 'tab:purple', 
        'tab:brown', 'tab:pink', 'tab:gray', 'tab:olive', 'tab:cyan'
    ]

    # Define a color cycle for plotting source-to-destination combinations
    source_dest_color_cycle = iter(colors_to_use)
    source_destination_colors = {}
    
    # Define a color cycle for plotting runs
    run_color_cycle = iter(colors_to_use)
    run_colors = {}

    line_styles = [
            (0, (1, 1)),   # Dotted
            (0, (5, 5)),   # Dashed
            (0, (3, 1, 1, 1)), # Dash-dot
            (0, (5, 1)),   # Dash with small gaps
            (0, (1, 2)),   # Dotted with larger gaps
            (0, (5, 2, 1, 2)), # Long dash, short dash
            (0, (2, 1)),   # Dash with short gaps
            (0, (1, 1, 1, 1, 1, 1)) # Dense dash-dot
        ]
    
     # Define a color cycle for plotting source-to-destination combinations
    source_dest_linestyle_cycle = iter(line_styles)
    source_destination_linestyles = {}
    
    # Define a color cycle for plotting runs
    run_linestyle_cycle = iter(line_styles)
    run_linestyles = {}

    # Step 2: Generate plot for each run for each source site
    for run_number, run_data in run_data_frames.items():
        for source_site, destinations in run_data.items():
            plt.figure(figsize=(10, 6))
            for destination_site, dfs in destinations.items():
                if destination_site not in source_destination_colors:
                    source_destination_colors[destination_site] = next(source_dest_color_cycle)
                color = source_destination_colors[destination_site]

                if destination_site not in source_destination_linestyles:
                    source_destination_linestyles[destination_site] = next(source_dest_linestyle_cycle)
                linestyle = source_destination_linestyles[destination_site]

                for _, df in dfs:
                    plt.plot(df['Datetime'], df['Latency'], label=f'{source_site} to {destination_site}', color=color, linestyle=linestyle)
            plt.xlabel('Datetime')
            # plt.yscale('log') # sets scale to log
            # plt.ylim(10**1, 10**4)  # Set y-axis limits for logarithmic scale
            plt.ylabel('Latency (ms)')
            # plt.title(f'Latency from {source_site} for Run {run_number}')
            plt.legend(loc="upper right")
            # Save the plot as a PNG file in the plots directory
            single_run_plot_path = os.path.join(plots_dir, f'{source_site}_single_run_{run_number}_{data_type}.png')
            plt.savefig(single_run_plot_path)
            plt.close()
    
    # Step 3: Generate separate plots for each destination site across all runs
    for source_site in all_source_sites:
        for destination_site in all_destination_sites:
            if source_site != destination_site:  # Skip plots where source and destination are the same
                plt.figure(figsize=(10, 6))
                # print(f'run_data_frames: {run_data_frames}')
                
                if len(run_data_frames) <= 1:
                    print(f'\nONLY ONE RUN, SKIPPING RUN PLOTS')
                    continue
                
                for run_number in sorted(run_data_frames.keys(), key=lambda x: int(float(x[1:]))):  # Sort run numbers in ascending order
                    run_data = run_data_frames[run_number]
                    if source_site in run_data and destination_site in run_data[source_site]:
                        for run_num, df in run_data[source_site][destination_site]:
                            
                            # Normalize the date values by subtracting the first date value
                            df['Timestamp_in_s'] -= df['Timestamp_in_s'].iloc[0]
                            if run_number not in run_colors:
                                run_colors[run_number] = next(run_color_cycle)
                            color = run_colors[run_number]

                            if run_number not in run_linestyles:
                                run_linestyles[run_number] = next(run_linestyle_cycle)
                            linestyle = run_linestyles[run_number]

                            plt.plot(df['Timestamp_in_s'], df['Latency'], label=f'Run {run_num}', color=color, linestyle=linestyle)
                plt.xlabel('Time (normalized in s)')
                plt.ylabel('Latency (ms)')
                # plt.yscale('log') # sets scale to log
                # plt.ylim(10**1, 10**4)  # Set y-axis limits for logarithmic scale
                # plt.title(f'Latency from {source_site} to {destination_site} for All Runs')
                plt.legend(loc="upper right")
                # Save the plot as a PNG file in the plots directory
                all_runs_plot_path = os.path.join(plots_dir, f'{source_site}_to_{destination_site}_all_runs_{data_type}.png')
                plt.savefig(all_runs_plot_path)
                plt.close()

def main():
    # plot_performance_data("results","P2E2-RFR2-", "BSM")
    # plot_performance_data("results", "SPAT")
    # plot_performance_data("results","P2E0-","BSM")
    plot_performance_data("results","P2E1-","SPAT")
    return

if __name__ == '__main__':
    main()