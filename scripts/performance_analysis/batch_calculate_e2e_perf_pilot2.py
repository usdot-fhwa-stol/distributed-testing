import sys
import os
import fnmatch
import json
import csv
# import re
import argparse
# import glob
# import matplotlib.pyplot as plt
# import pandas as pd
# import itertools
# import time
# import batch_generate_e2e_plots

## TODO
#   - make import files a json object so name doesnt matter
#       - add types and names to data from different sources
#   - 
#
#
#
#

# PROCESS FOR USE
#   1. Find start and end times of of event by replaying data and getting start and end time of desired event
#   2. 
#
#
#
#




############################## DATA LOCATION PARAMETERS ##############################

# TEST Times 

# event0 take 1

#   start:  2023-11-17 20:30:38
#   end:    2023-11-17 20:31:26

# even0 take 2: 

#   start:  2023-11-17 20:38:36
#   end:    2023-11-17 20:40:09

# even1 take 2: 

#   start:  2023-12-08 17:35:10
#   end:    2023-12-08 17:43:05


data_types = {
    # "J2735-SPAT": {
    #     "pcap_file_pattern" : "J2735-Payload",
    #     "sdo_file_pattern"   : ["TJ2735Msg-J2735"]
    # },
    "J2735-BSM": {
        "pcap_file_pattern" : "J2735-Payload",
        "sdo_file_pattern"   : ["TJ2735Msg-J2735"]
    },
    # "J2735-MAP": {
    #     "pcap_file_pattern" : "J2735-Payload",
    #     "sdo_file_pattern"   : ["TJ2735Msg-J2735"]
    # },
    # "J3224": {
    #     "pcap_file_pattern" : "J3224-Payload",
    #     "sdo_file_pattern"   : ["TJ3224Msg-J3224"]
    # },
    # "BSM": {
    #     "pcap_file_pattern" : "BSM-SKIPME",
    #     "sdo_file_pattern"   : ["Track-BSM"]
    # },
    # "Mobility_Path": {
    #     "pcap_file_pattern" : "Mobility-Path",
    #     "sdo_file_pattern"   : "Mobility-Path"
    # },
    # "Vehicle": {
    #     "pcap_file_pattern" : "Vehicle-THIS-DOES-NOT-EXIST",
    #     "sdo_file_pattern"   : ["Entities-Vehicle"]
    # },
    # "Mobility_Request": {
    #     "pcap_file_pattern" : "Mobility-Request",
    #     "sdo_file_pattern"   : "Platoon"
    # },
    # "Mobility_Response": {
    #     "pcap_file_pattern" : "Mobility-Response",
    #     "sdo_file_pattern"   : "Platoon"
    # },
    # "Mobility_Operations-INFO": {
    #     "pcap_file_pattern" : "Mobility-Operations",
    #     "sdo_file_pattern"   : "Platoon"
    # },
    # "Mobility_Operations-STATUS": {
    #     "pcap_file_pattern" : "Mobility-Operations",
    #     "sdo_file_pattern"   : "Platoon"
    # },
    # "Traffic_Control_Request": {
    #     "pcap_file_pattern" : "Traffic-Control-Request",
    #     "sdo_file_pattern"   : "TrafficControlRequest"
    # },
    # "Traffic_Control_Message": {
    #     "pcap_file_pattern" : "Traffic-Control-Message",
    #     "sdo_file_pattern"   : "TrafficControlMessage"
    # },
    # "MAP": {
    #     "pcap_file_pattern" : "MAP",
    #     "sdo_file_pattern"   : ["MAP"]
    # },
    # "TrafficLight": {
    #     "pcap_file_pattern" : "SPAT",
    #     "sdo_file_pattern"   : ["TJ2735Msg-J2735","Entities-Signals-TrafficLight"]
    # },
}

################################################## FUNCTIONS ##################################################
    
def find_file_at_path(pattern, path):
    result = []
    for root, dirs, files in os.walk(path):
        for name in files:
            if fnmatch.fnmatch(name, pattern):
                # return os.path.join(root, name)
                result.append(os.path.join(root, name))
    
    if len(result) == 0:
        print("\nERROR: File not found: " + path + " - " + pattern)
        return None
        # sys.exit()
    elif len(result) == 1:
        return result[0]
    else:
        print("\nMultiple files found in dir " + path + " for pattern " + pattern + ". Please select the desired file: [#]")
        for filename_i,filename in enumerate(result):
            print("\t[" + str(filename_i) + "] " +  filename)
        file_index_selection = input("--> ")
        return result[int(file_index_selection)]
            
    return result

def get_obj_by_key_value(obj_array,key,value):
    for index, element in enumerate(obj_array):
        if element[key] == value:
            return index

def find_data_files(exported_tcds_dir,decoded_pcap_in_dir,decoded_pcap_out_dir):

    data_file_locations = {}
    for data_type in data_types:
        data_file_locations[data_type] = {}
    
    
    if decoded_pcap_out_dir:
        print("\n  Locating pcap out files: ")
        for data_type in data_types:
            data_file_locations[data_type]["decoded_pcap_out_file"] = find_file_at_path("*" + data_types[data_type]["pcap_file_pattern"] + "*", decoded_pcap_out_dir)
            print("\t" + data_type + ": " + str(data_file_locations[data_type]["decoded_pcap_out_file"]))
    else:
        for data_type in data_types:
            data_file_locations[data_type]["decoded_pcap_out_file"] = None
        print("\n  No pcap out dir specified")
    
    if decoded_pcap_in_dir:
        print("\n  Locating pcap in files: ")
        for data_type in data_types:
            data_file_locations[data_type]["decoded_pcap_in_file"] = find_file_at_path("*" + data_types[data_type]["pcap_file_pattern"] + "*", decoded_pcap_in_dir)
            print("\t" + data_type + ": " + str(data_file_locations[data_type]["decoded_pcap_in_file"]))
    else:
        for data_type in data_types:
            data_file_locations[data_type]["decoded_pcap_in_file"] = None
        print("\n  No pcap in dir specified") 
        
    if exported_tcds_dir:
        print("\n  Locating exported tdcs files: ")
        for data_type in data_types:
            data_file_locations[data_type]["exported_tcds_file"] = []

            for sdo_type_pattern in data_types[data_type]["sdo_file_pattern"]:
                print(sdo_type_pattern)
                found_file = find_file_at_path("*" + sdo_type_pattern + "*", exported_tcds_dir)
                data_file_locations[data_type]["exported_tcds_file"].append(found_file)
                print("\t" + data_type + ": " + str(data_file_locations[data_type]["exported_tcds_file"]))
    else:
        for data_type in data_types:
            data_file_locations[data_type]["exported_tcds_file"] = None
        print("\n  No exported tdcs dir specified")
    
    return data_file_locations
        
def generate_import_files(source_data,v2xhub_data,dest_data,is_tcr_tcm,test_name):
    
    try:
        os.mkdir("generated_import_files")
    except:
        # print("\nDir generated_import_file already exists")
        pass
    
    try:
        os.mkdir("generated_import_files/" + test_name)
    except:
        # print("\nDir generated_import_file already exists")
        pass
    
    this_import_folder_name = None
    
    for data_type in data_types:
        
        print(f'\tGenerating file for data_type: {data_type}')
        sdo_file_patterns = data_types[data_type]['sdo_file_pattern']
        print(f"\t\tSDO source file {sdo_file_patterns}")
        
        # do not generate import files for TCM because TCR import and analysis includes both TCR and TCM
        # we dont want to remove it from the data list because we still want to get the data files in find_data_files
        if data_type == "Traffic_Control_Message":
            continue
            
        if is_tcr_tcm:
            
            try:
                os.mkdir("generated_import_files/" + test_name + "/" + source_data["site_name"] + "_tcr_tcm")
            except:
                pass
                # print("Dir generated_import_files/" + source_data["site_name"] + "_tcr_tcm" + " already exists")
            
            this_import_folder_name = source_data["site_name"] + "_tcr_tcm"
            this_importfile_name = "generated_import_files/" + test_name + "/" + this_import_folder_name + "/" + source_data["site_name"] + "_tcr_tcm"
            this_importfile_name_obj = open(this_importfile_name + ".csv",'w',newline='')
            this_importfile_name_writer = csv.writer(this_importfile_name_obj,quoting=csv.QUOTE_ALL)
            
            if source_data["lvc"] == "live":
                this_importfile_name_writer.writerow(["load_data","dataset_name","dataset_file_location","dataset_type","message_type"])
                this_importfile_name_writer.writerow(["true",source_data["site_name"] + " J2735 TCR platform out pcap",all_data[source_data["site_name"]]["Traffic_Control_Request"]["decoded_pcap_out_file"],"pcap","Traffic_Control_Request"])
                this_importfile_name_writer.writerow(["true",source_data["site_name"] + " J2735 TCR in to " + v2xhub_data["site_name"] + " J2735 TCR in pcap via DSRC",all_data[v2xhub_data["site_name"]]["Traffic_Control_Request"]["decoded_pcap_in_file"],"pcap","Traffic_Control_Request"])
                this_importfile_name_writer.writerow(["true",v2xhub_data["site_name"] + " J2735 TCR in to " + v2xhub_data["site_name"] + " J2735 TCM out pcap",all_data[v2xhub_data["site_name"]]["Traffic_Control_Message"]["decoded_pcap_out_file"],"pcap","Traffic_Control_Message"])
                this_importfile_name_writer.writerow(["true",v2xhub_data["site_name"] + " J2735 TCM in to " +  source_data["site_name"] + " J2735 TCM in pcap via DSRC",all_data[source_data["site_name"]]["Traffic_Control_Message"]["decoded_pcap_in_file"],"pcap","Traffic_Control_Message"])
            else:
                this_importfile_name_writer.writerow(["load_data","dataset_name","dataset_file_location","dataset_type","message_type"])
                this_importfile_name_writer.writerow(["true",source_data["site_name"] + " J2735 TCR platform out pcap",all_data[source_data["site_name"]]["Traffic_Control_Request"]["decoded_pcap_out_file"],"pcap","Traffic_Control_Request"])
                this_importfile_name_writer.writerow(["true",source_data["site_name"] + " J2735 TCR out to " + source_data["site_name"] + " TCR SDO commit",all_data[source_data["site_name"]]["Traffic_Control_Request"]["exported_tcds_file"],"tdcs","Traffic_Control_Request"])
                this_importfile_name_writer.writerow(["true",source_data["site_name"] + " to " + v2xhub_data["site_name"] + " TCR SDO transmit",all_data[v2xhub_data["site_name"]]["Traffic_Control_Request"]["exported_tcds_file"],"tdcs","Traffic_Control_Request"])
                this_importfile_name_writer.writerow(["true",v2xhub_data["site_name"] + " TCR SDO receipt to " + v2xhub_data["site_name"] + " TCM SDO commit",all_data[v2xhub_data["site_name"]]["Traffic_Control_Message"]["exported_tcds_file"],"tdcs","Traffic_Control_Message"])
                this_importfile_name_writer.writerow(["true",v2xhub_data["site_name"] + " to " + source_data["site_name"] + " TCM SDO transmit",all_data[source_data["site_name"]]["Traffic_Control_Message"]["exported_tcds_file"],"tdcs","Traffic_Control_Message"])
                this_importfile_name_writer.writerow(["false",source_data["site_name"] + " J2735 TCM SDO in to " +  source_data["site_name"] + " J2735 TCM in",all_data[source_data["site_name"]]["Traffic_Control_Message"]["decoded_pcap_in_file"],"pcap","Traffic_Control_Message"])
        
        elif source_data["lvc"] == "live":
            
            try:
                os.mkdir("generated_import_files/" + test_name + "/" +  source_data["site_name"] + "_to_" + dest_data["site_name"])
            except:
                pass
                # print("Dir generated_import_file/" + source_data["site_name"] + "_to_" + dest_data["site_name"] + " already exists")
            
            this_import_folder_name = source_data["site_name"] + "_to_" + dest_data["site_name"]
            this_importfile_name = "generated_import_files/" + test_name + "/" + this_import_folder_name + "/" + source_data["site_name"] + "_to_" + dest_data["site_name"] + "_" + data_type
            this_importfile_name_obj = open(this_importfile_name + ".csv",'w',newline='')
            this_importfile_name_writer = csv.writer(this_importfile_name_obj,quoting=csv.QUOTE_ALL)
            
            this_importfile_name_writer.writerow(["load_data","dataset_name","dataset_file_location","dataset_type","message_type"])
            this_importfile_name_writer.writerow(["true",source_data["site_name"] + " J2735 platform out pcap",all_data[source_data["site_name"]][data_type]["decoded_pcap_out_file"],"pcap",data_type])
            this_importfile_name_writer.writerow(["true",source_data["site_name"] + " to v2xhub DSRC in pcap",all_data[v2xhub_data["site_name"]][data_type]["decoded_pcap_in_file"],"pcap",data_type])
            this_importfile_name_writer.writerow(["true",v2xhub_data["site_name"] + " J2735 in to " + v2xhub_data["site_name"] + " SDO commit",all_data[v2xhub_data["site_name"]][data_type]["exported_tcds_file"],"tdcs",data_type])
            this_importfile_name_writer.writerow(["true",v2xhub_data["site_name"] + " SDO to " + dest_data["site_name"] +  " SDO transmit",all_data[dest_data["site_name"]][data_type]["exported_tcds_file"],"tdcs",data_type])
            this_importfile_name_writer.writerow(["true",dest_data["site_name"] + " SDO to " + dest_data["site_name"] + " J2735 in",all_data[dest_data["site_name"]][data_type]["decoded_pcap_in_file"],"pcap",data_type])
        
        elif dest_data["lvc"] == "live":
            
            try:
                os.mkdir("generated_import_files/" + test_name + "/" +  source_data["site_name"] + "_to_" + dest_data["site_name"])
            except:
                pass
                # print("Dir generated_import_file/" + source_data["site_name"] + "_to_" + dest_data["site_name"] + " already exists")
            
            this_import_folder_name = source_data["site_name"] + "_to_" + dest_data["site_name"]
            this_importfile_name = "generated_import_files/" + test_name + "/" + this_import_folder_name + "/" + source_data["site_name"] + "_to_" + dest_data["site_name"] + "_" + data_type
            this_importfile_name_obj = open(this_importfile_name + ".csv",'w',newline='')
            this_importfile_name_writer = csv.writer(this_importfile_name_obj,quoting=csv.QUOTE_ALL)
            
            this_importfile_name_writer.writerow(["load_data","dataset_name","dataset_file_location","dataset_type","message_type",data_type])
            this_importfile_name_writer.writerow(["true",source_data["site_name"] + " J2735 platform out pcap",all_data[source_data["site_name"]][data_type]["decoded_pcap_out_file"],"pcap",data_type])
            this_importfile_name_writer.writerow(["true",source_data["site_name"] + " J2735 in to " + source_data["site_name"] + " SDO commit",all_data[source_data["site_name"]][data_type]["exported_tcds_file"],"tdcs",data_type])
            this_importfile_name_writer.writerow(["true",source_data["site_name"] + " SDO to " + v2xhub_data["site_name"] +  " SDO transmit",all_data[v2xhub_data["site_name"]][data_type]["exported_tcds_file"],"tdcs",data_type])
            
            if data_type == "BSM":
                print("J2735 messages not generated from constructive vehicles, skipping v2xhub out and live in data")
                continue
            else:
                this_importfile_name_writer.writerow(["true",v2xhub_data["site_name"] + " SDO to v2xhub J2735 out pcap",all_data[v2xhub_data["site_name"]][data_type]["decoded_pcap_out_file"],"pcap",data_type])
                this_importfile_name_writer.writerow(["true",v2xhub_data["site_name"] + " J2735 to " + dest_data["site_name"] + " J2735 DSRC in",all_data[dest_data["site_name"]][data_type]["decoded_pcap_in_file"],"pcap",data_type])
        
        elif v2xhub_data == None:
            
            # check if all the required SDO types exists for this data type
            has_req_data = True
            for sdo_file in sdo_file_patterns:

                if not sdo_file in source_data["adapter_addresses_by_type"]:
                    print(f'\t\tRequired file {sdo_file} not found for {data_type}')
                    has_req_data = False
                    break
            
            if not has_req_data:
                continue
                
            try:
                os.mkdir("generated_import_files/" + test_name + "/" +  source_data["site_name"] + "_to_" + dest_data["site_name"])
            except Exception as err:
                pass
                # print("Dir generated_import_file/" + source_data["site_name"] + "_to_" + dest_data["site_name"] + " already exists")
            
            # for adapter_ip in source_data["adapter_addresses_by_type"][sdo_file_patterns[0]]:

            adapter_ip = source_data["adapter_addresses_by_type"][sdo_file_patterns[0]]

            this_import_folder_name = source_data["site_name"] + "_to_" + dest_data["site_name"]
            this_importfile_name = "generated_import_files/" + test_name + "/" + this_import_folder_name + "/" + source_data["site_name"] + "_to_" + dest_data["site_name"] + "_" + data_type + "_" + str(adapter_ip.replace(".","-").replace(":","_"))
            this_importfile_name_obj = open(this_importfile_name + ".csv",'w',newline='')
            this_importfile_name_writer = csv.writer(this_importfile_name_obj,quoting=csv.QUOTE_ALL)

            print("\t\tGenerating import file: " + this_importfile_name)

            import_data_type = data_type
            
            # write header
            this_importfile_name_writer.writerow(["load_data","dataset_name","dataset_file_location","dataset_type","message_type","adapter_ip","start_time","end_time"])
            
            # TODO - need a better way to organize data inputs to decide when to include pcap when a site has a data type that is in pcap and a data type that isnt
            # this particular logic is always true for pilot 1 but will not always be 
            
            # print(str(all_data[source_data["site_name"]][data_type]["decoded_pcap_out_file"]) + " : " +  str(all_data[source_data["site_name"]][data_type]))

            # if there is a pcap out file (meaning this site generated udp messages for this) and it is one of the listed message types,
            # include a pcap out row
            if all_data[source_data["site_name"]][data_type]["decoded_pcap_out_file"] and data_type in ["J2735-BSM","J2735-SPAT","J2735-MAP","SPAT","TrafficLight"]:
                
                # i dont think this is needed???
                if data_type == "TrafficLight":
                    import_data_type = "TrafficLight"

                this_importfile_name_writer.writerow(["true",source_data["site_name"] + " J2735 pcap out",all_data[source_data["site_name"]][data_type]["decoded_pcap_out_file"],"pcap",import_data_type,None,source_data["start_time"],source_data["end_time"]])
            
            # loop through all the exported TDCS files for this data type for this site
            for sdo_type_file_i,sdo_type_file in enumerate(all_data[source_data["site_name"]][data_type]["exported_tcds_file"]):

                print(f'\t\tAdding row for {sdo_type_file}')
                
                if sdo_type_file_i == 0:
                    if data_type == "TrafficLight":
                        import_data_type = "J2735-SPAT"
                        import_adapter_ip = source_data["adapter_addresses_by_type"]["TJ2735Msg-J2735"]
                    else:
                        import_data_type = data_type
                        import_adapter_ip = adapter_ip
                    
                    this_importfile_name_writer.writerow(["true",source_data["site_name"] + " J2735 in to " + source_data["site_name"] + " SDO commit",sdo_type_file,"tdcs",import_data_type,import_adapter_ip,source_data["start_time"],source_data["end_time"]])
                else:
                    this_importfile_name_writer.writerow(["true",source_data["site_name"] + " to " + source_data["site_name"] + " SDO convert",sdo_type_file,"tdcs",data_type,adapter_ip,source_data["start_time"],source_data["end_time"]])
            
            # if data_type in ["SPAT"]:
            #     this_importfile_name_writer.writerow(["true",sourceJ2735-Payload_data["site_name"] + " J2735 in to " + source_data["site_name"] + " SDO commit",all_data[source_data["site_name"]][data_type]["exported_tcds_file"],"tdcs",data_type,adapter_ip,source_data["start_time"],source_data["end_time"]])
            if data_type == "TrafficLight":
                import_data_file = all_data[dest_data["site_name"]][data_type]["exported_tcds_file"][1]
            else:
                import_data_file = all_data[dest_data["site_name"]][data_type]["exported_tcds_file"][0]

            if not import_data_file:
                print(f'\t\tImport data file is empty, skipping SDO transmit')
            else:
                
                this_importfile_name_writer.writerow(["true",source_data["site_name"] + " SDO to " + dest_data["site_name"] +  " SDO transmit",import_data_file,"tdcs",data_type,None,source_data["start_time"],source_data["end_time"]])
            
            # include pcap in if we are not trafficlight (this doesnt have pcap out since it is not j2735)
            # and if we have a pcap in file listed
            if data_type != "TrafficLight" and all_data[source_data["site_name"]][data_type]["decoded_pcap_in_file"]:
                this_importfile_name_writer.writerow(["true",dest_data["site_name"] + " J2735 to " + dest_data["site_name"] + " J2735 pcap in",all_data[dest_data["site_name"]][data_type]["decoded_pcap_in_file"],"pcap",data_type,None,source_data["start_time"],source_data["end_time"]])
        else:
            print("Invalid vehicle configuration. Must be: live to constructive vehicle, constructive to live vehicle, or constructive to constructive vehicle")
            sys.exit()

        this_importfile_name_obj.close()
        
        with open(this_importfile_name + ".csv") as f:
            num_importfile_rows = sum(1 for line in f)
        # print(f'\t\tnum_importfile_rows {num_importfile_rows}')
        if  num_importfile_rows <= 2:
            print(f'ERROR: only one data source added, skipping this analysis')
            os.remove(this_importfile_name + ".csv")

    
    return this_import_folder_name


argparser = argparse.ArgumentParser(
    description='Batch VOICES Performance Calculation Script for Pilot 2')
argparser.add_argument(
    '-m', '--metadata',
    metavar='<metadata file>',
    dest='metadata',
    type=str,
    default=None,
    help='metadata file containing site details and file locations')
argparser.add_argument(
    '-n', '--name',
    metavar='<event name>',
    dest='name',
    type=str,
    default=None,
    help='event name')
argparser.add_argument(
    '--plot_only',
    action='store_true',
    help='skip data analysis and only regenerate plots')
args = argparser.parse_args()

################################################## MAIN ##################################################

if args.metadata:
    metadata_file_path = args.metadata
else:
    print("\nERROR: Please provide metadata file using the -m argument. See help (-h) for more details")
    sys.exit()

if args.name:
    test_name = args.name
else:
    print("\nERROR: Please provide event name using the -n argument. See help (-h) for more details")
    sys.exit()

if args.plot_only:
    plot_only_arg = " --plot_only"
else:
    plot_only_arg = ""

with open(metadata_file_path, 'r') as metadata_file:
    # Reading from json file
    site_list = json.load(metadata_file)



if not args.plot_only:
    print("\n########## FINDING ALL DATA FILES ##########")


    all_data = {}


    for test_site in site_list:
        print("\nFinding data files for " + test_site["site_name"])
        all_data[test_site["site_name"]] = find_data_files(test_site["tdcs_dir"],test_site["pcap_out_dir"],test_site["pcap_in_dir"])




    print("\n########## GENERATING IMPORT FILES ##########")

    import_file_directory_list = []


    for src_test_site in site_list:
        
        for dest_test_site in site_list:
            if src_test_site != dest_test_site:

                print("\nGenerating for: " + str(src_test_site["site_name"]) + " to " + str(dest_test_site["site_name"]))

                v2xhub_site = None

                if src_test_site["lvc"] == "live" or dest_test_site["lvc"] == "live":
                    
                    v2xhub_site = site_list[get_obj_by_key_value(site_list,"is_v2xhub",True)]

                import_file = generate_import_files(src_test_site,v2xhub_site,dest_test_site,False,test_name)
                if import_file:
                    import_file_directory_list.append(import_file)

    print("\n########## RUNNING DATA ANALYSIS ##########")

    results_base_dir = "results/" + test_name + "_results" 

    try:
        os.makedirs(results_base_dir)
    except:
        pass

    results_summary_outfile_obj = open(results_base_dir + "/" + test_name + "_results_summary.csv",'w',newline='')
    results_summary_outfile_writer = csv.writer(results_summary_outfile_obj)
    results_summary_outfile_writer.writerow(["j2735_type","source","source_type","destination","destination_type","step_type","min","max","mean","jitter","std_dev"])
    results_summary_outfile_obj.close()


    for loader_dir in import_file_directory_list:

        print("\nCurrent analysis direction: " + loader_dir)
        
        for data_type in data_types:
            
            # do not generate import files for TCM because TCR import and analysis includes both TCR and TCM
            # we dont want to remove it from the data list because we still want to get the data files in find_data_files
            if data_type == "Traffic_Control_Message":
                continue
            
            # if the loader dir is tcr_tcm, we are only looking to calculate TCR
            if "tcr_tcm" in loader_dir and data_type != "Traffic_Control_Request":
                continue
            
            if data_type == "Traffic_Control_Request":
                if "tcr_tcm" in loader_dir:
                    loader_file_name_start = loader_dir
                else:
                    # we only want to run analysis on TCR and TCM in specific tcr_tcm loaders 
                    continue
            else:
                loader_file_name_start = loader_dir + "_" + data_type
                
                
            current_dir = os.getcwd()
            abs_loader_dir = os.path.join(current_dir, "generated_import_files",test_name,loader_dir)

            matching_loader_files = []

            # Iterate over all files and directories in the given directory
            for root, dirs, files in os.walk(abs_loader_dir):
                # Check if the file matches the datatype file name
                for filename in fnmatch.filter(files, loader_file_name_start + "*"):
                    # Append the absolute file path to the list of matching files
                    loader_file_to_run_abs = os.path.join(root, filename)
                    source_site = os.path.basename(loader_file_to_run_abs).split("_to_")[0]

                    analysis_command =  "python3 calculate_e2e_perf.py -i " + loader_file_to_run_abs + " -t " + data_type + " -o " + filename + "_performance_results.csv -r " + test_name + plot_only_arg + " -m " + metadata_file_path + " -s " + source_site
                    print("\nExecuting analysis: " + analysis_command)
                    exit_status = os.system(analysis_command)
                    if exit_status != 0:
                        print(f'\nAnalysis encountered an error, exiting...')
                        sys.exit()


# for datatype in data_types:
#     datatype_to_plot = datatype
    
#     if "J2735-" in datatype:
#         datatype_to_plot = datatype.replace("J2735-","")

#     batch_generate_e2e_plots.plot_performance_data("results", datatype_to_plot)




            
        
                    
                    
            
                    
                
                
                
