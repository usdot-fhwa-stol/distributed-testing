import os
import sys
import shutil
import subprocess
import json
from datetime import datetime
import csv
import re
import split_tdcs_for_throughput
import argparse

## TODO: 
#   - move the confirmation to delete from the create_folder function
#   - have the check  for delete occur once for both pcap in and out dirs and ask once


def select_data_folder(input_dir):
    folders = [folder for folder in os.listdir(input_dir) if os.path.isdir(os.path.join(input_dir, folder))]

    if not folders:
        print("No folders found in the current directory.")
        return None

    print("\nSelect a folder to export:")
    for index, folder in enumerate(folders, start=1):
        print(f"\t{index}. {folder}")
    
    while True:
        try:
            user_choice = input("\nSelect a folder by entering the corresponding number (leave empty to use current directory): ")
            if user_choice == '':
                absolute_path = input_dir
            else:
                selected_folder = folders[int(user_choice) - 1]
                absolute_path = os.path.abspath(os.path.join(input_dir, selected_folder))
                
            return absolute_path

        except (ValueError, IndexError):
            print("Invalid input. Please enter a valid number.")

def create_folder(directory_path,directory_name_list):
    
    delete_old_data = None
    confirmation = None

    for directory_name in directory_name_list:
        
        exported_folder_path = os.path.join(directory_path, directory_name)
        # Check if the folder already exists and there are files in it
        if os.path.exists(exported_folder_path) and len([file for file in os.listdir(directory_path) if os.path.isfile(os.path.join(directory_path, file))]) > 0:
            # Confirm with the user before deleting
            if directory_name_list[0].startswith("pcap") and args.export_pcap == True:
                delete_old_data = True
                break

            elif directory_name_list[0].endswith("tdcs") and args.export_tdcs == True:
                delete_old_data = True
                break

            elif directory_name_list[0].startswith("pcap") and args.export_pcap == False:
                delete_old_data = False
                print("\tKeeping old data.")

            elif directory_name_list[0].endswith("tdcs") and args.export_tdcs == False:
                delete_old_data = False
                print("\tKeeping old data.")

            else:
                confirmation = input(f"\nExsisting {directory_name} data found, delete old data and re-export? [y/n]: ").lower()
                if confirmation == 'y':
                    delete_old_data = True
                    break
                else:
                    delete_old_data = False
                    print("\tKeeping old data.")
            
    # if we confrirmed, delete the data
    if delete_old_data:
        try:
            for directory_name in directory_name_list:
                exported_folder_path = os.path.join(directory_path, directory_name)
                # Use shutil.rmtree to delete the folder and its contents
                shutil.rmtree(exported_folder_path)
                print(f"\tFolder '{exported_folder_path}' deleted successfully.")

        except Exception as e:
            print(f"\tError deleting folder: {e}")
            sys.exit()
    # if we said no to deletting data, keep the data and move on
    elif delete_old_data == False:
        return True
    
    # if we did not get the confirmation or we deleted them, create them
    for directory_name in directory_name_list:
        exported_folder_path = os.path.join(directory_path, directory_name)
        try:
            os.makedirs(exported_folder_path)
            print(f"\tCreated {directory_name} folder in {directory_path}")
        except OSError as e:
            print(f"\tError creating folder {exported_folder_path}: {e}")
        

def find_largest_sqlite_file(folder_path):
    # Get a list of files in the specified folder
    files = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]

    # Filter files with ".sqlite" extension
    sqlite_files = [f for f in files if f.endswith('.sqlite')]

    if not sqlite_files:
        print("No .sqlite files found in the specified folder.")
        return None

    # Find the largest .sqlite file
    largest_file = max(sqlite_files, key=lambda f: os.path.getsize(os.path.join(folder_path, f)))

    # Return the absolute path of the largest .sqlite file
    print("\tUsing sqlite file: " + largest_file)
    return os.path.abspath(os.path.join(folder_path, largest_file))

def get_epoch_time():

    while True:
        try:
            user_input = input("\n\t -->  ")
            # Convert user input to datetime object
            input_datetime = datetime.strptime(user_input, "%Y-%m-%d %H:%M:%S")

            # Convert datetime object to epoch time
            epoch_time = int(input_datetime.timestamp())
            
            return epoch_time
        except ValueError:
            print("\nInvalid date format. Please use YYYY-MM-DD HH:MM:SS.")

def get_obj_by_key_value(obj_array,key,value):
    for index, element in enumerate(obj_array):
        if element[key] == value:
            return element
    return None

def get_site_type():
    site_types = ["live","virtual","constructive","v2xhub"]
    

    while True:
        print("\nSelect site type:")
        for index, site_type in enumerate(site_types, start=1):
            print(f"\t{index}. {site_type}")

        try:
            site_choice = input("\nSelect a site type by entering the corresponding number: ")
            selected_site_type = site_types[int(site_choice) - 1]
                
            return selected_site_type

        except (ValueError, IndexError):
            print("Invalid input. Please enter a valid number.")

def remove_file(file_path):
    try:
        os.remove(file_path)
    except OSError as e:
        print(f"Error removing file: {e}")
        sys.exit()

def get_adapter_addresses_by_type(exported_tcs_path,ip_address):

    try:
        # Get a list of all files in the specified directory
        exported_tdcs_files = [f for f in os.listdir(exported_tcs_path) if os.path.isfile(os.path.join(exported_tcs_path, f))]
    except FileNotFoundError:
        return f"Error: Directory not found - {exported_tcs_path}"
    except Exception as e:
        return f"Exception getting list of exported TDCS data: {e}"
    
    adapter_addresses_by_type = {}

    for file in exported_tdcs_files:
        print(f"\tChecking {file}")
        file_path = os.path.join(exported_tcs_path,file)

        pattern = re.compile(r'VUG-(.*?)-202')
        match = pattern.search(file)
        
        if match:
            msg_type = match.group(1)
        else:
            print("\nERROR: Unable to get message type from: " + file)

        try:
            with open(file_path, 'r', newline='') as csvfile:
                reader = csv.DictReader(csvfile)
                headers = reader.fieldnames
                
                if "Metadata,Endpoint" in headers:
                    endpoint_col = "Metadata,Endpoint"
                elif "const^Metadata,Endpoint" in headers:
                    endpoint_col = "const^Metadata,Endpoint"
                else:
                    print(f"Error: unable to locate endpoint column in file: {csvfile}")
                # Assuming the CSV file has a column named "const^Metadata,Endpoint"
                for row in reader:

                    if ip_address == row[endpoint_col].split(":")[0]:
                        adapter_addresses_by_type[msg_type] = row[endpoint_col]
                        
        except FileNotFoundError:
            print(f"Error: File not found - {file_path}")
            sys.exit()
        except Exception as e:
            print(f"Exception reading file ({file_path}): {e}")
            sys.exit()
    
    return adapter_addresses_by_type


def export_pcap_data(site_dir_abs,this_site_metadata):
    # Get a list of files in the specified folder that end with .pcap
    pcap_files = [
        # {
        #     "pcap_file_abs_path": "/a/b/c/d",
        #     "dest_dir": "pcap_in_dir" or "pcap_out_dir"
        # }
    ]

    for f in os.listdir(site_dir_abs):
        this_pcap_file_obj = {}
        this_pcap_file_abs = os.path.join(site_dir_abs, f)
        
        if os.path.isfile(this_pcap_file_abs) and this_pcap_file_abs.endswith('.pcap'):
            this_pcap_file_obj["pcap_file_abs_path"] = this_pcap_file_abs
            file_basename = os.path.basename(f)
            if "j2735" in file_basename.lower():
                if "packet_in" in file_basename.lower():
                    this_pcap_file_obj["dest_dir"] = "pcap_in_dir"
                elif "packet_out" in file_basename.lower():
                    this_pcap_file_obj["dest_dir"] = "pcap_out_dir"
                else:
                    print("\tUnable to identiy file: " + f)
                    print("\tPlease make sure the file contains 'j2735' or 'j3224' and 'packet_in' or 'packet_out'")
                    sys.exit()
            if "j3224" in file_basename.lower():
                if "packet_in" in file_basename.lower():
                    this_pcap_file_obj["dest_dir"] = "pcap_in_dir"
                elif "packet_out" in file_basename.lower():
                    this_pcap_file_obj["dest_dir"] = "pcap_out_dir"
                else:
                    print("\tUnable to identiy file: " + f)
                    print("\tPlease make sure the file contains 'j2735' or 'j3224' and 'packet_in' or 'packet_out'")
                    sys.exit()
        else:
            continue

        pcap_files.append(this_pcap_file_obj)

    skip_export = create_folder(site_dir_abs,["pcap_in_dir","pcap_out_dir"])
    
    if not skip_export:
        for pcap_file in pcap_files:

            if "j3224" in pcap_file:
                print("\tSKIPPING J3224 FOR NOW")
                continue

            if pcap_file["pcap_file_abs_path"] == None:
                print("\tpcap file not found for: " + os.path.basename(pcap_file["pcap_file_abs_path"]))
                continue
            else:
            
                os.chdir(site_dir_abs)

                try:
                    pcap_decoder_path = os.environ["VUG_LOCAL_VOICES_POC_PATH"] + "/scripts/encoding_decoding_tools/J2735_pcap_decoder/src/J2735_pcap_decoder.sh"
                    decoded_pcap_dest = os.path.join(site_dir_abs,pcap_file["dest_dir"])
                    # set the pcap_in_dir and pcap_out_dir in metadata
                    this_site_metadata[pcap_file["dest_dir"]] = decoded_pcap_dest
                    pcap_decoder_cmd = pcap_decoder_path + " -i " + pcap_file["pcap_file_abs_path"] + " -o " + decoded_pcap_dest + " --keep-old-files"
                    sp_results = subprocess.run(pcap_decoder_cmd, shell=True, check=True)

                    if sp_results.returncode != 0:
                        print("\nPcap decoder encountered an error, exiting")
                        sys.exit()

                except subprocess.CalledProcessError as e:
                    print(f"\n\tError loading pcap decoder: \n{e}")
                    this_site_metadata["pcap_export_success"] = False
                    sys.exit()
                except Exception as e:
                    print(f"\n\tError loading pcap decoder: \n{e}")
                    this_site_metadata["pcap_export_success"] = False
                    sys.exit()

                # check to see if any csv files are generated
                csv_files = [file for file in os.listdir(decoded_pcap_dest) if file.endswith('.csv')]

                if len(csv_files) == 0:
                    print(f"NO CSV FILES GENERATED FROM PCAP DECODE")
                    this_site_metadata[pcap_file["dest_dir"]] = ""
                    

    return this_site_metadata

def export_tdcs_data(site_dir_abs,this_site_metadata):
    dataview_dir = "/opt/TENA/DataView-v1.5.4/start.sh"

    skip_export = create_folder(site_dir_abs,["exported_tdcs"])

    if not skip_export:
        tdcs_file_path = find_largest_sqlite_file(site_dir_abs)
        os.chdir(site_dir_abs)
        try:
            tdcs_cmd = dataview_dir + " -d " + tdcs_file_path
            subprocess.run(tdcs_cmd, shell=True, check=True)
        except subprocess.CalledProcessError as e:
            print(f"\n\tError loading TDCS: \n{e}")
            this_site_metadata["tdcs_export_success"] = False
            sys.exit()
        except Exception as e:
            print(f"\n\tError loading TDCS: \n{e}")
            this_site_metadata["tdcs_export_success"] = False
            sys.exit()
    if this_site_metadata["adapter_addresses_by_type"] == {}:
        this_site_metadata["adapter_addresses_by_type"] = get_adapter_addresses_by_type(this_site_metadata["tdcs_dir"],this_site_metadata["ip_address"])
    else:
        if not args.get_endpoints == False:
            
            if args.get_endpoints == True:
                confirmation = 'y'
            else:
                confirmation = input(f"\nWould you like to recheck for adapter endpoints? [y/n]: ").lower()

            if confirmation == 'y':
                this_site_metadata["adapter_addresses_by_type"] = get_adapter_addresses_by_type(this_site_metadata["tdcs_dir"],this_site_metadata["ip_address"])
    

    return this_site_metadata

def parse_args():
    argparser = argparse.ArgumentParser(
    description='Batch decode distributed testing data')

    argparser.add_argument(
        '--use_metadata',
        dest='use_metadata',
        action='store_true',
        default=None,
        help='Use metadata if found in folder'
    )
    argparser.add_argument(
        '--split_tdcs',
        dest='split_tdcs',
        action='store_true',
        default=None,
        help='Split TDCS into inbound and outbound tdcs files'
    )
    argparser.add_argument(
        '--no_split_tdcs',
        dest='split_tdcs',
        action='store_false',
        default=None,
        help='Skip split TDCS into inbound and outbound tdcs files'
    )
    argparser.add_argument(
        '--export_pcap',
        dest='export_pcap',
        action='store_true',
        default=None,
        help='Export PCAP files to CSV'
    )
    argparser.add_argument(
        '--no_export_pcap',
        dest='export_pcap',
        action='store_false',
        default=None,
        help='Skip export PCAP files to CSV'
    )
    argparser.add_argument(
        '--export_tdcs',
        dest='export_tdcs',
        action='store_true',
        default=None,
        help='Export TDCS to CSV'
    )
    argparser.add_argument(
        '--no_export_tdcs',
        dest='export_tdcs',
        action='store_false',
        default=None,
        help='Skip export TDCS to CSV'
    )
    argparser.add_argument(
        '--get_endpoints',
        dest='get_endpoints',
        action='store_true',
        default=None,
        help='Find adapter endpoints by IP'
    )
    argparser.add_argument(
        '--no_get_endpoints',
        dest='get_endpoints',
        action='store_false',
        default=None,
        help='Skip find adapter endpoints by IP'
    )
    
    return argparser.parse_args()

def main(): 
    
    print(f'export_pcap { args.export_pcap}')

    print(f'get_endpoints { args.get_endpoints}')

    start_log_dir = os.environ["VUG_LOG_FILES_ROOT"]
    current_log_dir = start_log_dir
    chosen_log_dir = None

    while True:
        chosen_log_dir = select_data_folder(current_log_dir)
        if chosen_log_dir == None:
            sys.exit()
            
            # continue
        if chosen_log_dir == current_log_dir:
            break
        else:
            current_log_dir = chosen_log_dir

    if chosen_log_dir:
        print(f"Selected folder: {chosen_log_dir}")

        # create_export_folder(chosen_log_dir)

    use_existing_metadata = "n"
    
    metadata_file_path = os.path.join(chosen_log_dir, "metadata.json")

    if os.path.exists(metadata_file_path):

        if args.use_metadata == True:
            use_existing_metadata = "y"
        else:
            use_existing_metadata = input("\nExisting metadata file found, use existing metadata? [y/n] ").lower()

        if use_existing_metadata == 'y':
            print("")
            with open(metadata_file_path, 'r') as metadata_file:
 
                # Reading from json file
                metadata_json = json.load(metadata_file)
            start_time = metadata_json[0]["start_time"]
            end_time = metadata_json[0]["end_time"]
            
        else:
            remove_file(metadata_file_path)

            print ("\nEnter the event start time (YYYY-MM-DD HH:MM:SS): ")
            start_time = get_epoch_time()

            print ("\nEnter the event end time (YYYY-MM-DD HH:MM:SS): ")
            end_time = get_epoch_time()
    else:
        print ("\nEnter the event start time (YYYY-MM-DD HH:MM:SS): ")
        start_time = get_epoch_time()

        print ("\nEnter the event end time (YYYY-MM-DD HH:MM:SS): ")
        end_time = get_epoch_time()

       


    

    # Get a list of all directories in the given parent directory
    site_dirs = [entry for entry in os.listdir(chosen_log_dir) if os.path.isdir(os.path.join(chosen_log_dir, entry))]

    metadata = []

    # Iterate through each directory
    for site_dir in site_dirs:
        print ("\nExporting: " + site_dir)
        site_dir_abs = os.path.join(chosen_log_dir, site_dir)


        if os.path.exists(metadata_file_path):
            with open(metadata_file_path, 'r') as metadata_file:
    
                # Reading from json file
                metadata = json.load(metadata_file)

        this_site_metadata = None
        

        if use_existing_metadata == 'y':
            this_site_metadata = get_obj_by_key_value(metadata,"site_name",site_dir)
        
        if this_site_metadata == None:
            
            this_site_metadata = {
                "site_name" : site_dir,
                "is_v2xhub" : None,
                "lvc" : None,
                "tdcs_dir" : None,
                "pcap_in_dir" : None,
                "pcap_out_dir" : None,
                "start_time" : start_time,
                "end_time" : end_time,
                "ip_address" : None,
                "adapter_addresses_by_type" : {
                    # "J2735-BSM" : [
                    #     # "192.168.2.6:39957",  # test 1-2
                    #     # "192.168.2.6:40079"   # test 3
                    # ],
                },
                "tdcs_export_success" : True,
                "pcap_export_success" : True,
            }
        
        if  (   not "lvc" in this_site_metadata or 
                not "is_v2xhub" in this_site_metadata or 
                this_site_metadata["lvc"] == None or 
                this_site_metadata["is_v2xhub"] == None
            ) :

            site_type = get_site_type()

            if site_type == "v2xhub":
                site_lvc = "live"
                site_is_v2xhub = True
            else:
                site_lvc = site_type
                site_is_v2xhub = False
            
            this_site_metadata["lvc"] = site_lvc
            this_site_metadata["is_v2xhub"] = site_is_v2xhub

        if not "tdcs_dir" in this_site_metadata or this_site_metadata["tdcs_dir"] == None:
            this_site_metadata["tdcs_dir"] = os.path.join(site_dir_abs, "exported_tdcs")

        if not "ip_address" in this_site_metadata or this_site_metadata["ip_address"] == None:
            this_site_metadata["ip_address"] = input("\nEnter this site's IP address [xxx.xxx.xxx]: ")

        
        ##### EXPORT PCAP DATA #####
        this_site_metadata = export_pcap_data(site_dir_abs,this_site_metadata)

        
        ##### EXPORT TDCS DATA #####
        this_site_metadata = export_tdcs_data(site_dir_abs,this_site_metadata)

        ##### SPLIT TDCS DATA #####
        tdcs_to_split = find_largest_sqlite_file(site_dir_abs)
        split_tdcs_for_throughput.split_tdcs(tdcs_to_split,this_site_metadata["ip_address"],args.split_tdcs)


        this_site_metadata_exists = False
        

        for i_m,metadata_to_check in enumerate(metadata):
            if metadata_to_check["site_name"] == this_site_metadata["site_name"]:
                if metadata_to_check != this_site_metadata:
                    print(f'\tUpdating existing metadata {i_m}')
                    metadata[i_m] = this_site_metadata
                this_site_metadata_exists = True
                break
        
        if not this_site_metadata_exists:

            metadata.append(this_site_metadata)
        
        os.chdir(chosen_log_dir)
        with open('metadata.json', 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=4)
        

    # os.chdir(chosen_log_dir)
    # with open('metadata.json', 'w', encoding='utf-8') as f:
    #     json.dump(metadata, f, ensure_ascii=False, indent=4)
    
    print("\nFINISHED EXPORTING AND DECODING ALL DATA")

args = parse_args()

if __name__ == "__main__":
    main()


