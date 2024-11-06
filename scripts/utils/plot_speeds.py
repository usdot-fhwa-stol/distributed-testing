import os
import argparse
import pandas as pd
import matplotlib.pyplot as plt
import shutil
import re
import numpy as np



def filter_speed_data(df, run_name, speed_column='calculated_speed', threshold=2, window=5):
    """
    Filters the speed data by trimming the data before the vehicle starts moving (speed exceeds threshold)
    and removing data after the vehicle stops (speed falls below threshold).
    
    Parameters:
    - df: DataFrame containing the speed data.
    - run_name: Name of the run to retrieve start/end times.
    - speed_column: The name of the column containing speed data.
    - threshold: Speed threshold to determine when the vehicle starts/stops moving.
    - window: Rolling window size for smoothing to handle spikes.
    
    Returns:
    - Filtered and trimmed DataFrame.
    """
    print(f'\tFiltering {run_name}')

    # # Get start and end times from the hardcoded dictionary
    # start_time = run_time_data.get(run_name, {}).get('start')
    # end_time = run_time_data.get(run_name, {}).get('end')


    # if start_time is not None and end_time is not None:
    #     if start_time > df['current_time'].iloc[-1]:
    #         print("START TIME AFTER LAST TIMESTAMP")

    #     if end_time > df['current_time'].iloc[0]:
    #         print("START TIME AFTER LAST TIMESTAMP")

    #     # Filter rows based on start and end times
    #     df = df[(df['current_time'] >= start_time) & (df['current_time'] <= end_time)]

    # Smooth the data using a rolling mean to handle early spikes
    # df[speed_column] = df[speed_column].rolling(window=window, min_periods=1).mean()

    df[speed_column] = df[speed_column].ewm(alpha=0.1).mean()

    # Find the first index where speed exceeds the threshold (trim beginning)
    first_above_threshold_idx = df[df[speed_column] > threshold].index.min()
    
    if first_above_threshold_idx is not None:
        df = df.loc[first_above_threshold_idx:]  # Keep rows after this index

    # Find the last index where speed exceeds the threshold (trim end)
    last_above_threshold_idx = df[df[speed_column] > threshold].index.max()
    
    if last_above_threshold_idx is not None:
        df = df.loc[:last_above_threshold_idx]  # Keep rows before this index

    # Reset index after trimming
    df = df.reset_index(drop=True)
    
    return df

# Define 10 unique line styles
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


import os
import re
import pandas as pd
import matplotlib.pyplot as plt

def load_and_plot_speeds(csv_files, plots_dir):
    """
    Loads CSV files and generates three plots for each vehicle: 
    1. Combined plot with both Group and Solo runs.
    2. Plot with only Solo runs.
    3. Plot with only Group runs.
    
    Parameters:
    - csv_files: Dictionary with vehicle names as keys and paths to their Group and Solo files.
    - plots_dir: Directory where the plots should be saved.
    """
    # print(f'csv_files: {csv_files}')
    
    for vehicle, files in csv_files.items():
        print(f'\tPlotting: {vehicle}')
        
        # 1. Combined plot
        plt.figure(figsize=(12, 8))  # Increase figure size for better visibility

        # Plot Group runs
        for idx, file in enumerate(files['Group']):
            df = pd.read_csv(file)
            match = re.search(r'Group-R(\d+)', file)
            run_number = match.group(1) if match else "Unknown"
            run_name = f"Group {run_number}"
            df = filter_speed_data(df, run_name)  # Filter and trim speed data
            label = run_name
            plt.plot(df.index * 0.1,
                     df['calculated_speed'], 
                     label=label, 
                     linestyle=line_styles[idx % len(line_styles)])  # Different line styles for Group runs

        # Plot Solo runs
        for idx, file in enumerate(files['Solo']):
            df = pd.read_csv(file)
            match = re.search(r'SR(\d+)', os.path.basename(file))
            run_number = match.group(1) if match else "Unknown"
            run_name = f'{vehicle} SR{run_number}'
            df = filter_speed_data(df, run_name)  # Filter and trim speed data
            label = run_name
            plt.plot(df.index * 0.1,
                df['calculated_speed'], 
                     label=label, 
                     linestyle=line_styles[(idx + len(files['Group'])) % len(line_styles)])  # Different line styles for Solo runs

        plt.xlabel('Time (s)')
        plt.ylabel('Speed (km/h)')
        plt.legend()
        plt.grid(True)
        plot_path = os.path.join(plots_dir, f'{vehicle}_combined_speeds.png')
        plt.savefig(plot_path)
        plt.close()
        print(f"Combined plot saved for {vehicle} at: {plot_path}")

        # 2. Solo runs only
        plt.figure(figsize=(12, 8))
        for idx, file in enumerate(files['Solo']):
            df = pd.read_csv(file)
            match = re.search(r'SR(\d+)', os.path.basename(file))
            run_number = match.group(1) if match else "Unknown"
            run_name = f'{vehicle} SR{run_number}'
            df = filter_speed_data(df, run_name)
            plt.plot(df.index * 0.1,
                     df['calculated_speed'], 
                     label=run_name, 
                     linestyle=line_styles[idx % len(line_styles)])  # Different line styles for Solo runs

        plt.xlabel('Time (s)')
        plt.ylabel('Speed (km/h)')
        plt.legend()
        plt.grid(True)
        plot_path = os.path.join(plots_dir, f'{vehicle}_solo_speeds.png')
        plt.savefig(plot_path)
        plt.close()
        print(f"Solo runs plot saved for {vehicle} at: {plot_path}")

        # 3. Group runs only
        plt.figure(figsize=(12, 8))
        for idx, file in enumerate(files['Group']):
            df = pd.read_csv(file)
            match = re.search(r'Group-R(\d+)', file)
            run_number = match.group(1) if match else "Unknown"
            run_name = f"Group {run_number}"
            df = filter_speed_data(df, run_name)
            plt.plot(df.index * 0.1,
                df['calculated_speed'], 
                     label=run_name, 
                     linestyle=line_styles[idx % len(line_styles)])  # Different line styles for Group runs

        plt.xlabel('Time (s)')
        plt.ylabel('Speed (km/h)')
        plt.legend()
        plt.grid(True)
        plot_path = os.path.join(plots_dir, f'{vehicle}_group_speeds.png')
        plt.savefig(plot_path)
        plt.close()
        print(f"Group runs plot saved for {vehicle} at: {plot_path}")


def to_numeric(series):
    return pd.to_numeric(series, errors='coerce')  # Convert to numeric, setting invalid parsing to NaN

def load_and_plot_speed_averages(csv_files, plots_dir):
    """
    Loads CSV files and generates plots for each vehicle, with Group and Solo runs labeled.
    
    Parameters:
    - csv_files: Dictionary with vehicle names as keys and paths to their Group and Solo files.
    - plots_dir: Directory where the plots should be saved.
    """
    print(f'csv_files: {csv_files}')
    for vehicle, files in csv_files.items():
        print(f'\tPlotting: {vehicle}')
        plt.figure(figsize=(12, 8))  # Increase figure size for better visibility

        group_series_list = []
        solo_series_list = []

        # Plot Group runs
        for idx, file in enumerate(files['Group']):
            df = pd.read_csv(file)
            # Regular expression to find the run number
            match = re.search(r'Group-R(\d+)', file)

            # Extract and print the run number
            if match:
                run_number = match.group(1)
                print(f"\t\tRun number: {run_number}")
            else:
                print("Run number not found")
            run_name = f"Group {run_number}"
            df = filter_speed_data(df, run_name)  # Filter and trim speed data

            # Ensure numeric conversion for all columns
            df = df.apply(to_numeric)

            # Handle missing values (NaNs)
            df = df.fillna(0) 

            group_series_list.append(df['calculated_speed'])

            # Combine Series into a DataFrame

        # print(f'group_series_list:\n\n {group_series_list }\n\n')

        # Combine Series into a DataFrame
        group_series_combined = pd.concat(group_series_list, axis=1)

        # print(f'group_series_combined:\n\n {group_series_combined }\n\n')

        # Calculate the mean across the columns (axis=1)
        average_group_series = group_series_combined.mean(axis=1)

        # print(f'average_group_series:\n\n {average_group_series }\n\n')



        # label = run_name
        plt.plot(average_group_series.index * 0.1,
                    average_group_series,
                    label="Group Run", 
                    linestyle="--")  # Use different line styles for Group runs
        
        # Plot Solo runs
        for idx, file in enumerate(files['Solo']):
            df = pd.read_csv(file)
            # Extract the basename from the path
            basename = os.path.basename(file)

            # Regular expression to find the run number in the basename
            match = re.search(r'SR(\d+)', basename)

            # Extract and print the run number
            if match:
                run_number = match.group(1)
                print(f"\t\tRun number: {run_number}")
            else:
                print("Run number not found")

            run_name = f'{vehicle} SR{run_number}'
            df = filter_speed_data(df, run_name)  # Filter and trim speed data

            # Ensure numeric conversion for all columns
            df = df.apply(to_numeric)

            # Handle missing values (NaNs)
            df = df.fillna(0) 

            # Append Series to list
            solo_series_list.append(df['calculated_speed'])


        # print(f'solo_series_list:\n\n {solo_series_list }\n\n')

        # Combine Series into a DataFrame
        solo_series_combined = pd.concat(solo_series_list, axis=1)

        # print(f'solo_series_combined:\n\n {solo_series_combined }\n\n')

        # Calculate the mean across the columns (axis=1)
        average_solo_series = solo_series_combined.mean(axis=1)

        # print(f'average_solo_series:\n\n {average_solo_series }\n\n')



        plt.plot(average_solo_series.index * 0.1,
                 average_solo_series,
                    label="Solo Runs", 
                    linestyle="-")  # Use different line styles for Solo runs

        # Customize plot
        # plt.title(f'{vehicle} - Solo vs Group Runs (Filtered)')
        plt.xlabel('Time (s)')
        plt.ylabel('Speed (km/h)')
        plt.legend()
        plt.grid(True)

        # Save the plot to the plots directory
        plot_path = os.path.join(plots_dir, f'{vehicle}_solo_vs_group_speeds_averages.png')
        plt.savefig(plot_path)
        plt.close()

        print(f"Plot saved for {vehicle} at: {plot_path}")

def find_csv_files(base_dir):
    """
    Finds and organizes CSV files dynamically based on the directory structure.
    
    Parameters:
    - base_dir: The base directory where the Group and Solo folders are located.
    
    Returns:
    - Dictionary where each key is a vehicle/site name (e.g., 'UCLA') and values are dictionaries with 'Group' and 'Solo' run CSV file paths.
    """
    csv_files = {
        'ANL': {'Group': [], 'Solo': []},
        'FHWA': {'Group': [], 'Solo': []},
        'Mcity': {'Group': [], 'Solo': []},
        'ORNL': {'Group': [], 'Solo': []},
        'UCLA': {'Group': [], 'Solo': []}
    }
    
    # Look for Group runs
    group_dir = os.path.join(base_dir, 'Group')
    for group_run in os.listdir(group_dir):
        group_run_dir = os.path.join(group_dir, group_run)
        if os.path.isdir(group_run_dir):
            for file in os.listdir(group_run_dir):
                if file.endswith('.csv'):
                    if 'ANL' in file:
                        csv_files['ANL']['Group'].append(os.path.join(group_run_dir, file))
                    elif 'FHWA' in file:
                        csv_files['FHWA']['Group'].append(os.path.join(group_run_dir, file))
                    elif 'MCITY' in file:
                        csv_files['Mcity']['Group'].append(os.path.join(group_run_dir, file))
                    elif 'ORNL' in file:
                        csv_files['ORNL']['Group'].append(os.path.join(group_run_dir, file))
                    elif 'UCLA' in file:
                        csv_files['UCLA']['Group'].append(os.path.join(group_run_dir, file))

    # Look for Solo runs
    for vehicle in ['ANL', 'FHWA', 'Mcity', 'ORNL', 'UCLA']:
        solo_dir = os.path.join(base_dir, f'Solo-{vehicle}')
        for file in os.listdir(solo_dir):
            if file.endswith('.csv'):
                csv_files[vehicle]['Solo'].append(os.path.join(solo_dir, file))

    return csv_files

# Hardcoded dictionary of start and end times
run_time_data = {
    "Group 1": {"start": 1712338114.05220, "end": 1712338337.25267},
    "Group 2": {"start": 1712339463.91321, "end": 1712339740.18305},
    "Group 3": {"start": 1712340451.58703, "end": 1712340743.44211},
    "Group 4": {"start": 1712341317.33595, "end": 1712341556.68898},
    "Group 5": {"start": 1712342039.68582, "end": 1712342298.91937},
    "ORNL SR1": {"start": 1711032907.04399, "end": 1711033115.34726},
    "ORNL SR2": {"start": 1711033900.89659, "end": 1711043087.20575},
    "ORNL SR3": {"start": 1711035002.96016, "end": 1711035204.05394},
    "ANL SR1": {"start": 1712343852.22775, "end": 1712343967.85983},
    "ANL SR2": {"start": 1712344589.57794, "end": 1712345389.56596},
    "ANL SR3": {"start": 1712345679.11066, "end": 1712345806.58100},
    "UCLA SR1": {"start": 1711040064.17786, "end": 1711040835.13687},
    "UCLA SR2": {"start": 1711041077.91513, "end": 1711041256.71349},
    "UCLA SR3": {"start": 1711041547.50551, "end": 1711041725.24368},
    "Mcity SR1": {"start": 1712347156.11500, "end": 1712347356.06328},
    "Mcity SR2": {"start": 1712347520.82607, "end": 1712347683.02699},
    "Mcity SR3": {"start": 1712347940.46268, "end": 1712348101.66324},
    "carma SR1": {"start": None, "end": None},
    "carma SR2": {"start": None, "end": None},
    "carma SR3": {"start": None, "end": None}
}

def main():
    parser = argparse.ArgumentParser(description='Plot Solo vs Group Speeds for Multiple Vehicles.')
    parser.add_argument('-d', '--directory', type=str, required=True, help='Base directory containing the Group and Solo folders.')
    args = parser.parse_args()

    base_dir = args.directory
    plots_dir = os.path.join(base_dir, 'plots')

    # If plots directory exists, remove it and recreate
    if os.path.exists(plots_dir):
        shutil.rmtree(plots_dir)
    os.makedirs(plots_dir)

    # Find CSV files
    csv_files = find_csv_files(base_dir)

    # Load and plot speeds
    load_and_plot_speeds(csv_files, plots_dir)
    load_and_plot_speed_averages(csv_files, plots_dir)

if __name__ == "__main__":
    main()
