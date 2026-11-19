import sys
import os
import csv
import argparse
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import matplotlib.lines as mlines
import shutil


## This script is used to convert nethogs text output to csv format
## It takes an input of a text file of nethogs output
## The csv produced will contain a column for each application that appears in the text file
## A row will be added for every time step
##
## Example collection command:
##
##     sudo nethogs -d 1 -t > run_7_aug_all.txt
##
## Example script usage:
##
##     python3 calculate_throughput_averages.py -i run_7_mitre_all.txt -o run_7_mitre_all_output.csv
##

def convert_nethogs_to_csv(infile,outfile):

    # infile_obj = open(infile,'r')

    # Read all lines from the file
    with open(infile, 'r') as file:
        lines = file.readlines()

    results_outfile_obj = open(outfile,'w',newline='')
    results_outfile_writer = csv.writer(results_outfile_obj)

    results_dataset = {}
    
    refresh_index = 0

    # Find the index of the last empty line
    last_empty_line_index = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "":
            last_empty_line_index = i
            break

    # If an empty line is found, return everything before it (including the empty line)
    if last_empty_line_index is not None:
        lines = lines[:last_empty_line_index + 1]

        # Write the modified lines back to the file
        with open(infile, 'w') as file:
            file.writelines(lines)
    


    for line_i,line in enumerate(lines):
        current_line = line.strip()
        
        if "Adding local address" in current_line or "Ethernet link detected" in current_line:
            continue
        if current_line == "Refreshing:":
            refresh_index += 1
            continue
        elif current_line == "":
            continue
        else:
            # print(str(line_i) + " - " + str(refresh_index) + " - " + current_line)

            current_line_list = current_line.split("	")
            
            current_line_app = current_line_list[0]
            current_line_up = current_line_list[1]
            current_line_down = current_line_list[2]
            
            # print("\tApp: " + current_line_app)
            # print("\tUP: " + current_line_up)
            # print("\tDOWN: " + current_line_down)

            if not current_line_app in results_dataset:
                results_dataset[current_line_app] = {
                    str(refresh_index) : {
                        "up" : current_line_up,
                        "down" : current_line_down 
                    }
                    
                }
            else:
                results_dataset[current_line_app][str(refresh_index)] = {}
                results_dataset[current_line_app][str(refresh_index)]["up"] = current_line_up
                results_dataset[current_line_app][str(refresh_index)]["down"] = current_line_down

    # print(str(results_dataset))

    header_row = []

    for app in results_dataset:
        header_row.append(app + "_UP")
        header_row.append(app + "_DOWN")

    results_outfile_writer.writerow(header_row)

    for this_refresh_index in range(1,refresh_index):
        # print("\nWriting refresh: " + str(this_refresh_index))

        row_to_write = []

        for app in results_dataset:
            # print("  Checking app for data: " + app)
            if str(this_refresh_index) in results_dataset[app]:
                # print("    UP: " + results_dataset[app][str(this_refresh_index)]["up"])
                # print("    DOWN: " + results_dataset[app][str(this_refresh_index)]["down"])

                row_to_write.append(results_dataset[app][str(this_refresh_index)]["up"])
                row_to_write.append(results_dataset[app][str(this_refresh_index)]["down"])

            else:
                # print("    UP: NO DATA" )
                # print("    DOWN: NO DATA")

                row_to_write.append("NO DATA")
                row_to_write.append("NO DATA")
        
        results_outfile_writer.writerow(row_to_write)

def find_files_by_type(root_dir,filetype_suffix):
    txt_files = []
    
    # Walk through the directory and subdirectories
    for dirpath, dirnames, filenames in os.walk(root_dir):
        for filename in filenames:
            # Check if the file ends with .txt
            if filename.endswith(filetype_suffix):
                # Get the full path of the file
                file_path = os.path.join(dirpath, filename)
                txt_files.append(file_path)
    
    # Print all found .txt files
    if txt_files:
        # print("Found the following .txt files:")
        # for file_path in txt_files:
        #     print(file_path)
        return txt_files
    else:
        print(f"No .txt files found in the directory and subdirectories of: {root_dir}")



def analyze_csv_files(csv_files, output_csv_name):
    # Initialize an empty list to hold the results
    results = []

    all_data = []
    single_site_singe_run_by_type_data = {}
    '''
    { 
        "R1" : 
            { 
                "ANL" : [type_data1, type_data2, ...]
            }, 
            { 
                "ORNL" : [type_data1, type_data2, ...]
            }, 
            ...
        "R2" : 
            { 
                "ANL" : [type_data1, type_data2, ...]
            }, 
            { 
                "ORNL" : [type_data1, type_data2, ...]
            }, 
            ...
        ...
    }
    '''
    single_site_all_runs_by_type_data = {}
    all_sites_by_run_by_type = {}

    min_time = None
    max_down = 50

    plots_folder = output_csv_name + "_plots"

    if os.path.exists(plots_folder):
        # Remove the existing folder and its contents
        shutil.rmtree(plots_folder)
        print(f"Folder '{plots_folder}' deleted.")

    # Create the folder
    os.makedirs(plots_folder)
    print(f"Folder '{plots_folder}' created.")

    # Iterate over each CSV file in the list
    for csv_file in csv_files:
        # Extract information from the CSV file name
        filename = os.path.basename(csv_file)
        event, run_number, site_name, data_type, in_or_out = filename.rstrip('.csv').split('_')

        # Read the CSV file into a pandas DataFrame
        df = pd.read_csv(csv_file)

        # Find columns that match the criteria
        down_col = [col for col in df.columns if "tenaCollector-VUG-Combined" in col and col.endswith("_DOWN")]
        # up_col = [col for col in df.columns if "tenaCollector-VUG-Combined" in col and col.endswith("_UP")]

        if down_col:
            down_col = down_col[0]  # Assuming there's only one match
            # up_col = up_col[0]  # Assuming there's only one match

            # Convert columns to numeric, coercing errors to NaN for non-numeric values
            df[down_col] = pd.to_numeric(df[down_col], errors='coerce')
            # df[up_col] = pd.to_numeric(df[up_col], errors='coerce')
            
            # data rate below this number we consider to be "zero"
            zero_rate_threshold = 0.1

            # Identify the first and last index where the value is greater than or equal to the threshold
            first_valid_down_idx = df[df[down_col] >= zero_rate_threshold].first_valid_index()
            last_valid_down_idx = df[df[down_col] >= zero_rate_threshold].last_valid_index()
            # Keep only the rows between the first and last valid indices
            df = df.loc[first_valid_down_idx:last_valid_down_idx].reset_index(drop=True)

            # Calculate the metrics
            metrics = {
                'event': event,
                'run_number': run_number,
                'site_name': site_name,
                'data_type': data_type,
                'in_or_out': in_or_out,
                'down_avg': df[down_col].mean(),
                'down_min': df[down_col].min(),
                'down_max': df[down_col].max(),
                'down_std': df[down_col].std(),
                # 'up_avg': df[up_col].mean(),
                # 'up_min': df[up_col].min(),
                # 'up_max': df[up_col].max(),
                # 'up_std': df[up_col].std()
            }

            # data to be used in combined plots
            individual_data = {
                'event': event,
                'run_number': run_number,
                'site_name': site_name,
                'data_type': data_type,
                'in_or_out': in_or_out,
                'filename' : filename.rstrip('.csv'),
                'down_col_data' : df[down_col],
            }

            num_rows = df[down_col].index[-1]

            print(f"Num Rows: {num_rows}")
            if min_time == None or min_time > num_rows:
                print(f"min_time = {min_time}")
                if num_rows < 30:
                    print(f'Data file {filename} only has {num_rows} rows!!! ')
                    continue
                else:
                    min_time = num_rows
            
            if max_down < df[down_col].max():
                max_down = max_down + 25
                print(f"max_down = {max_down}")

            # Append the data
            all_data.append(individual_data)

            # create collection of data to generate plots of all data types of a single site for a single run
            if run_number not in single_site_singe_run_by_type_data:
                print(f'\tadding {run_number} to single_site_singe_run_by_type_data')
                single_site_singe_run_by_type_data[run_number] = {}

            if site_name not in single_site_singe_run_by_type_data[run_number]:
                print(f'\t\tadding {site_name} to single_site_singe_run_by_type_data[{run_number}]')
                single_site_singe_run_by_type_data[run_number][site_name] = []

            single_site_singe_run_by_type_data[run_number][site_name].append(individual_data)
            print(f'\t\t\tAdding data to single_site_singe_run_by_type_data[{run_number}][{site_name}]: {individual_data["data_type"]} {individual_data["in_or_out"]} ')


            # create collection of data to generate plots of a single site for a single data type for all runs
            if site_name not in single_site_all_runs_by_type_data:
                single_site_all_runs_by_type_data[site_name] = {}

            if data_type not in single_site_all_runs_by_type_data[site_name]:
                single_site_all_runs_by_type_data[site_name][data_type] = []

            single_site_all_runs_by_type_data[site_name][data_type].append(individual_data)

            # create collection of data to generate plots of a single site for a single data type for all runs
            if run_number not in all_sites_by_run_by_type:
                all_sites_by_run_by_type[run_number] = {}

            if data_type not in all_sites_by_run_by_type[run_number]:
                all_sites_by_run_by_type[run_number][data_type] = []

            all_sites_by_run_by_type[run_number][data_type].append(individual_data)
            
            

            # Append the metrics to the results list
            results.append(metrics)

    for dataset in all_data:

        plot_individual_data_rate(dataset['down_col_data'], plots_folder, dataset['filename'],min_time,max_down)

    print("\nPlotting single_site_singe_run_by_type_data")
    for run_key in single_site_singe_run_by_type_data:
        for site_key in single_site_singe_run_by_type_data[run_key]:
            plot_combined_data_rates(f'{run_key}_{site_key}', single_site_singe_run_by_type_data[run_key][site_key],'data_type', plots_folder,x_limit=min_time,y_limit=max_down,skip_all=True,stack_plot=True)
    
    print("\nPlotting single_site_all_runs_by_type_data")
    for site_key in single_site_all_runs_by_type_data:
        for data_key in single_site_all_runs_by_type_data[site_key]:
            plot_combined_data_rates(f'{site_key}_{data_key}', single_site_all_runs_by_type_data[site_key][data_key],'run_number', plots_folder,x_limit=min_time,y_limit=max_down)

    print("\nPlotting all_sites_by_run_by_type")
    for run_key in all_sites_by_run_by_type:
        for data_key in all_sites_by_run_by_type[run_key]:
            plot_combined_data_rates(f'{run_key}_{data_key}', all_sites_by_run_by_type[run_key][data_key],'site_name', plots_folder,x_limit=min_time,y_limit=max_down)

    # Convert the results to a DataFrame
    results_df = pd.DataFrame(results)

    # Write the results to a new CSV file
    results_df.to_csv(f"{output_csv_name}.csv", index=False)

def plot_combined_data_rates(title_key, datasets, legend_key, plots_folder,x_limit,y_limit,skip_all=False,stack_plot=False):
    # Filter datasets by 'in_or_out' condition
    
    split_datasets = {}
    
    if skip_all:

        split_datasets["IN"] = [data for data in datasets if data['in_or_out'] == 'IN' and data['data_type'] != "ALL"]
        split_datasets["OUT"] = [data for data in datasets if data['in_or_out'] == 'OUT' and data['data_type'] != "ALL"]
    else:
        split_datasets["IN"] = [data for data in datasets if data['in_or_out'] == 'IN']
        split_datasets["OUT"] = [data for data in datasets if data['in_or_out'] == 'OUT']

    
    
    print(f'Creating plots for {title_key}')
    
    for data_direction in ["IN","OUT"]:

        plt.figure(figsize=(12, 8))

        if len(split_datasets[data_direction]) <= 1:
            print(f"\tOnly 1 dataset for {title_key}, skipping")
            return

        if stack_plot:
            hatch_types = ["//","++","..","OO","--","XX"]
            small_hatch_types = ["//","++","..","OO","--","XX"]

            datasets_data = [smooth_data(data['down_col_data'][0:x_limit]) for data in split_datasets[data_direction]]

            datasets_labels = [data[legend_key] for data in split_datasets[data_direction]]
            stacks = plt.stackplot(split_datasets[data_direction][0]['down_col_data'].index[0:x_limit],*datasets_data,labels=datasets_labels)

            for stack, hatch in zip(stacks, hatch_types):
                stack.set_hatch(hatch)
                stack.set_facecolor('none')

            # Create custom legend handles (with hatches)
            handles = [Patch(facecolor='none', edgecolor='black', hatch=hatch, label=label) 
                    for hatch, label in zip(small_hatch_types, datasets_labels)]
            
            handles = handles[::-1]
            labels = datasets_labels[::-1]


            # Adjust handle length and height for the legend box size
            plt.legend(handles=handles, loc='upper left', handleheight=2, handlelength=4)

        else:

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

            for i_d,data in enumerate(split_datasets[data_direction]):
                down_col_data = data['down_col_data']
                
                # Apply smoothing if requested
                down_col_data = smooth_data(down_col_data)
                
                plt.plot(down_col_data.index, down_col_data.values, linestyle=line_styles[i_d], label=data[legend_key])
            
            plt.legend(title=legend_key.replace("_"," ").title(), loc='upper left')

        # Adding labels and title
        plt.xlabel('Time (s)')
        plt.ylabel('Data Rate (KB/s)')
        plt.ylim(0, y_limit)  # Set y-axis limits from 0 to 100
        plt.xlim(0, x_limit)  # Set y-axis limits from 0 to 100
        plt.title(f'Combined Plot for {title_key}')
        

        # Save the plot to a file
        plt.savefig(os.path.join(plots_folder,title_key + "_" + data_direction + ".png"))
        plt.close()  # Close the plot to prevent display in interactive environment

def smooth_data(data, window_size=10):
    """Apply a simple moving average to smooth the data."""
    return data.rolling(window=window_size, min_periods=1).mean()

def plot_individual_data_rate(data_rate_column, plots_folder, output_file, x_limit,y_limit):
    """
    Plots a line plot with the DataFrame index as Time (s) on the x-axis and 
    Data Rate (KB/s) on the y-axis, with the y-axis limited from 0 to 100, and saves it to a file.

    :param df: pandas DataFrame containing the data.
    :param data_rate_column: The column name for Data Rate (KB/s).
    :param output_file: The name of the file to save the plot (include file extension like .png or .jpg).
    """
    print(f'Creating plot for {output_file}')
    

    # Plot
    plt.figure(figsize=(12, 8))

    data_rate_column = smooth_data(data_rate_column)

    plt.plot(data_rate_column.index, data_rate_column.values, label=data_rate_column)

    # Adding labels and title
    plt.xlabel('Time (s)')
    plt.ylabel('Data Rate (KB/s)')
    plt.title('Data Rate over Time')
    plt.ylim(0, y_limit)  # Set y-axis limits from 0 to 100
    plt.xlim(0, x_limit)  # Set y-axis limits from 0 to 100
    # plt.legend()

    # Save the plot to a file
    plt.savefig(os.path.join(plots_folder,output_file + ".png"))
    plt.close()  # Close the plot to prevent display in interactive environments


argparser = argparse.ArgumentParser(
    description='Calculate network throughput from nethogs output')

argparser.add_argument(
    '-i', '--infile',
    metavar='<infile>',
    dest='infile',
    type=str,
    default=None,
    help='name of the infile (no special characters or spaces)')
argparser.add_argument(
    '-d', '--infile_directory',
    metavar='<infile_directory>',
    dest='infile_directory',
    type=str,
    default=None,
    help='directory to search for infiles, will find all .txt files in directory and subdirectories')
argparser.add_argument(
    '-o', '--outfile',
    metavar='<outfile>',
    dest='outfile',
    type=str,
    default=None,
    help='name of the outfile (no special characters or spaces)')
args = argparser.parse_args()



if args.infile and args.infile_directory:
    print("\nERROR - Please specify singular infile (-i) or infile_directory (-d), not both\n")
    print(argparser.print_help())
    sys.exit()
elif not args.infile and not args.infile_directory:
    print("\nERROR - NO INFILE OR INFILE DIRECTORY SPECIFIED\n")
    print(argparser.print_help())
    sys.exit()
elif args.infile:
    infile = str(args.infile)

    if args.outfile:
        outfile = args.outfile
    else:
        outfile = args.infile.replace(".txt",".csv")

    convert_nethogs_to_csv(infile,outfile)
elif args.infile_directory:
    txt_files_found = find_files_by_type(args.infile_directory,".txt")

    for txt_file in txt_files_found:
        convert_nethogs_to_csv(txt_file,txt_file.replace(".txt",".csv"))

    csv_files_found = find_files_by_type(args.infile_directory,".csv")
    analyze_csv_files(csv_files_found,os.path.basename(args.infile_directory)+ "_RESULTS" )




    






