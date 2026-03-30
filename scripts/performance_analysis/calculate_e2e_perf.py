import sys
import csv
import datetime
import math
import re
import logging
import glob
import argparse
import json
from pprint import pprint
import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np


############################## TODO ##############################
# - change all data param modifiers (round, buffer, radian) to check if key exists, not value
# - add checks for all param modifiers to check for the proper datatype before attempting to perform modifier
# - remove places where underscore is added to message types
# - incorporate intersection name outside the script (un-hard code )

# checks if value is a number
def is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False

# filter dataset based on specified parameters
def filter_dataset(data_to_filter):

    logging.info("----- FILTERING DATASET: " + data_to_filter["dataset_name"] + " -----")
    logging.debug("Before packets total: " + str(len(data_to_filter["original_data_list"])))
    
    search_starting_row = None
    found_packet_matching_search = False
    cleaned_data_to_search_list = []
   
    # source_data_obj = source_data
    # source_data_list_filtered = source_data_obj["filtered_data_list"]
    # source_packet_to_match = source_data_list_filtered[0]
    # source_packet_params = source_data_obj["dataset_params"]

    # logging.debug("Looking at source packetIndex: " + source_packet_to_match[source_data_obj["dataset_index_column_name"]])


    data_to_search_list = data_to_filter["original_data_list"]
    data_to_search_params = data_to_filter["dataset_params"]

    skipped_packets = 0

    for search_i,search_packet in enumerate(data_to_search_list):

        # if data_to_filter["data_order"] == 1:
        logging.debug("Checking packet index: [" + search_packet[data_to_filter["dataset_index_column_name"]] + "]")
        # else:
        #     logging.debug("Checking packet index: [" + source_packet_to_match[source_data_obj["dataset_index_column_name"]] + ":" + search_packet[data_to_filter["dataset_index_column_name"]] + "]")
        
        # UNABLE TO USE THIS BECAUSE NO WAY TO IDENTIFY TCM BY VEHICLE AT THE MOMENT
        # LEAVING IN AS MAY BE USED LATER
        # quick and dirty way to align multiple tcm with one tcr
        # if the next row contains the same 
        if J2735_message_type_name == "Traffic_Control_Request":
            if (search_i + 1) < len(data_to_search_list) and data_to_search_list[search_i][data_to_filter["dataset_reqid_field"]] == data_to_search_list[search_i + 1][data_to_filter["dataset_reqid_field"]]:
                logging.debug("Skipping TCM since next is from the same request")
                continue
        
        # # if source packet key is j2735_vector, combine all array elements to a single hex value
        # if J2735_message_type_name == "J2735":

        #     j2735_payload = ""
        #     num_j2735_vector_elements = int(search_packet["Vector,binaryContent,count"])
            
        #     for array_element in range(1,num_j2735_vector_elements+1):
        #         binary_element = int(search_packet["binaryContent^UInt8 (" + str(array_element) + ")"])
        #         hex_element = hex(binary_element).split('x')[-1].zfill(2)
        #         j2735_payload = j2735_payload + hex_element

        #     search_packet["binaryContent^UInt8"] = j2735_payload
        
        
        if data_to_filter["dataset_type"] == "pcap":
            filter_packet_timestamp = float(search_packet["packetTimestamp"])
        elif data_to_filter["dataset_type"] == "tdcs":
            if data_to_filter["dataset_message_type"] in J2735_message_types_as_tena_message:
                # this is ideally time of transmission, but it functions the same
                filter_packet_timestamp = float(search_packet["Metadata,TimeOfTransmission"])/1000000000
            else:
                filter_packet_timestamp = float(search_packet["Metadata,TimeOfCommit"])/1000000000
        
        if filter_packet_timestamp < data_to_filter["start_time"] or filter_packet_timestamp > data_to_filter["end_time"]:
            logging.debug("Skipping packet because not in time bounds")
            continue


        # if the J2735_message_subtype is not none, we must be J2735 
        if J2735_message_subtype_name != None:
            
            # check the value of the first match key (which should be the J2735 payload since that is the only value for J2735) and check whether the first 4 digits are equal to the appropriate subtype id value
            if data_to_filter["dataset_type"] == "pcap":
                j2735_payload_key = data_to_search_params["J2735"]["match_keys"][0]["key"]

                if not search_packet[j2735_payload_key].startswith(J2735_message_type_ids[J2735_message_subtype_name]):
                    logging.debug("Skipping packet because doesnt start with correct ID")
                    logging.debug("  " + search_packet[j2735_payload_key] + " !^ " + J2735_message_type_ids[J2735_message_subtype_name])
                    continue

            elif data_to_filter["dataset_type"] == "tdcs":
                if search_packet["messageType,String"] != J2735_message_subtype_name:
                    logging.debug("Skipping packet because doesnt start with correct ID")
                    logging.debug("  " + search_packet["messageType,String"] + " !^ " + J2735_message_subtype_name)
                    continue

        # iterate through the neqs to check
        all_neqs_pass = True

        for current_neq in data_to_search_params[data_to_filter["dataset_message_type"]]["skip_if_neqs"]:
            
            neq_bypass = False

            # skip if values are not equal (ex: checking for matching bsm id)
            search_packet_neq_value = search_packet[current_neq["key"]]
            neq_param_value = current_neq["value"]

            if "e+" in search_packet_neq_value:
                search_packet_neq_value = float(search_packet_neq_value)

            logging.debug("  NEQ CHECK: " + str(search_packet_neq_value) + " != " + str(neq_param_value))

            # if we have already found the start of the data set (and therefore the offset),
            # and the current neq is for the start_only, skip this neq
            if not found_packet_matching_search and "start_only" in current_neq and current_neq["start_only"]:
                logging.debug("    Skipping NEQ since it is start only: " + current_neq["key"])
                continue
            
            # if we are looking at TCM, all TCM come from the v2xhub so check against the v2xhub IP
            if data_to_filter["dataset_message_type"] == "Traffic_Control_Message" and "use_v2xhub_ip_for_tcm" in current_neq and current_neq["use_v2xhub_ip_for_tcm"]:
                logging.debug("    Using v2xhub IP since all TCM are generated by the v2xhub")
                neq_param_value = v2xhub_ip_address

            # if the source_packet_value is a number and we want to round, round both values to the same number of decimals
            if "round" in current_neq and current_neq["round"]:
                    
                    try:
                        search_packet_neq_value = round(float(search_packet_neq_value),current_neq["round_decimals"])
                    except:
                        logging.error("    Unable to round: " + search_packet_neq_value)
                    try:
                        neq_param_value = round(float(neq_param_value),current_neq["round_decimals"])
                    except:
                        logging.error("    Unable to round: " + neq_param_value)

            
            # the only way to know which vehicle sent the mobility operations is to check if the timestamps are close together
            if "mobility_timestamp_check" in current_neq and current_neq["mobility_timestamp_check"]:
                
                # we need to use this timesstamp check for filtering pcaps in but it breaks if we dont have a first data point
                # if data_to_filter["data_order"] == 1:
                #     neq_bypass = True
                
                # if the cleaned data list is empty, this must be the first packet and we need to feed a starting timestamp value
                if len(cleaned_data_to_search_list) == 0:
                    
                    # if we are the first dataset, use the timestamp from the current packet
                    if data_to_filter["data_order"] == 1:
                        previous_timestamp = float(search_packet["headerTimestamp"])
                    else:
                        previous_timestamp = float(all_data[0]["filtered_data_list"][0]["headerTimestamp"])
                        
                        if data_to_filter["dataset_type"] == "tdcs":
                            previous_timestamp = previous_timestamp * 1000000 # tdcs timestamps are in nanoseconds, mobility header timestamp is in ms

                    
                # if we do have something in the list, we can just use the last timestamp
                else:
                    previous_timestamp = cleaned_data_to_search_list[-1][current_neq["key"]]
                
                logging.debug("    Timestamp check: " + str(previous_timestamp) + " ~ " + str(search_packet_neq_value) )
                # check if difference is greater than 1 second (1000000000 ns)
                if abs(int(float(search_packet_neq_value)) - int(float(previous_timestamp))) > 1000000000:
                    logging.debug("    Skipping because timestamp doesnt match therefore must be other vehicle")
                    all_neqs_pass = False
                    break
                else:
                    neq_bypass = True
                    
            if "reqid_check" in current_neq and current_neq["reqid_check"]:
                if data_to_filter["data_order"] == 1:
                    neq_bypass = True
                elif search_packet_neq_value in source_reqid_list:
                    logging.debug("  reqid found in source reqids, keeping packet")
                    neq_bypass = True
                else:
                    all_neqs_pass = False
                    logging.debug("  reqid not found in source reqids, skipping packet")
                    break

            if search_packet_neq_value != neq_param_value and not neq_bypass:
                logging.debug("    Skipping non matching value: " + str(search_packet_neq_value) + " != " + str(neq_param_value))
                all_neqs_pass = False
                break
        
        if not all_neqs_pass:
            logging.debug("  Continuing because not all NEQs passed")
            continue
        
        #iterate through the eqs to check
        all_eqs_pass = True

        for current_eq in data_to_search_params[data_to_filter["dataset_message_type"]]["skip_if_eqs"]:
            
            eq_bypass = False
            
            # skip if values are equal (ex: skip if speed is 0)
            search_packet_eq_value = search_packet[current_eq["key"]]
            eq_param_value = current_eq["value"]

            if "e+" in search_packet_eq_value:
                search_packet_eq_value = float(search_packet_neq_value)

            logging.debug("  EQ CHECK: " + str(search_packet_eq_value) + " == " + str(eq_param_value))

            # if we have already found the start of the data set (and therefore the offset),
            # and the current eq is for the start_only, skip this neq
            if found_packet_matching_search and "start_only" in current_eq and current_eq["start_only"]:
                logging.debug("    Skipping EQ since it is start only: " + current_eq["key"])
                continue

            # if the source_packet_value is a number and we want to round, round both values to the same number of decimals
            if "round" in current_eq and current_eq["round"]:
                    
                    try:
                        search_packet_eq_value = round(float(search_packet_eq_value),current_eq["round_decimals"])
                    except:
                        logging.warning("    Unable to round: " + search_packet_eq_value)
                    
                    try:
                        eq_param_value = round(float(eq_param_value),current_eq["round_decimals"])
                    except:
                        logging.warning("    Unable to round: " + eq_param_value )

            if "starts_with" in current_eq and current_eq["starts_with"]:
                logging.debug("    Checking if: " + str(search_packet_eq_value) + " starts with " + str(current_eq["value"]))
                
                starts_with_search = re.search('^' + current_eq["value"],search_packet_eq_value)

                if not starts_with_search:
                    logging.debug("    Value doesnt start with " + str(current_eq["value"]))
                    eq_bypass = True
                else:
                    logging.debug("    Skipping because value starts with " + str(current_eq["value"]))
                    all_eqs_pass = False
                    break
            
            if search_packet_eq_value == eq_param_value and not eq_bypass:
                logging.debug("    Skipping matching value: " + str(search_packet_eq_value) + " == " + str(eq_param_value))
                all_eqs_pass = False
                break
        
        if not all_eqs_pass:
            logging.debug("  Continuing because not all EQs passed")
            continue
        
        # here we are continuing if this packet was not found in other datasets
        # this is accomplished by skipping and counting the number of skipped packets 
        # until it matches the desired skipped packet number
        # TODO: This can probably get moved up before the eq and neqs 
        # if data_to_filter["data_order"] == 1 and skipped_packets < desired_num_of_skipped_packets:
                        
        #     logging.debug("Skipping packet to find one that exists in all datasets")
        #     skipped_packets += 1
        #     continue

        # because J2735 data can repeat for BSMs, we need to look for the first unique value so we can eliminate the repeating values in the start
        
        if data_to_filter["data_order"] == 1 and data_to_filter["dataset_message_type"] == "Traffic_Control_Request":
            logging.debug("Adding source reqid to list: " + search_packet[data_to_filter["dataset_reqid_field"]])
            source_reqid_list.append(search_packet[data_to_filter["dataset_reqid_field"]])

        # if we are filtering the source data, we are not matching it against anything so skip this bottom part
        # if not kept_at_least_one_packet:
        #     kept_at_least_one_packet = True
            # search_starting_row = search_i
            # logging.debug("Found source search_starting_row: " + str(search_starting_row))
        
        logging.debug("Keeping Packet: " + str(search_packet[data_to_filter["dataset_index_column_name"]]))
        cleaned_data_to_search_list.append(search_packet)

        

        # the first time all fields match, this is the start of the data we want
        # get the offset between the source start index and the search start index
        #
        # UPDATE:   with the new method of filtering out the data lists, ideally all lists index 0 align
        #           this might not always be the case (if the first valid packet was dropped) so we do this anyway

        # if not found_packet_matching_search:

        #     all_fields_match = check_if_data_matches(source_packet_params,data_to_search_params,source_packet_to_match,search_packet)
            
        #     if all_fields_match:
        #         logging.debug("All Fields match for " + data_to_filter["dataset_name"])
        #         found_packet_matching_search = True

        # since it was not eliminated from the NEQ and EQs, add the packet to the filtered data list
        # if found_packet_matching_search:
        #     logging.debug("Keeping Packet: " + str(search_packet[data_to_filter["dataset_index_column_name"]]))
        #     cleaned_data_to_search_list.append(search_packet)

    # if search_starting_row == None:
    #     # if desired_num_of_skipped_packets == len(data_to_search_list):
    #     #         logging.critical("Unable to find any packets in source dataset that exits in all other datasets. Consider changing the EQ and NEQ")
    #     #         print("\nUnable to find any packets in source dataset that exits in all other datasets. Consider changing the EQ and NEQ")
    #     #         sys.exit()
    #     # else:
    #     logging.critical("search_starting_row not set - Unable to find a single packet in source that satisfies the EQ and NEQ. Consider changing the EQ and NEQ to find a starting packet")
    #     print("\nUnable to find a single packet in source data that satisfies the EQ and NEQ, Consider changing the EQ and NEQ to find a starting packet")
    #     sys.exit()

        
    if len(cleaned_data_to_search_list) == 0:
        logging.warning("[!!!] found_packet_matching_search false - Unable to find a single packet that satisfies the EQ and NEQ")
        return

    data_to_filter["filtered_data_list"] = cleaned_data_to_search_list
    # data_to_filter["found_packet_matching_search"] = found_packet_matching_search

    # filtered_data_list = dataset["cleaned_data_to_search_list"]
    filtered_total_packets = len(data_to_filter["filtered_data_list"])
    logging.info("Cleaned packets total - " + data_to_filter["dataset_name"] + ": " + str(filtered_total_packets))

    logging.debug("Last packetIndex: " + data_to_filter["filtered_data_list"][filtered_total_packets -1][data_to_filter["dataset_index_column_name"]])

def align_dataset(source_data,data_to_search):

    logging.info("----- ALIGNING DATASETS: " + source_data["dataset_name"] + " and " + data_to_search["dataset_name"] + " -----")
    logging.debug("Before packets total: " + str(len(source_data["filtered_data_list"])))
    
    search_starting_row = None
    found_packet_matching_search = False
    cleaned_data_to_search_list = []
   
    source_data_obj = source_data
    source_data_list_filtered = source_data_obj["filtered_data_list"]
    source_packet_to_match = source_data_list_filtered[0]
    source_packet_params = source_data_obj["dataset_params"]

    logging.debug("Looking at source packetIndex: " + source_packet_to_match[source_data_obj["dataset_index_column_name"]])

    data_to_search_list = data_to_search["filtered_data_list"]
    data_to_search_params = data_to_search["dataset_params"]

    for search_i,search_packet in enumerate(data_to_search_list):
        
        # if data_to_search["data_order"] == 1:
        #     logging.debug("Checking packet index: [" + search_packet[data_to_search["dataset_index_column_name"]] + "]")
        # else:
        logging.debug("Checking packet index: [" + source_packet_to_match[source_data_obj["dataset_index_column_name"]] + ":" + search_packet[data_to_search["dataset_index_column_name"]] + "]")
        
        # UNABLE TO USE THIS BECAUSE NO WAY TO IDENTIFY TCM BY VEHICLE AT THE MOMENT
        # LEAVING IN AS MAY BE USED LATER
        # quick and dirty way to align multiple tcm with one tcr
        # if the next row contains the same 
        if J2735_message_type_name == "Traffic_Control_Request":
            if (search_i + 1) < len(data_to_search_list) and data_to_search_list[search_i][data_to_search["dataset_reqid_field"]] == data_to_search_list[search_i + 1][data_to_search["dataset_reqid_field"]]:
                logging.debug("Skipping TCM since next is from the same request")
                continue  

        all_fields_match = check_if_data_matches(source_packet_params,data_to_search_params,source_packet_to_match,search_packet)
        
        if all_fields_match:
            logging.debug("All Fields match for " + data_to_search["dataset_name"])
            found_packet_matching_search = True
            search_starting_row = search_i
            break

        
    if not found_packet_matching_search:
        logging.warning("[!!!] found_packet_matching_search false - Unable to find first source packet in dataset")
        return
    else:
        logging.warning("[!!!] found_packet_matching_search true - " + str(search_starting_row))

    # data_to_search["filtered_data_list"] = cleaned_data_to_search_list
    data_to_search["found_packet_matching_search"] = found_packet_matching_search
    data_to_search["starting_dataset_index"] = search_i

    # filtered_data_list = dataset["cleaned_data_to_search_list"]
    # filtered_total_packets = len(data_to_search["filtered_data_list"])
    # logging.info("Cleaned packets total - " + data_to_search["dataset_name"] + ": " + str(filtered_total_packets))

    # logging.debug("Last packetIndex: " + dataset["filtered_data_list"][filtered_total_packets -1][dataset["dataset_index_column_name"]])

def find_first_unique_packet_old(data_to_search):

    logging.info("----- FINDING FIRST UNIQUE PACKET: " + data_to_search["dataset_name"] + " -----")
    logging.debug("Before total: " + str(len(data_to_search["filtered_data_list"])))

    data_to_search_list = data_to_search["filtered_data_list"]
    data_to_search_params = data_to_search["dataset_params"]

    for search_i,search_packet in enumerate(data_to_search_list):

        packet_is_unique = True

        logging.debug("Checking if packet is unique")
        for unique_search_i,unique_search_packet in enumerate(data_to_search_list,start=search_i+1):
            # if unique_search_i < search_i:
            #     continue
            
            logging.debug("Checking if packet is unique [" + str(search_i) + ":" + str(unique_search_i) + "]")
            unique_packet_check = check_if_data_matches(data_to_search_params,data_to_search_params,search_packet,unique_search_packet)

            if unique_packet_check:
                packet_is_unique = False
                break

        if not packet_is_unique:
            logging.debug("Packet is not unique")
            continue
        else:
            logging.debug("Packet is unique")
            data_to_search_list = data_to_search["filtered_data_list"][search_i:]
            break
    
    logging.debug("After total: " + str(len(data_to_search["filtered_data_list"])))

def find_first_unique_packet(data_to_search):
    
    logging.info("Searching for first unique packet in dataset")

    # Create a dictionary to store the count of each payload value
    unique_packets = []

    data_to_search_list = data_to_search["filtered_data_list"]
    data_to_search_params = data_to_search["dataset_params"]

    # Count the occurrences of each payload value
    for packet_to_check in data_to_search_list:
        logging.debug("  Checking packet index: " + str(packet_to_check[data_to_search["dataset_index_column_name"]]))

        packet_is_in_unique_packets = False

        for unique_packet_obj in unique_packets:
            
            packet_is_in_unique_packets = check_if_data_matches(data_to_search_params,data_to_search_params,unique_packet_obj["packet"],packet_to_check)

            if packet_is_in_unique_packets:
                break

        if packet_is_in_unique_packets:
            unique_packet_obj["count"] += 1
            logging.debug("  Found duplicate packet: " + str(packet_to_check[data_to_search["dataset_index_column_name"]]) + " = " + str(unique_packet_obj["packet"][data_to_search["dataset_index_column_name"]]) + " count: " + str(unique_packet_obj["count"]))
        else:
            unique_packets.append(
                {
                    "packet"    : packet_to_check,
                    "count"     : 1
                }
            )
            logging.debug("  Found unique packet: " + str(packet_to_check[data_to_search["dataset_index_column_name"]]) )

    # Find the first element with a payload value that occurs only once
    for unique_packet_obj in unique_packets:
        if unique_packet_obj["count"] == 1:
            return unique_packet_obj["packet"]

    # Return None if no unmatched element is found
    return None

def extract_dtd_from_mob_ops(ops_params_value):
    # logging.debug("  EXTRACTING DTD FROM: " + str(ops_params_value))
    mobility_op_type_search = re.search('^(.*)\|',ops_params_value)

    if not mobility_op_type_search:
        # logging.debug("  Error, unable to extract STATUS or INFO from operations params")
        return None

    mobility_op_type = mobility_op_type_search.group(1)

    if mobility_op_type == "INFO":
        # logging.debug("  Got INFO message")
        
        dtd_search = re.search('DTD:(.*),ECEFX:',ops_params_value)

        if not dtd_search:
            logging.debug("  Error, unable to extract DTD from operations params")
            return None
        
        try:
            dtd_value = float(dtd_search.group(1))
        except:
            logging.debug("Unable to convert DTD to float: " + dtd_search.group(1))
            return None
            
        
        # logging.debug("dtd_value: " + str(dtd_value))
        return dtd_value
        
    elif mobility_op_type == "STATUS":
        # logging.debug("Got STATUS message")
        
        dtd_search = re.search('DTD:(.*),SPEED:',ops_params_value)

        if not dtd_search:
            logging.debug("Error, unable to extract DTD from operations params")
            return None
        
        try:
            dtd_value = float(dtd_search.group(1))
        except:
            # logging.debug("Unable to convert DTD to float: " + dtd_search.group(1))
            return None
            
        
        logging.debug("  dtd_value: " + str(dtd_value))

        return dtd_value
    else:
        logging.debug("  Got invalid mobility ops message")


# checks all match params for two give packets
def check_if_data_matches(source_packet_params,data_to_search_params,source_packet_to_match,search_packet):

    all_fields_match = True


    for match_i in range(0,num_match_keys):
        source_packet_key = source_packet_params[J2735_message_type_name]["match_keys"][match_i]["key"]
        search_packet_key = data_to_search_params[J2735_message_type_name]["match_keys"][match_i]["key"]

        logging.debug("  source_packet_key: " + str(source_packet_key))
        logging.debug("  search_packet_key: " + str(search_packet_key))

        # if the source or search packet match key are none. the same index of each match key should align. 
        # see definition at the top of the file for more info
        if (
                source_packet_key == None or
                search_packet_key == None
        ):
            logging.debug("  Skipping match key " + str(match_i) + " since one or more keys are None: " + str(source_packet_key) + "," + str(search_packet_key))
            continue
        
        # if source packet key is j2735_vector, combine all array elements to a single hex value
        if "j2735_vector" in source_packet_params[J2735_message_type_name]["match_keys"][match_i] and source_packet_params[J2735_message_type_name]["match_keys"][match_i]["j2735_vector"]:

            j2735_payload = ""
            num_j2735_vector_elements = int(source_packet_to_match["Vector,binaryContent,count"])
            
            for array_element in range(1,num_j2735_vector_elements+1):
                binary_element = int(source_packet_to_match["binaryContent^UInt8 (" + str(array_element) + ")"])
                hex_element = hex(binary_element).split('x')[-1].zfill(2)
                j2735_payload = j2735_payload + hex_element

            # !!! ASSUME ALL SPAT ARE LESS THAN 255 HEX BYTES
            # the third hex byte in a J2735 message is the remaining char
            # ex: 00 13 6B  40 85...
            #      0 19 107 64 79
            #            ^ = 107 hex bytes remaining after this byte == 110 total
            if J2735_message_subtype_name == "SPAT":
                hex_string_length = (int(source_packet_to_match["binaryContent^UInt8 (3)"]) + 3)*2
                j2735_payload = j2735_payload[0:hex_string_length]

            source_packet_to_match[source_packet_key] = j2735_payload

        # if source packet key is j2735_vector, combine all array elements to a single hex value
        if "j2735_vector" in data_to_search_params[J2735_message_type_name]["match_keys"][match_i] and data_to_search_params[J2735_message_type_name]["match_keys"][match_i]["j2735_vector"]:

            j2735_payload = ""
            num_j2735_vector_elements = int(search_packet["Vector,binaryContent,count"])
            
            for array_element in range(1,num_j2735_vector_elements+1):
                binary_element = int(search_packet["binaryContent^UInt8 (" + str(array_element) + ")"])
                hex_element = hex(binary_element).split('x')[-1].zfill(2)
                j2735_payload = j2735_payload + hex_element

            # !!! ASSUME ALL SPAT ARE LESS THAN 255 HEX BYTES
            # the third hex byte in a J2735 message is the remaining char
            # ex: 00 13 6B  40 85...
            #      0 19 107 64 79
            #            ^ = 107 hex bytes remaining after this byte == 110 total
            if J2735_message_subtype_name == "SPAT":
                hex_string_length = (int(search_packet["binaryContent^UInt8 (3)"]) + 3)*2
                j2735_payload = j2735_payload[0:hex_string_length]

            search_packet[search_packet_key] = j2735_payload

        
        source_packet_value = source_packet_to_match[source_packet_key]
        search_packet_value = search_packet[search_packet_key]

        # print(source_packet_value)
        # print(search_packet_value)


        if "extract_mobility_dtd" in source_packet_params[J2735_message_type_name]["match_keys"][match_i] and source_packet_params[J2735_message_type_name]["match_keys"][match_i]["extract_mobility_dtd"]:
            
            extracted_dtd = extract_dtd_from_mob_ops(source_packet_value)

            if extracted_dtd != None:
                source_packet_value = extracted_dtd
            else:
                all_fields_match = False
                logging.error("  DTD could not be extracted from mob ops string, skipping packet")
                break

        if "extract_mobility_dtd" in data_to_search_params[J2735_message_type_name]["match_keys"][match_i] and data_to_search_params[J2735_message_type_name]["match_keys"][match_i]["extract_mobility_dtd"]:
            
            extracted_dtd = extract_dtd_from_mob_ops(search_packet_value)

            if extracted_dtd != None:
                search_packet_value = extracted_dtd
            else:
                all_fields_match = False
                logging.error("  DTD could not be extracted from mob ops string, skipping packet")
                break

        if "divide_by" in source_packet_params[J2735_message_type_name]["match_keys"][match_i]:
            source_packet_value = float(source_packet_value)/source_packet_params[J2735_message_type_name]["match_keys"][match_i]["divide_by"]
        
        if "divide_by" in data_to_search_params[J2735_message_type_name]["match_keys"][match_i]:
            search_packet_value = float(search_packet_value)/data_to_search_params[J2735_message_type_name]["match_keys"][match_i]["divide_by"]

        if "multiply_by" in source_packet_params[J2735_message_type_name]["match_keys"][match_i]:
            source_packet_value = float(source_packet_value)*source_packet_params[J2735_message_type_name]["match_keys"][match_i]["multiply_by"]
        
        if "multiply_by" in data_to_search_params[J2735_message_type_name]["match_keys"][match_i]:
            search_packet_value = float(search_packet_value)*data_to_search_params[J2735_message_type_name]["match_keys"][match_i]["multiply_by"]
            
        if "radians" in source_packet_params[J2735_message_type_name]["match_keys"][match_i] and source_packet_params[J2735_message_type_name]["match_keys"][match_i]["radians"]:
            try:
                source_packet_value = math.degrees(float(source_packet_value))
            except:
                logging.error("[!!!] Unable to convert to radians: " + source_packet_value)

        if "radians" in data_to_search_params[J2735_message_type_name]["match_keys"][match_i] and data_to_search_params[J2735_message_type_name]["match_keys"][match_i]["radians"]:
            try:
                search_packet_value = math.degrees(float(search_packet_value))
            except:
                logging.error("[!!!] Unable to convert to radians: " + search_packet_value)

        if "round" in source_packet_params[J2735_message_type_name]["match_keys"][match_i] and source_packet_params[J2735_message_type_name]["match_keys"][match_i]["round"]:
            try:
                source_packet_value = round(float(source_packet_value),source_packet_params[J2735_message_type_name]["match_keys"][match_i]["round_decimals"])
            except:
                logging.error("[!!!] Unable to round: " + source_packet_value)

        if "round" in data_to_search_params[J2735_message_type_name]["match_keys"][match_i] and data_to_search_params[J2735_message_type_name]["match_keys"][match_i]["round"]:
            try:
                search_packet_value = round(float(search_packet_value),data_to_search_params[J2735_message_type_name]["match_keys"][match_i]["round_decimals"])
            except:
                logging.error("[!!!] Unable to round: " + search_packet_value)


        spat_state_mappings = {
            "VUG::Entities::Signals::TrafficLightState_Green" : "green",
            "protected-Movement-Allowed" : "green",
            "VUG::Entities::Signals::TrafficLightState_Green" : "green",
            "permissive-Movement-Allowed" : "green",

            "VUG::Entities::Signals::TrafficLightState_Red" : "red",
            "stop-And-Remain" : "red",

            "VUG::Entities::Signals::TrafficLightState_Yellow" : "yellow",
            "protected-clearance" : "yellow",
            "VUG::Entities::Signals::TrafficLightState_Yellow" : "yellow",
            "permissive-clearance" : "yellow",             

        }

        if "spat_state" in source_packet_params[J2735_message_type_name]["match_keys"][match_i] and source_packet_params[J2735_message_type_name]["match_keys"][match_i]["spat_state"]:
            source_packet_value = spat_state_mappings[source_packet_value]
        
        if "spat_state" in data_to_search_params[J2735_message_type_name]["match_keys"][match_i] and data_to_search_params[J2735_message_type_name]["match_keys"][match_i]["spat_state"]:
            search_packet_value = spat_state_mappings[search_packet_value]

        if  ( source_packet_value != search_packet_value ):
            
            #TODO this logic could be better 
            if "buffer" in source_packet_params[J2735_message_type_name]["match_keys"][match_i]:
                try:
                    float(search_packet_value)
                    float(source_packet_value)
                except:
                    logging.warning("Unable to apply buffer since one of these is not a number: " + str(search_packet_value) + " : "+ str(source_packet_value))
                    all_fields_match = False
                    break

                source_buffer = source_packet_params[J2735_message_type_name]["match_keys"][match_i]["buffer"]
                if abs(source_packet_value - search_packet_value) >  source_buffer:
                    logging.debug("  [!!!] VALUES DO NOT MATCH WITHIN BUFFER [" + str(source_packet_key) + "] " + str(source_packet_value) + " == " + str(search_packet_value))
                    all_fields_match = False
                    break
                else:
                    logging.debug("  Values Match within buffer [" + str(source_packet_key) + "] " + str(source_packet_value) + " == " + str(search_packet_value) + " +/- " + str(source_buffer))
            
            else:

                logging.debug("  [!!!] VALUES DO NOT MATCH [" + str(source_packet_key) + "] " + str(source_packet_value) + " == " + str(search_packet_value))
                all_fields_match = False
                break
        else:
            logging.debug("  Values Match [" + str(source_packet_key) + "] " + str(source_packet_value) + " == " + str(search_packet_value))
    
    
    return all_fields_match

# prints all the match params and values for two given packets
def print_keys(source_params,check_params,source_packet,check_packet,log_level):
    for match_i in range(0,num_match_keys):
            
        source_key = source_params[J2735_message_type_name]["match_keys"][match_i]["key"]
        check_key = check_params[J2735_message_type_name]["match_keys"][match_i]["key"]

        if (  source_key == None or check_key == None ):
            continue
        if log_level == "debug":
            logging.debug("  - " + source_packet[source_key] + " == " + check_packet[check_key])
        elif log_level == "info":
            logging.info("  - " + source_packet[source_key] + " == " + check_packet[check_key])
        elif log_level == "warning":
            logging.warning("  - " + source_packet[source_key] + " == " + check_packet[check_key])

def clean_name(input_name):
    logging.debug("Dirty Name: " + input_name)
    clean_name = re.sub('\.csv', '', input_name)
    clean_name = re.sub('\.\/data\/.*\/', '', clean_name)
    clean_name = re.sub('[^A-Za-z0-9 _-]+', '', clean_name)
    clean_name = re.sub(' ', '_', clean_name)
    
    clean_name = clean_name.lower()
    
    logging.debug("Clean Name: " + clean_name)
    return clean_name

def load_data(dataset_name,dataset_infile,dataset_type,dataset_message_type,adapter_ip,start_time,end_time):

    dataset_name_clean = clean_name(dataset_name)

    logging.info("----- LOADING DATA FOR " + dataset_name_clean + " -----")

    data_infile_obj = open(dataset_infile,'r')
    data_infile_reader = csv.DictReader(data_infile_obj,delimiter=',')
    data_infile_headers = data_infile_reader.fieldnames
    logging.debug("  Data Headers: " + str(data_infile_headers))

    data_list = list(data_infile_reader)
    total_packets = len(data_list)

    logging.info("  Total Packets: " + str(total_packets))
    print("\t" + dataset_name_clean + ": " + str(total_packets))

    if total_packets == 0:
        print("\nERROR: " + dataset_name_clean + " dataset is empty" )
        sys.exit()

    if dataset_type == "pcap":
        dataset_params = data_params["pcap_params"]
        dataset_index_column_name = "packetIndex"
        dataset_reqid_field = "reqid_hex"
    elif dataset_type == "tdcs":
        dataset_params = data_params["tdcs_params"]
        dataset_index_column_name = "rowID"
        dataset_reqid_field = "requestID,String"
    

    if "J2735-" in dataset_message_type:
        dataset_message_subtype = dataset_message_type.replace("J2735-","")
        dataset_message_type = "J2735"
    else:
        dataset_message_subtype = None

    # if the dataset has an adapter_ip row and the neq wants to filter on it, insert the configured IP to the neq value
    if adapter_ip:
        for neq in dataset_params[dataset_message_type]["skip_if_neqs"]:
            if neq["key"] == "Metadata,Endpoint":
                neq["value"] = adapter_ip
    


    
    num_datasets_loaded = len(all_data)
    
    all_data.append({
        "dataset_name"                  : dataset_name_clean,
        "data_order"                    : num_datasets_loaded + 1,
        "original_data_list"            : data_list,
        "filtered_data_list"            : [],
        "dataset_type"                  : dataset_type,
        "dataset_params"                : dataset_params,
        "dataset_index_column_name"     : dataset_index_column_name,
        "found_packet_matching_search"  : False,
        "dataset_reqid_field"           : dataset_reqid_field,
        "dataset_message_type"          : dataset_message_type,
        "dataset_message_subtype"       : dataset_message_subtype,
        "start_time"                    : float(start_time),
        "end_time"                      : float(end_time),
        
    })

def get_obj_by_key_value(obj_array,key,value):
    for index, element in enumerate(obj_array):
        if element[key] == value:
            return index

def check_for_dropped_packets():

    source_data_obj_index = get_obj_by_key_value(all_data,"data_order",1)
    source_data_obj = all_data[source_data_obj_index]
    source_data_list_filtered = source_data_obj["filtered_data_list"]
    source_packet_params = source_data_obj["dataset_params"]

    dropped_packet_counts = {}

    dataset_offsets = {}

    for dataset_i in range(1,len(all_data)):
        dropped_packet_counts[all_data[dataset_i]["dataset_name"]] = 0
        dataset_offsets[all_data[dataset_i]["dataset_name"]] = 0


    logging.debug("----- CHECKING FOR DROPPED PACKETS -----")
    for source_i,source_packet in enumerate(source_data_list_filtered):
        
        for dataset_i in range(1,len(all_data)):
            
            # i know this is lazy, i already had it written this way before :)
            dataset = all_data[dataset_i]

            # check to make sure we did not reach the end of the file on the dataset 
            if source_i >= len(dataset["filtered_data_list"]):               
                logging.warning("  [!!!] Reached end of file for " + dataset["dataset_name"] +  ", does not contain source row [" + source_packet[source_data_obj["dataset_index_column_name"]] + "]")

                # dropped_packet_counts[dataset["dataset_name"]] += 1

                # insert a filler row in the data lists with the dropped packet
                dropped_packet_placeholder = {}

                for key in dataset["filtered_data_list"][source_i-1]:
                    dropped_packet_placeholder[key] = "EOF"

                dataset["filtered_data_list"].insert(source_i ,dropped_packet_placeholder)

                continue
            
            logging.debug("Checking against source packet: " + source_packet[source_data_obj["dataset_index_column_name"]])

            packet_lookahead = 0
            packet_lookahead_max = 50

            # we are unable to completely filter the pcap in dataset since we are not decoding the J2735 payload to get any filtering criteria
            # therefore, we are trying to look ahead in the dataset to skip unfiltered rows
            while packet_lookahead < packet_lookahead_max:
                
                if len(dataset["filtered_data_list"]) <= source_i + packet_lookahead:
                    logging.debug("Reached end of dataset")
                    all_fields_match = False
                    break

                current_dataset_packet = dataset["filtered_data_list"][source_i + packet_lookahead]

                all_fields_match = check_if_data_matches(source_packet_params,dataset["dataset_params"],source_packet,current_dataset_packet)

                if not all_fields_match:
                    logging.debug("Skipping ahead " + str(packet_lookahead) + " for desired packet")
                    packet_lookahead += 1
                else:
                    dataset_offsets[all_data[dataset_i]["dataset_name"]] += packet_lookahead
                    logging.debug("Found packet by looking ahead " + str(packet_lookahead) + ", new total offset is " + str(dataset_offsets[all_data[dataset_i]["dataset_name"]]))
                    del dataset["filtered_data_list"][source_i:source_i + packet_lookahead]

                    break

            if not all_fields_match:
                logging.warning("  [!!!] Found dropped packet in " + dataset["dataset_name"] +  " [" + source_packet[source_data_obj["dataset_index_column_name"]] + ":" + current_dataset_packet[dataset["dataset_index_column_name"]] + "]: ")
                print_keys(source_packet_params,dataset["dataset_params"],source_packet,current_dataset_packet,"warning")

                dropped_packet_counts[dataset["dataset_name"]] += 1

                # insert a filler row in the data lists with the dropped packet
                dropped_packet_placeholder = {}

                for key in current_dataset_packet:
                    dropped_packet_placeholder[key] = "DROPPED PACKET"

                dataset["filtered_data_list"].insert(source_i ,dropped_packet_placeholder)

            else:
                logging.debug("  Found matching packet in " + dataset["dataset_name"] +  " [" + source_packet[source_data_obj["dataset_index_column_name"]] + ":" + current_dataset_packet[dataset["dataset_index_column_name"]] + "]: ")
                
                print_keys(source_packet_params,dataset["dataset_params"],source_packet,current_dataset_packet,"debug")
    
    print("\nDropped Packet Totals: ")
    for dataset_name in dropped_packet_counts:
        print("\t" + dataset_name + ": " + str(dropped_packet_counts[dataset_name]))             

def calculate_performance_metrics():

    source_data_obj_index = get_obj_by_key_value(all_data,"data_order",1)
    source_data_obj = all_data[source_data_obj_index]
    source_data_list_filtered = source_data_obj["filtered_data_list"]

    logging.info("----- CALCULATING PERFORMANCE METRICS -----")
    for source_i,source_packet in enumerate(source_data_list_filtered):

        current_row_data = {}

        # add source data packet index
        current_row_data[ source_data_obj["dataset_name"] + "_" + source_data_obj["dataset_index_column_name"] ] = source_packet[source_data_obj["dataset_index_column_name"]]

        if source_data_obj["dataset_type"] == "pcap":
            source_packet_timestamp = float(source_packet["packetTimestamp"])
        elif source_data_obj["dataset_type"] == "tdcs":
            if J2735_message_type_name in J2735_message_types_as_tena_message:
                # this is ideally time of transmission, but it functions the same
                source_packet_timestamp = float(source_packet["Metadata,TimeOfTransmission"])/1000000000
            else:
                source_packet_timestamp = float(source_packet["Metadata,TimeOfCommit"])/1000000000


        current_row_data[ source_data_obj["dataset_name"] + "_timestamp"] = source_packet_timestamp
        logging.debug("----- CALCULATING PERFORMANCE FOR SOURCE PACKET " + source_packet[source_data_obj["dataset_index_column_name"]] + " -----")
        logging.debug("source_packet_timestamp: " + str(source_packet_timestamp))

        if J2735_message_type_name == "BSM" and source_data_obj["dataset_type"] == "pcap":

            # calculate the bsm broadcast latency
            secMark = float(source_packet["secMark"])
            packet_timestamp = datetime.datetime.fromtimestamp(int(float(source_packet_timestamp)))
            roundDownMinTime = datetime.datetime(packet_timestamp.year,packet_timestamp.month,packet_timestamp.day,packet_timestamp.hour,packet_timestamp.minute).timestamp()
            packetSecondsAfterMin = (float(source_packet_timestamp) - roundDownMinTime)
            bsm_broadcast_latency = packetSecondsAfterMin*1000 - secMark

            if (bsm_broadcast_latency < 0) :
                logging.debug("[!!!] Minute mismatch")
                bsm_broadcast_latency = bsm_broadcast_latency + 60000

            current_row_data["platform_bsm_generation_to_obu_latency"] = bsm_broadcast_latency
    
        # loop through all datasets except the first (source)
        for dataset_i in range(1,len(all_data)):
            
            # check to make sure we did not reach the end of the file on the dataset 
            if source_i >= len(all_data[dataset_i]["filtered_data_list"]):
                logging.debug("Reached end of " + all_data[dataset_i]["dataset_name"] + ", stopping dropped packet check")
                return

            current_dataset_packet = all_data[dataset_i]["filtered_data_list"][ source_i ]
            # logging.debug("current_dataset_packet: " + str(current_dataset_packet))
            # current_dataset_packet = all_data[dataset_i]["filtered_data_list"][ source_i]



            if all_data[dataset_i]["dataset_type"] == "pcap":
                logging.debug("" + all_data[dataset_i]["dataset_name"] + "_packet_index: " + current_dataset_packet["packetIndex"])

                if current_dataset_packet["packetIndex"] == "DROPPED PACKET":
                    current_row_data[ all_data[dataset_i]["dataset_name"] + "_packet_index" ] = "DROPPED PACKET"
                    current_row_data[ all_data[dataset_i]["dataset_name"] + "_timestamp"] = "DROPPED PACKET"
                    current_row_data[ all_data[dataset_i]["dataset_name"] + "_total_latency"] = "DROPPED PACKET"
                elif current_dataset_packet["packetIndex"] == "EOF":
                    current_row_data[ all_data[dataset_i]["dataset_name"] + "_packet_index" ] = "EOF"
                    current_row_data[ all_data[dataset_i]["dataset_name"] + "_timestamp"] = "EOF"
                    current_row_data[ all_data[dataset_i]["dataset_name"] + "_total_latency"] = "EOF"
                else:
                    current_row_data[ all_data[dataset_i]["dataset_name"] + "_packet_index" ] = current_dataset_packet["packetIndex"]
                    
                    pcap_timestamp = float(current_dataset_packet["packetTimestamp"])
                    logging.debug("pcap_timestamp: " + str(pcap_timestamp))

                    current_row_data[ all_data[dataset_i]["dataset_name"] + "_timestamp"] = pcap_timestamp
        
                    dataset_total_latency = (pcap_timestamp - float(source_packet_timestamp)) * 1000
                    logging.debug("dataset_total_latency: " + str(dataset_total_latency))

                    current_row_data[ all_data[dataset_i]["dataset_name"] + "_total_latency"] = dataset_total_latency 

                # calculate the incremental latency (latency from previous step to this step)
                # can not calculate incremental latency of the source data (no previous step to subtract from)
                if (dataset_i != 1):
                    if current_dataset_packet["packetIndex"] == "DROPPED PACKET":
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_incremental_latency"] = "DROPPED PACKET"
                    elif current_dataset_packet["packetIndex"] == "EOF":
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_incremental_latency"] = "EOF"
                    elif (  current_row_data[ all_data[dataset_i-1]["dataset_name"] + "_total_latency"] == "DROPPED PACKET" or
                            current_row_data[ all_data[dataset_i-1]["dataset_name"] + "_total_latency"] == "EOF" ):
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_incremental_latency"] = "NO PREV PACKET"
                    else:
                        dataset_incremental_latency = (dataset_total_latency - current_row_data[ all_data[dataset_i-1]["dataset_name"] + "_total_latency"])
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_incremental_latency"] = dataset_incremental_latency 
                        logging.debug("dataset_incremental_latency: " + str(dataset_incremental_latency))


                
            
            elif all_data[dataset_i]["dataset_type"] == "tdcs":
                logging.debug("" + all_data[dataset_i]["dataset_name"] + "_packet_index: " + current_dataset_packet["rowID"])
                

                # if the previous dataset is from a tdcs, we want to know how long it took to go from created (committed) at the source
                # and received and the dest. this is tdcs_time_of_receipt - tdcs_time_of_commit

                if all_data[dataset_i-1]["dataset_type"] == "tdcs":
                    
                    if current_dataset_packet["rowID"] == "DROPPED PACKET":
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_rowID"  ] = "DROPPED PACKET"
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_tdcs_time_of_receipt"] = "DROPPED PACKET"
                        # current_row_data[ all_data[dataset_i]["dataset_name"] + "_tdcs_commit_to_receipt"] = "DROPPED PACKET"
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_total_latency"] = "DROPPED PACKET"
                    elif current_dataset_packet["rowID"] == "EOF":
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_rowID"  ] = "EOF"
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_tdcs_time_of_receipt"] = "EOF"
                        # current_row_data[ all_data[dataset_i]["dataset_name"] + "_tdcs_commit_to_receipt"] = "EOF"
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_total_latency"] = "EOF"
                    else:
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_rowID" ] = current_dataset_packet["rowID"]
                        
                        if J2735_message_type_name in J2735_message_types_as_tena_message:
                            # this is ideally time of transmission, but it functions the same
                            tdcs_time_of_commit = float(current_dataset_packet["Metadata,TimeOfTransmission"])/1000000000
                        else:
                            tdcs_time_of_creation = float(current_dataset_packet["const^Metadata,TimeOfCreation"])/1000000000
                            tdcs_time_of_commit = float(current_dataset_packet["Metadata,TimeOfCommit"])/1000000000
                        
                        
                        tdcs_time_of_receipt = float(current_dataset_packet["Metadata,TimeOfReceipt"])/1000000000
                        
                        logging.debug("tdcs_time_of_receipt: " + str(tdcs_time_of_receipt))
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_tdcs_time_of_receipt"] = tdcs_time_of_receipt
                       
                        # this is really a sanity check. it should be the same as the incremental latency
                        # tdcs_commit_to_receipt = tdcs_time_of_receipt - tdcs_time_of_commit
                        # logging.debug("tdcs_commit_to_receipt: " + str(tdcs_commit_to_receipt))
                        # current_row_data[ all_data[dataset_i]["dataset_name"] + "_tdcs_commit_to_receipt"] = tdcs_commit_to_receipt

                        dataset_total_latency = (tdcs_time_of_receipt - float(source_packet_timestamp)) * 1000
                        logging.debug("dataset_total_latency: " + str(dataset_total_latency))
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_total_latency"] = dataset_total_latency


                # if the previous dataset is a pcap, we want to know how long it took from the adapter receiving it to it being committed
                elif all_data[dataset_i-1]["dataset_type"] == "pcap":
                    # if dropped packet, write that row accordingly
                    if current_dataset_packet["rowID"] == "DROPPED PACKET":
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_rowID"  ] = "DROPPED PACKET"
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_total_latency"] = "DROPPED PACKET"
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_tdcs_time_of_commit"] = "DROPPED PACKET"
                    elif current_dataset_packet["rowID"] == "EOF":
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_rowID"  ] = "EOF"
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_total_latency"] = "EOF"
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_tdcs_time_of_commit"] = "EOF"
                    else:
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_rowID"  ] = current_dataset_packet["rowID"]
                        
                        if J2735_message_type_name in J2735_message_types_as_tena_message:
                            # this is ideally time of transmission, but it functions the same
                            tdcs_time_of_commit = float(current_dataset_packet["Metadata,TimeOfTransmission"])/1000000000
                        else:
                            tdcs_time_of_creation = float(current_dataset_packet["const^Metadata,TimeOfCreation"])/1000000000
                            tdcs_time_of_commit = float(current_dataset_packet["Metadata,TimeOfCommit"])/1000000000
                            
                        tdcs_time_of_receipt = float(current_dataset_packet["Metadata,TimeOfReceipt"])/1000000000
                        
                        logging.debug("tdcs_time_of_commit: " + str(tdcs_time_of_commit))
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_tdcs_time_of_commit"] = tdcs_time_of_commit

                        dataset_total_latency = (tdcs_time_of_commit - float(source_packet_timestamp))* 1000
                        logging.debug("dataset_total_latency: " + str(dataset_total_latency))
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_total_latency"] = dataset_total_latency 
        
                else:
                    logging.debug("[???] HOW DID WE GET HERE????")
                    sys.exit()

                # calculate the incremental latency (latency from previous step to this step)
                # can not calculate incremental latency of the source data (no previous step to subtract from)

                if (dataset_i != 1):                    
                    if current_dataset_packet["rowID"] == "DROPPED PACKET":
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_incremental_latency"] = "DROPPED PACKET"
                    elif current_dataset_packet["rowID"] == "EOF":
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_incremental_latency"] = "EOF"
                    elif (  current_row_data[ all_data[dataset_i-1]["dataset_name"] + "_total_latency"] == "DROPPED PACKET" or
                            current_row_data[ all_data[dataset_i-1]["dataset_name"] + "_total_latency"] == "EOF"):
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_incremental_latency"] = "NO PREV PACKET"
                    else:
                        
                        logging.debug("dataset_incremental_latency = " + str(dataset_total_latency) + " - " + str(current_row_data[ all_data[dataset_i-1]["dataset_name"] + "_total_latency"]))
                        dataset_incremental_latency = dataset_total_latency - current_row_data[ all_data[dataset_i-1]["dataset_name"] + "_total_latency"]
                        current_row_data[ all_data[dataset_i]["dataset_name"] + "_incremental_latency"] = dataset_incremental_latency
                        logging.debug("dataset_incremental_latency: " + str(dataset_incremental_latency))
                
        
        # if this is the first iteration, write the headers
        if(source_i) == 0:
            results_outfile_writer.writerow(current_row_data.keys())

        # write the values to a row
        logging.debug("current_row_data: " + str(current_row_data) + "\n")
        results_outfile_writer.writerow(current_row_data.values())

def performance_post_processing(results_file):
    print("\nPerfoirming Post Processing: " + results_file)
    
    try:
        results_infile = pd.read_csv(results_file)
    except:
        logging.error("Unable to open results file")
        print("\tERROR: Unable to open results file")
        sys.exit()
    
    
    found_first_total_latency = False
    
    filtered_dataset = results_infile
    
    # remove all rows with EOF, DROPPED PACKET, NO PREV PACKET in any column
    # for column in results_infile:
    #     filtered_dataset = results_infile[(results_infile[column] != "EOF") & (results_infile[column] != "DROPPED PACKET") & (results_infile[column] != "NO PREV PACKET")]
    
    # convert values to numeric

    
    filtered_dataset_numeric = filtered_dataset.apply(pd.to_numeric,errors='coerce')
    
    if args.results_summary_prefix:

        results_summary_outfile_obj = open(results_base_dir + "/" + args.results_summary_prefix + "_results_summary.csv",'a')
        results_summary_outfile_writer = csv.writer(results_summary_outfile_obj)

    incremental_latency_cols = [col for col in filtered_dataset_numeric if "_incremental_latency" in col]
    total_latency_cols = [col for col in filtered_dataset_numeric if "_total_latency" in col]

    # we want the first total latency (which is really the first incremental), all remaining incremental, and the final total latency
    # this probably wont play nice with only one total latency column but we are likely not doing all this for one latency step
    if len(total_latency_cols) > 1:
        results_only_dataset_old_names = filtered_dataset_numeric[[total_latency_cols[0]] + incremental_latency_cols + [total_latency_cols[-1]]]
        
        results_only_dataset = results_only_dataset_old_names.rename(columns={total_latency_cols[-1]: total_latency_cols[-1] + '_e2e'})

    else:
        results_only_dataset_old_names = filtered_dataset_numeric[[total_latency_cols[-1]] + incremental_latency_cols ]
        
        results_only_dataset = results_only_dataset_old_names.rename(columns={total_latency_cols[-1]: total_latency_cols[-1] + '_e2e'})

    for column in results_only_dataset:
        
        ## REPLACED WITH results_only_dataset logic above
        # # skip all columns which do not contain incremental_latency
        # # but we want the first total_latency since it is essentially the first incremental
        # if not found_first_total_latency and "_total_latency" in column:
        #     found_first_total_latency = True
        # elif not "_incremental_latency" in column:
        #     # print("\t" + str(column) + ": XXX")
        #     continue
        
        print("\t" + str(column) + ": ")
        
        column_min = results_only_dataset[column].min()
        column_max = results_only_dataset[column].max()
        column_mean = results_only_dataset[column].mean()
        print("\t\tMin: " + str(column_min))
        print("\t\tMax: " + str(column_max))
        print("\t\tMean: " + str(column_mean))

        # if "dsrc" in column or transmit, calculate jitter
        if "dsrc" in column or "transmit" in column:
            # filtered_dataset = results_only_dataset.dropna()
            # print(str(filtered_dataset))
            
            filtered_dataset_numeric_diff = results_only_dataset[column] - results_only_dataset[column].shift(-1)
            filtered_dataset_numeric_diff_abs = filtered_dataset_numeric_diff.abs().dropna()
            # print(str(filtered_dataset_numeric_diff_abs))
            
            column_mean_diff = filtered_dataset_numeric_diff_abs.mean()
            column_std_dev = "NA"
            print("\t\tJitter: " + str(column_mean_diff))
        else:
            filtered_dataset_numeric_dropna = results_only_dataset[column].dropna()
            column_std_dev = filtered_dataset_numeric_dropna.std()
            column_mean_diff = "NA"
            print("\t\tStd Dev: " + str(column_std_dev))

        if args.results_summary_prefix:
            column_split = column.split("_to_")

            src_name_and_type = column_split[0]
            src_name_and_type_split = src_name_and_type.split("_")
            src_name = src_name_and_type_split[0]
            src_type = src_name_and_type_split[1]

            # print("src_name: " + src_name)

            dst_name_type_step_split = column_split[1].split("_")
            dst_name = dst_name_type_step_split[0]
            dst_type = dst_name_type_step_split[1]
            # print("dst_name: " + dst_name)


            if column.endswith("total_latency_e2e"):
                src_name = args.source_site.lower()
                step_type = "total_latency"
            elif "_transmit" in column_split[1]:
                step_type = "sdo_transmit"
            elif "_commit" in column_split[1]:
                step_type = "sdo_commit"
            elif "_pcap_in" in column_split[1]:
                step_type = "pcap_in"
            elif "_pcap_out" in column_split[1]:
                step_type = "pcap_out"

            results_summary_outfile_writer.writerow([J2735_message_subtype_name,src_name,src_type,dst_name,dst_type,step_type,column_min,column_max,column_mean,column_mean_diff,column_std_dev])

    
        
#################### LOAD DATA ####################

def load_data_user_input():
        
    still_loading_data = True
    loaded_filenames = []

    if J2735_message_type_name == "Mobility_Operations-INFO" or J2735_message_type_name == "Mobility_Operations-STATUS":
        J2735_message_type_folder_name = "Mobility_Operations"
    else:
        J2735_message_type_folder_name = J2735_message_type_name
    
    while still_loading_data == True:
        if len(all_data) > 0:
            print("\n\n\nCurrently Loaded Datasets: ")
            for dataset in all_data:
                print("\t" + dataset["dataset_name"])



        print("\nAvailable Dataset input files:")

        try:
            available_dataset_list = glob.glob("./data/" + J2735_message_type_folder_name + "/*")
        except:
            print("[!!!] No data found at " + "./data/" + J2735_message_type_folder_name)

        print("\nWhat dataset would you like to load? [#]\n")
        for dataset_i,dataset_path in enumerate(available_dataset_list):
            if dataset_path in loaded_filenames:
                continue
            print("[" + str(dataset_i + 1) + "] " + dataset_path)

        dataset_selection_index = input("\n    --> ")

        try:
            dataset_selected = available_dataset_list[int(dataset_selection_index) -1]
        except:
            print("[!!!] Invalid selection, try again")
            continue

        dataset_type = input("\nWhat type of data is this? [pcap/tdcs] ")

        if not dataset_type in ["pcap","tdcs"]:
            print("[!!!] Invalid selection, try again")
            continue
        
        print("\n Importing " + dataset_selected)
        load_data(dataset_selected,dataset_selected,dataset_type,0)

        loaded_filenames.append(dataset_selected)

        load_another_dataset_yn = input('\nWould load additional datasets? [y/n] ').lower()

        if not load_another_dataset_yn.startswith('y'):
            still_loading_data = False


def load_data_from_csv(datasets_infile):

    datasets_infile_obj = open(datasets_infile,'r')
    datasets_infile_reader = csv.DictReader(datasets_infile_obj,delimiter=',')

    datasets_list = list(datasets_infile_reader)
    total_packets = len(datasets_list)

    for dataset_line in datasets_list:
        if str(dataset_line["load_data"]) == "true":
            load_data(dataset_line["dataset_name"],dataset_line["dataset_file_location"],dataset_line["dataset_type"],dataset_line["message_type"],dataset_line["adapter_ip"],dataset_line["start_time"],dataset_line["end_time"])

#################### PLOT DATA ####################


def plot_latency(file_path, results_base_dir):
    # Load the CSV file
    try:
        data = pd.read_csv(file_path)
    except:
        print(f'ERROR: Unable to read file: {file_path}')
        sys.exit()
    
    # Identify the columns containing "_incremental_latency" and "_total_latency"
    incremental_latency_cols = [col for col in data.columns if "_incremental_latency" in col]
    total_latency_cols = [col for col in data.columns if "_total_latency" in col]
    timestamp_cols = [col for col in data.columns if "timestamp" in col]
    # print(f'timestamp_cols: {timestamp_cols}')
    
    # Find the first and last columns with "_total_latency"
    first_total_latency_col = total_latency_cols[0]
    last_total_latency_col = total_latency_cols[-1]
    
    first_timestamp_col = timestamp_cols[0]
    # print(f'first_timestamp_col: {first_timestamp_col}')
    timestamps = pd.to_datetime(data[first_timestamp_col], unit='s',errors='coerce')
    data.insert(0,"converted_timestamps",timestamps,True)
    # print(f'timestamps: {timestamps}')

    # Get the base name of the file without extension
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    
    # Combine incremental columns and first total latency column for plotting
    incremental_col_to_plot = incremental_latency_cols + [first_total_latency_col] + [last_total_latency_col]

    # print(f'incremental_col_to_plot: {incremental_col_to_plot}')

    ################# 
    # Plot the combined plot of all incremental latency columns and the first total latency column
    ################# 

    plt.figure(figsize=(20, 8))
    eof_label_added = False
    dropped_packet_label_added = False
    no_prev_packet_label_added = False

    incremental_col_to_plot_values = []
    
    first_timestamp_data = pd.to_numeric(data[first_timestamp_col], errors='coerce')

    end_of_shortest_data = None

    for col in incremental_col_to_plot:
        numeric_data = pd.to_numeric(data[col], errors='coerce')
        
        incremental_col_to_plot_values.append(numeric_data)

        plt.plot(timestamps, numeric_data, label=clean_column_name(col))
        
        # Check for "EOF" in the column and plot a vertical line if found
        eof_indices = data[data[col] == 'EOF'].index
        for idx in eof_indices:
            plt.axvline(x=timestamps[idx], color='r', linestyle='--', linewidth=1, alpha=0.1, label='EOF' if not eof_label_added else "")
            eof_label_added = True
        
        # Check for "DROPPED PACKET" in the column and plot a vertical line if found
        dropped_indices = data[data[col] == 'DROPPED PACKET'].index
        for idx in dropped_indices:
            plt.axvline(x=timestamps[idx], color='b', linestyle='--', linewidth=1, alpha=0.1, label='DROPPED PACKET' if not dropped_packet_label_added else "")
            dropped_packet_label_added = True
        
        # Check for "NO PREV PACKET" in the column and plot a vertical line if found
        no_prev_indices = data[data[col] == 'NO PREV PACKET'].index
        for idx in no_prev_indices:
            plt.axvline(x=timestamps[idx], color='g', linestyle='--', linewidth=1, alpha=0.1, label='NO PREV PACKET' if not no_prev_packet_label_added else "")
            no_prev_packet_label_added = True
    
        # Find where the condition is met
        consecutive = data[col].eq("DROPPED PACKET").rolling(window=10).sum() == 10

        # Get the first index where this is True
        first_occurrence = consecutive.idxmax() if consecutive.any() else None

        if first_occurrence != None:
            if end_of_shortest_data == None or not end_of_shortest_data < first_occurrence:
                end_of_shortest_data = first_occurrence




    plt.title('Latency of each Segment')
    plt.xlabel('Index')
    # Ensure end_of_shortest_data is within the range of available timestamps
    if end_of_shortest_data is not None:
        max_timestamp = timestamps.max()
        min_timestamp = timestamps.min()
        
        # Check if end_of_shortest_data falls within the range of the timestamps
        if timestamps[end_of_shortest_data] >= min_timestamp and timestamps[end_of_shortest_data] <= max_timestamp:
            plt.gca().set_xlim(right=timestamps[end_of_shortest_data])
        else:
            # If end_of_shortest_data is out of bounds, set the limit to the maximum timestamp
            plt.gca().set_xlim(right=max_timestamp)
    plt.ylabel('Latency (ms)')
    plt.gca().set_ylim(bottom=0)
    plt.legend()
    plt.grid(True)
    combined_plot_path = os.path.join(results_base_dir, f'{base_name}_combined_plot.png')
    plt.savefig(combined_plot_path)
    plt.close()

    ################# 
    # plot stacked bar chart
    ################# 
    
    plt.figure(figsize=(20, 8))
    x = range(0,len(incremental_col_to_plot_values[0]))
    bar_width = 1/24/60/60/11
    plt.bar(x=data["converted_timestamps"], height=incremental_col_to_plot_values[0], color='r', width=bar_width)
    if len(incremental_col_to_plot_values) > 1:
        plt.bar(data["converted_timestamps"], height=incremental_col_to_plot_values[1], bottom=incremental_col_to_plot_values[0], color='b', width=bar_width)

        if len(incremental_col_to_plot_values) > 2:
            plt.bar(data["converted_timestamps"], height=incremental_col_to_plot_values[2], bottom=incremental_col_to_plot_values[0]+incremental_col_to_plot_values[1], color='g', width=bar_width)
    
    plt.ylabel("Latency (ms)")
    plt.gca().set_ylim(bottom=0)
    plt.xlabel('Index')

    if end_of_shortest_data != None:
        plt.gca().set_xlim(right=end_of_shortest_data)

    cleaned_col_names = []
    for col_name in incremental_col_to_plot:
        cleaned_col_names.append(clean_column_name(col_name))

    plt.legend(cleaned_col_names)
    plt.title("Latency in Segments")
    
    bar_plot_path = f'{file_path}_stacked_bar_chart.png'
    plt.savefig(bar_plot_path)
    plt.close()

    # print(f'last_total_latency_col: {last_total_latency_col}')

    ################# 
    # Plot the last total latency column
    ################# 

    plt.figure(figsize=(20, 8))
    last_total_latency_data = pd.to_numeric(data[last_total_latency_col], errors='coerce')
    plt.plot(timestamps, last_total_latency_data, label="End to End Latency", color='red')

    eof_label_added = False
    dropped_packet_label_added = False
    no_prev_packet_label_added = False
    
    # Check for "EOF" in the last total latency column and plot a vertical line if found
    eof_indices = data[data[last_total_latency_col] == 'EOF'].index
    for idx in eof_indices:
        plt.axvline(x=timestamps[idx], color='r', linestyle='--', linewidth=1, alpha=0.1, label='EOF' if not eof_label_added else "")
        eof_label_added = True
    
    # Check for "DROPPED PACKET" in the last total latency column and plot a vertical line if found
    dropped_indices = data[data[last_total_latency_col] == 'DROPPED PACKET'].index
    for idx in dropped_indices:
        plt.axvline(x=timestamps[idx], color='b', linestyle='--', linewidth=1, alpha=0.1, label='DROPPED PACKET' if not dropped_packet_label_added else "")
        dropped_packet_label_added = True
    
    # Check for "NO PREV PACKET" in the last total latency column and plot a vertical line if found
    no_prev_indices = data[data[last_total_latency_col] == 'NO PREV PACKET'].index
    for idx in no_prev_indices:
        plt.axvline(x=timestamps[idx], color='g', linestyle='--', linewidth=1, alpha=0.1, label='NO PREV PACKET' if not no_prev_packet_label_added else "")
        no_prev_packet_label_added = True

    # Find where the condition is met
    consecutive = data[last_total_latency_col].eq("DROPPED PACKET").rolling(window=5).sum() == 5

    # Get the first index where this is True
    first_occurrence = consecutive.idxmax() if consecutive.any() else None

    plt.title('End to End Latency')
    plt.xlabel('Index')
    if first_occurrence != None:
        plt.gca().set_xlim(right=first_occurrence)
    plt.ylabel('Latency (ms)')
    plt.gca().set_ylim(bottom=0)
    plt.legend()
    plt.grid(True)
    last_total_plot_path = os.path.join(results_base_dir, f'{base_name}_last_total_latency_plot.png')
    plt.savefig(last_total_plot_path)
    plt.close()

    ################# 
    # Plot total histograms
    ################# 
    last_total_latency_data.hist(bins=50, figsize=(20, 8))
    plt.title('End to End Latency Histogram')
    hist_plot_path = f'{file_path}_histograms.png'
    plt.savefig(hist_plot_path)
    plt.close()


def clean_column_name(column_name):


    if "pcap_in_total_latency" in column_name:
        return "Total Latency"
    elif "pcap_in" in column_name:
        return "SDO to UDP Conversion"
    elif "sdo_transmit" in column_name:
        return "SDO Transmit Latency"
    elif "sdo_commit" in column_name:
        return "UDP to SDO Conversion"
    else:
        return column_name
    

#################### SELECT SOURCE VEHICLE ####################

sit1_dt_vehicles = [
        {
            "tena_host_id"       : "CARMA-TFHRC-LIVE",
            "host_static_id":   "CARMA-TFHRC-LIVE", #CARMA-TFHRC-LIVE",
            "bsm_id"        : "f03ad610",
            "platoon_order" : 1, # this can be used for identifying what fields to look at in platoon sdos
            "lvc_designation" : "live",
            "traffic_control_ip_address"    : "172.30.1.146",
        },
        {
            "tena_host_id"       : "CARMA-TFHRC",
            "host_static_id":   "CARMA-TFHRC",
            "bsm_id"        : "f03ad608",
            "lvc_designation" : "constructive",
            "traffic_control_ip_address"    : None,
            
        },
        {
            "tena_host_id"       : "CARMA-SPR",
            "host_static_id":   "CARMA-SPR",
            "bsm_id"        : "f03ad612",
            "lvc_designation" : "constructive",
            "traffic_control_ip_address"    : None,
        },
        {
            "tena_host_id"       : "CARMA-AUG",
            "host_static_id":   "CARMA-AUG",
            "bsm_id"        : "f03ad614",
            "platoon_order" : 2,
            "lvc_designation" : "constructive",
            "traffic_control_ip_address"    : "172.31.3.100",
        },
        {
            "tena_host_id"       : "CARMA-MITRE",
            "host_static_id":   "CARMA-MITRE",
            "bsm_id"        : "f03ad616",
            "platoon_order" : 3,
            "lvc_designation" : "constructive",
            "traffic_control_ip_address"    : "172.30.4.10",
        },
        {
            "tena_host_id"       : "CARLA-MANUAL-1",
            "host_static_id":   "CARLA-MANUAL-1",
            "bsm_id"        : "f03ad618",
            "platoon_order" : 4,
            "lvc_designation" : "virtual",
            "traffic_control_ip_address"    : None,
            
        },
    ]

pilot1_dt_participants = [
        {
            "tena_host_id"       : "TFHRC_CAR_2",
            "host_static_id":   "TFHRC_CAR_2",
            "bsm_id"        : "f03ad614",
            "lvc_designation" : "constructive",
            "traffic_control_ip_address"    : None,
            
        },
        {
            "tena_host_id"       : "UCLA-OPENCDA",
            "host_static_id":   "UCLA-OPENCDA",
            "bsm_id"        : "f03ad612",
            "lvc_designation" : "constructive",
            "traffic_control_ip_address"    : None,
        },
        {
            "tena_host_id"       : "NISSAN-SVM",
            "host_static_id":   "NISSAN-SVM",
            "bsm_id"        : "f03ad614",
            "lvc_designation" : "constructive",
            "traffic_control_ip_address"    : None,
        },
    ]

dt_vehicles = pilot1_dt_participants

def select_vehicle_user_input():

    print("\nWhat is the source vehicle? [#]\n")
    for vehicle_i,vehicle in enumerate(dt_vehicles):
        print("\n[" + str(vehicle_i + 1) + "] \tHOST ID: " + vehicle["host_static_id"] + " \n\tTENA ID: " + vehicle["tena_host_id"] + " \n\tBSM ID: " + vehicle["bsm_id"])

    vehicle_index = input("\n    --> ")

    try:
        selected_vehicle = dt_vehicles[int(vehicle_index) -1]      
        return selected_vehicle

    except:
        print("[!!!] Invalid selection, try again")
        sys.exit()

#################### SELECT MESSAGE TYPE ####################

def select_message_type_user_input():

    print("\nWhat data type would you like to analyze? [#]\n")
    for type_i,message_type in enumerate(J2735_message_types):
        print("[" + str(type_i + 1) + "] " + message_type)

    J2735_message_type_index = input("\n    --> ")

    try:
        J2735_message_type_name = J2735_message_types[int(J2735_message_type_index) -1]
        J2735_message_type_name = re.sub(" ","_",J2735_message_type_name)
        return J2735_message_type_name
    except:
        print("[!!!] Invalid selection, try again")

############################## DEFINE GENERAL VARIABLES ##############################

# example schema for all_data
# all_data = [
#     {
#         "dataset_name"                    : "some_dataset_name",
#         "data_order"                      : 1,
#         "original_data_list"              : [ {},{},{},{}... ],
#         "filtered_data_list"              : [ {},{},{},{}...  ],
#         "dataset_type"                    : "pcap" or "tdcs"
#         "dataset_params"                  : {},
#         "found_packet_matching_search"    : bool,
#         "starting_dataset_index"          : int of starting index in dataset to align with other datasets (NOT PACKET INDEX)
#         "dataset_index_column_name"       : packetIndex for pcap, rowID for tdcs,
#         "dataset_subtype"                 : SPAT or BSM or other - used for J2735 messages
#     },
#     {
#         "dataset_name"                    : "some_other_dataset_name",
#         "data_order"                      : 2,
#         "original_data_list"              : [ {},{},{},{}... ],
#         "filtered_data_list"              : [ {},{},{},{}...  ],
#         "dataset_type"                    : "pcap" or "tdcs"
#         "dataset_params"                  : {},
#         "found_packet_matching_search"    : bool,
#         "starting_dataset_index"          : int of starting index in dataset to align with other datasets (NOT PACKET INDEX)
#         "dataset_index_column_name"       : packetIndex for pcap, rowID for tdcs,
#         "dataset_subtype"                 : SPAT or BSM or other - used for J2735 messages
#     },
#     ...

# ]


# specifies the number of match_keys defined in the params for each data source
num_match_keys = 5

J2735_message_types = ["J2735","J3224","J2735-BSM","J2735-SPAT","J2735-MAP","LandVehicle","MAP","TrafficLight","BSM","Mobility_Request","Mobility_Response","Mobility_Path","Mobility_Operations-STATUS","Mobility_Operations-INFO","Traffic_Control_Request","Traffic_Control_Message", "V2XMessage", "TrafficSignalController"]

J2735_message_type_ids = {
    "BSM"   : "0014",
    "SPAT"  : "0013",
    "MAP"   : "0012"
}

# list of J2735 messages that become TENA Messages (as opposed to SDOs)
J2735_message_types_as_tena_message = ["Traffic_Control_Request","Traffic_Control_Message", "J2735","J3224","V2XMessage"]

desired_intersection_name = ""
desired_signal_id = "1628"

v2xhub_ip_address = "172.30.1.146"

all_data = []

############################## MAIN ##############################

argparser = argparse.ArgumentParser(
    description='VOICES Performance Calculation Script')
argparser.add_argument(
    '-l', '--log_level',
    metavar='<log_level>',
    type=str,
    dest='log_level',
    default="WARNING",
    help='set the logging level OPTIONS: [DEBUG,INFO,WARNING,ERROR,CRITICAL]')
argparser.add_argument(
    '-t', '--data-type',
    metavar='<data_type>',
    dest='data_type',
    type=str,
    default=None,
    help='Data type to be analyzed OPTIONS: [J2725,MAP,SPAT,BSM,LandVehicle,Mobility_Request,Mobility_Response,Mobility_Path,Mobility_Operations-STATUS,Mobility_Operations-INFO,Traffic_Control_Request,Traffic_Control_Message]')
argparser.add_argument(
    '-s', '--source_site',
    metavar='<source_site>',
    dest='source_site',
    type=str,
    default=None,
    help='Name of the source site in metadata')
argparser.add_argument(
    '-o', '--outfile',
    metavar='<outfile>',
    dest='outfile',
    type=str,
    default=None,
    help='name of the outfile (no special characters or spaces)')
argparser.add_argument(
    '-r', '--results_summary',
    metavar='<summary file prefix>',
    dest='results_summary_prefix',
    type=str,
    default=None,
    help='if used, includes results summary using given prefix')
argparser.add_argument(
    '-i', '--infile',
    metavar='<infile>',
    dest='infile',
    type=str,
    default=None,
    help='a csv input file that contains the datasets to load (columns: "dataset_name","dataset_file_location","dataset_type" ')
argparser.add_argument(
    '--plot_only',
    action='store_true',
    help='skip data analysis and only regenerate plots')
argparser.add_argument(
    '-m', '--metadata',
    metavar='<metadata file>',
    dest='metadata',
    type=str,
    default=None,
    help='metadata file containing site details and file locations')
args = argparser.parse_args()

log_level = getattr(logging, args.log_level)

logging.basicConfig(level=log_level,filename='performance_analysis.log', filemode='w', format='%(name)s:%(levelname)s:%(message)s')


print("\n==========================================================")
print("========== STARTING VOICES PERFORMANCE ANALYSIS ==========")
print("==========================================================\n")

# print("args: " + str(args))

print("Log Level: " + str(args.log_level))

logging.info("========== STARTING VOICES PERFORMANCE ANALYSIS ==========")



############################## SET CLOCK SKEWS ##############################

# live_to_nist_clock_skew = 0.060723
# virtual_to_nist_clock_skew = -0.051729

# live_to_virtual_clock_skew = live_to_nist_clock_skew - virtual_to_nist_clock_skew

# virt_to_v2x_clock_skew = -44.806000
# virt_to_second_clock_skew = -45.000999
# virt_to_third_clock_skew = -45.786999

# live_to_v2x_clock_skew = live_to_virtual_clock_skew + virt_to_v2x_clock_skew
# live_to_second_clock_skew = live_to_virtual_clock_skew + virt_to_second_clock_skew
# live_to_third_clock_skew = live_to_virtual_clock_skew + virt_to_third_clock_skew


############################## USER INPUT ##############################

if args.metadata:
    metadata_file_path = args.metadata
else:
    print("\nERROR: Please provide metadata file using the -m argument. See help (-h) for more details")
    sys.exit()

with open(metadata_file_path, 'r') as metadata_file:
    # Reading from json file
    metadata_site_list = json.load(metadata_file)

if args.data_type == None:
    J2735_message_type_name = select_message_type_user_input()
else:
    if not args.data_type in J2735_message_types:
        print("ERROR: selected message type " + args.data_type +  " is not valid, try again")
        print("\n\tValid Types: " + str(J2735_message_types) + "\n")
        sys.exit()

    J2735_message_type_name = str(args.data_type)

if "J2735-" in J2735_message_type_name:
    J2735_message_subtype_name = J2735_message_type_name.replace("J2735-","")
    J2735_message_type_name = "J2735"
else:
    J2735_message_subtype_name = None


print("Message Type: " + J2735_message_type_name + " selected")

if J2735_message_subtype_name:
    print("Message Sub-Type: " + J2735_message_subtype_name + " selected")

# we do not need to select a vehicle for spat
# we dont need this anymore, get data from metadata
# if False:
# 
# # if J2735_message_type_name != "TrafficLight" and J2735_message_type_name != "J2735":
#     if args.source_vehicle_index == None:
#         vehicle_info = select_vehicle_user_input()
#     else:
        
#         if args.source_vehicle_index > len(dt_vehicles):
#             print("ERROR: Source LandVehicle index out of bounds, try again")
#             print("\nValid Vehicles:")
#             for vehicle_i,vehicle in enumerate(dt_vehicles):
#                 print("\n[" + str(vehicle_i + 1) + "] \tHOST ID: " + vehicle["host_static_id"] + " \n\tTENA ID: " + vehicle["tena_host_id"] + " \n\tBSM ID: " + vehicle["bsm_id"])

#             sys.exit()
        
#         vehicle_info = dt_vehicles[args.source_vehicle_index - 1]
# else:
# but, we need values for the params, so we put one in as a placeholder...
# probably can do this better


source_vehicle_metadata_index = get_obj_by_key_value(metadata_site_list,"site_name",args.source_site)

if source_vehicle_metadata_index == None:
    print(f'\nERROR: Unable to find vehicle {args.source_site} in metadata')
    sys.exit()

source_vehicle_metadata = metadata_site_list[source_vehicle_metadata_index]


# {
#     "tena_host_id"       : "CARMA-TFHRC-LIVE",
#     "host_static_id":   "CARMA-TFHRC-LIVE", #CARMA-TFHRC-LIVE",
#     "bsm_id"        : "f03ad610",
#     "platoon_order" : 1, # this can be used for identifying what fields to look at in platoon sdos
#     "lvc_designation" : "live",
#     "traffic_control_ip_address"    : "172.30.1.146",
# },

# TODO: add bsm_id and host static ID and TENA identifier to metadata
# desired_bsm_id = source_vehicle_metadata["bsm_id"]
desired_bsm_id = ""
# desired_tena_identifier = source_vehicle_metadata["tena_host_id"]
desired_tena_identifier = source_vehicle_metadata["site_name"]
# desired_host_static_id = source_vehicle_metadata["host_static_id"]
desired_host_static_id = ""
# desired_traffic_control_ip_address = source_vehicle_metadata["traffic_control_ip_address"]
desired_traffic_control_ip_address = source_vehicle_metadata["ip_address"]

source_ip_address = source_vehicle_metadata["ip_address"]


# velocity is not set for constructive vehicles, so do not check it
if source_vehicle_metadata["lvc"] == "live":
    tdcs_bsm_velocity_field = "tspi.velocity.ltpENU_asTransmitted.vxInMetersPerSecond,Float32 (optional)"
    pcap_bsm_velocity_field = "speed(m/s)"
else:
    pcap_bsm_velocity_field = None
    tdcs_bsm_velocity_field = None

# there is an export issue with TDCS which needs to be fixed manully for platoon SDOs
# to fix, open in excel and find the column candidateVehicles^trajectoryStart.position.geocentric_asTransmitted.xInMeters,Float64 (1) (optional)
# find any columns with a value and insert one cell, pushing the entire row to the right (from that point to the right)
# insert a cell in the same way at the header
# delete the entire column created with no header
# select all cells and change format to Number
# remove two decimal places 
# save

# TODO: fix this with new metadata file? Probably dont need as we moved to J2735 messages 
if J2735_message_type_name == "Mobility_Operations-INFO" or J2735_message_type_name == "Mobility_Operations-STATUS":
    if source_vehicle_metadata["platoon_order"] == 1:
        mob_ops_tdcs_field = "downtrackDistanceInMeters,Float32"
        extract_tdcs_mobility_dtd = False
    elif source_vehicle_metadata["platoon_order"] == 2:
        mob_ops_tdcs_field = "joinedVehicles^strategyParameters,String (1)"
        extract_tdcs_mobility_dtd = True
    elif source_vehicle_metadata["platoon_order"] == 3:
        mob_ops_tdcs_field = "joinedVehicles^strategyParameters,String (2)"
        extract_tdcs_mobility_dtd = True
else:
    mob_ops_tdcs_field = None
    extract_tdcs_mobility_dtd = None
    

print("Source Vehicle: " + desired_tena_identifier + "(" + desired_bsm_id +  ") selected")



############################## SET DATA PARAMS ##############################

data_params = {
    "pcap_params" :{
        "BSM" : {
            "skip_if_neqs"      : [
                {
                    "key"           : "bsm id",         # key(column) to check
                    "value"         : desired_bsm_id,   # value to check
                    "round"         : False,            # round the value before checking (important for TENA data)
                # "round_decimals": 0,                # decimal places to round to (only needed if round == True, shown here for example)
                    "start_only"    : False,            # only skip through rows matching this condition to align the start of the data set 
                                                        #    had to add this becuase we want to use speed == 0 to find the start of the data (when the vehicle starts moving)
                                                        #    but we do not want to throw out any values which contain speed == 0 (vehicle stops during run)
                }

            ],
            
            "skip_if_eqs"       : [
                {
                    "key"    : "speed(m/s)",
                    "value"  : "0.0",
                    "round" : True,
                    "round_decimals": 2,
                    "start_only" : True, 
                }
            ],

            "match_keys"        : [
                {
                    "key"       : "latitude",
                    "round"     : True,
                    "round_decimals": 6,
                    "buffer"    : 0.000002,
                },
                {
                    "key"       : "longitude",
                    "round"     : True,
                    "round_decimals": 6,
                    "buffer"    : 0.000002,
                },
                {
                    "key"       : "secMark",
                },
                {
                    "key"       : pcap_bsm_velocity_field,
                    "round"     : True,
                    "round_decimals": 2,
                    "buffer"    : 0.03,
                },
                {
                    "key"       : None,
                }
            ]
        },
        "LandVehicle" : {
            "skip_if_neqs"      : [
                {
                }

            ],
            
            "skip_if_eqs"       : [
                {
                }
            ],

            "match_keys"        : [
                {
                    "key"       : "latitude",
                    "round"     : True,
                    "round_decimals": 6,
                    "buffer"    : 0.000002,
                },
                {
                    "key"       : "longitude",
                    "round"     : True,
                    "round_decimals": 6,
                    "buffer"    : 0.000002,
                },
                {
                    "key"       : "const^identifier,String",
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },

            ]
        },
        "TrafficLight" : { # actually decoded spat
            "skip_if_neqs"      : [
                {
                    "key"           : "intersectionName",
                    "value"         : desired_intersection_name,  
                                                       
                },
            ],
            
            "skip_if_eqs"       : [
                {
                    "key"           : "phase2_eventState",
                    "value"         : "permissive-Movement-Allowed",  # only way to align the data is to skip until a value changes
                    "start_only"    : True                         
                },
            ],

            "match_keys"        : [
                {
                    "key"       : "phase2_eventState",
                    "spat_state": True,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                }
            ]
        },
        "Mobility_Path" : {
            "skip_if_neqs"      : [
                {
                    "key"           : "hostStaticId",
                    "value"         : desired_host_static_id,  
                                                       
                },
                {
                    "key"           : "hostBSMId",      
                    "value"         : desired_bsm_id, 
                }

            ],
            
            "skip_if_eqs"       : [
               
            ],

            "match_keys"        : [
                {
                    "key"       : "hostStaticId",
                },
                {
                    "key"       : "hostBSMId",
                },
                {
                    "key"       : "planId",
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                }
            ]
        },
        "Mobility_Operations-STATUS" : {
            "skip_if_neqs"      : [
                {
                    "key"           : "hostStaticId",
                    "value"         : desired_host_static_id,             
                },
                {
                    "key"           : "headerTimestamp",
                    "value"         : None,
                    "mobility_timestamp_check" : True,                        
                },
            ],
            
            "skip_if_eqs"       : [
                { # excluding info messages because they are sent at the same time, 
                  # and sometimes tena plugins load them in a different order than the pcap
                    "key"           : "operationParams",
                    "value"         : "INFO",
                    "starts_with"   : True  
                                                       
                },
            ],

            "match_keys"        : [
                {
                    "key"       : "headerTimestamp",
                    "multiply_by"  : 1000000,
                },
                {
                    "key"       : "operationParams",
                    "extract_mobility_dtd" : True,
                    "round"     : True,
                    "round_decimals" : 3,
                    "buffer"    : 0.002,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                }
            ]
        },
        "Mobility_Operations-INFO" : {
            "skip_if_neqs"      : [
                {
                    "key"           : "hostStaticId",
                    "value"         : desired_host_static_id,                              
                },
            ],
            
            "skip_if_eqs"       : [
                { # excluding status messages because they are sent at the same time, 
                  # and sometimes tena plugins load them in a different order than the pcap
                    "key"           : "operationParams",
                    "value"         : "STATUS",
                    "starts_with"   : True  
                                                       
                },
            ],

            "match_keys"        : [
                {
                    "key"       : "headerTimestamp",
                    "multiply_by"  : 1000000,
                },
                {
                    "key"       : "operationParams",
                    "extract_mobility_dtd" : True,
                    "round"     : True,
                    "round_decimals" : 3,
                    "buffer"    : 0.002,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                }
            ]
        },
        "Mobility_Request" : {
            "skip_if_neqs"      : [
                {
                    "key"           : "hostStaticId",
                    "value"         : desired_host_static_id,  
                                                       
                },
            ],
            
            "skip_if_eqs"       : [
            ],

            "match_keys"        : [
                {
                    "key"       : "headerTimestamp",
                    "multiply_by"  : 1000000,
                    # "buffer"    : 100000000,
                },
                {
                    "key"       : "strategyParams",
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                }
            ]
        },
        "Mobility_Response" : {
            "skip_if_neqs"      : [
                {
                    "key"           : "hostStaticId",
                    "value"         : desired_host_static_id,  
                                                       
                },
            ],
            
            "skip_if_eqs"       : [
            ],

            "match_keys"        : [
                {
                    "key"       : "headerTimestamp",
                    "multiply_by"  : 1000000,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                }
            ]
        },
        "Traffic_Control_Request" : {
            "skip_if_neqs"      : [
                {
                    "key"           : "reqid_hex",
                    "value"         : None,
                    "reqid_check"   : True,  
                                                       
                },
            ],
            
            "skip_if_eqs"       : [
            ],

            "match_keys"        : [
                {
                    "key"       : "reqid_hex",
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                }
            ]
        },
        "J2735" : {
            "skip_if_neqs"      : [
            ],
            
            "skip_if_eqs"       : [
            ],

            "match_keys"        : [
                {
                    "key"       : "hex_payload",
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                }
            ]
        },
        "J3224" : {
            "skip_if_neqs"      : [
            ],
            
            "skip_if_eqs"       : [
            ],

            "match_keys"        : [
                {
                    "key"       : "hex_payload",
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                }
            ]
        },
    },
    
    "tdcs_params" : {
        "BSM" : {
            "skip_if_neqs"      : [
                # {
                #     "key"           : "const^identifier,String",
                #     "value"         : desired_tena_identifier,
                # }

            ],
            
            "skip_if_eqs"       : [
                {
                    "key"   : "Metadata,Enum,Middleware::EventType",
                    "value" : "Discovery",
                },
                {
                    "key"   : "Metadata,Enum,Middleware::EventType",
                    "value" : "Destruction",
                },
            ],

            "match_keys"        : [
                {
                    "key"       : "tspi.position.geodetic_asTransmitted.latitudeInDegrees,Float64 (optional)",
                    "round"     : True,
                    "round_decimals": 6,
                    "buffer"    : 0.000002,
                },
                {
                    "key"       : "tspi.position.geodetic_asTransmitted.longitudeInDegrees,Float64 (optional)",
                    "round"     : True,
                    "round_decimals": 6,
                    "buffer"    : 0.000002,
                },
                {
                    "key"       : "msWithinMinute,UInt16",
                },
                # {
                #     # velocity is not set in TDCS for constructive BSMs 
                #     "key"       : tdcs_bsm_velocity_field,
                #     "round"     : True,
                #     "round_decimals": 2,
                #     "buffer"    : 0.03,
                # },
                {
                    "key"       : None,
                },
                
                {
                    "key"       : None,
                }
            ]
        },
        "V2XMessage" : {
            "skip_if_neqs" : [
                {
                    "key" : "Metadata,Endpoint",
                    "value" : source_ip_address,
                }
            ],
            "skip_if_eqs" : [
                
            ],
            "match_keys" : [
                {
                    "key" : "Metadata,MessageCount",
                },
                {
                    "key" : "senderIdentifier,String",
                },
                {
                    "key" : "uuid,String"
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
            ]
        },
        "LandVehicle" : {
            "skip_if_neqs"      : [
                {
                    "key"   : "const^Metadata,SDOid.hostIPaddress",
                    "value" : source_ip_address,
                },
            ],
            
            "skip_if_eqs"       : [
                {
                    "key"   : "Metadata,Enum,Middleware::EventType",
                    "value" : "Discovery",
                },
                {
                    "key"   : "Metadata,Enum,Middleware::EventType",
                    "value" : "Destruction",
                },
                
            ],

            "match_keys"        : [
                # {
                #     "key"       : "tspi.position.geodetic_asTransmitted.latitudeInDegrees,Float64 (optional)",
                #     "round"     : True,
                #     "round_decimals": 6,
                #     "buffer"    : 0.000002,
                # },
                # {
                #     "key"       : "tspi.position.geodetic_asTransmitted.longitudeInDegrees,Float64 (optional)",
                #     "round"     : True,
                #     "round_decimals": 6,
                #     "buffer"    : 0.000002,
                # },
                {
                    "key"       : "const^identifier,String",
                },
                {
                    "key"       : "Metadata,StateVersion",
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
            ]
        },
        "TrafficSignalController" : {
            "skip_if_neqs" : [
                {
                    "key" : "const^Metadata,SDOid.hostIPaddress",
                    "value": source_ip_address,
                }
            ],
            "skip_if_eqs" : [
                {
                    "key"   : "Metadata,Enum,Middleware::EventType",
                    "value" : "Discovery",
                },
                {
                    "key"   : "Metadata,Enum,Middleware::EventType",
                    "value" : "Destruction",
                },
            ],
            "match_keys" : [
                {
                    "key" : "Metadata,StateVersion",
                },
                {
                    "key" : "const^identifier,String",
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
            ]
        },
        "TrafficLight" : {
            "skip_if_neqs"      : [
                # {
                #     "key"           : "const^signalID,String",
                #     "value"         : desired_signal_id,
                # }

            ],
            
            "skip_if_eqs"       : [
                {
                    "key"   : "Metadata,Enum,Middleware::EventType",
                    "value" : "Discovery",
                },
            ],

            "match_keys"        : [
                {
                    "key"       : "Enum,VUG::Entities::Signals::TrafficLightState,currentState",
                    "spat_state": True,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                
                {
                    "key"       : None,
                }
            ]
        },
        "Mobility_Path" : {
            "skip_if_neqs"      : [
                {
                    "key"           : "header.hostBSMId,String",
                    "value"         : desired_bsm_id,
                }

            ],

            "skip_if_eqs"       : [
                {
                    "key"   : "Metadata,Enum,Middleware::EventType",
                    "value" : "Discovery",
                },
                {
                    "key"   : "Metadata,Enum,Middleware::EventType",
                    "value" : "Destruction",
                },
            ],

            "match_keys"        : [
                {
                    "key"       : "header.hostStaticId,String",
                },
                {
                    "key"       : "header.hostBSMId,String",
                },
                {
                    "key"       : "header.planId,String",
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                }
            ]
        },
        "Mobility_Operations-STATUS" : {
            "skip_if_neqs"      : [
                # {
                #     "key"           : "const^hostStaticId,String",
                #     "value"         : desired_host_static_id,
                # },
                {
                    "key"           : "urgency,Int32 (optional)",
                    "value"         : "<UNSET>",
                },
                # {
                #     "key"           : "Vector,requestedVehicles,count",
                #     "value"         : "0",
                # },
                {
                    "key"           : "timestamp.nanosecondsSince1970,Int64",
                    "value"         : None,
                    "mobility_timestamp_check" : True,                        
                },

            ],

            "skip_if_eqs"       : [
                {
                    "key"   : "Metadata,Enum,Middleware::EventType",
                    "value" : "Discovery",
                },
                {
                    "key"   : "Metadata,Enum,Middleware::EventType",
                    "value" : "Destruction",
                },
                { # excluding info messages because they are sent at the same time, 
                  # and sometimes tena plugins load them in a different order than the pcap
                    "key"   : "commandSpeedInMetersPerSecond,Float32 (optional)",
                    "value" : "<UNSET>",
                },
            ],

            "match_keys"        : [
                {
                    "key"       : "timestamp.nanosecondsSince1970,Int64",
                    "multiply_by" : 1,
                },
                {
                    "key"       : mob_ops_tdcs_field,
                    "extract_mobility_dtd" : extract_tdcs_mobility_dtd,
                    "round"     : True,
                    "round_decimals" : 3,
                    "buffer"    : 0.002,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                }
            ]
        },
        "Mobility_Operations-INFO" : {
            "skip_if_neqs"      : [
                # {
                #     "key"           : "const^hostStaticId,String",
                #     "value"         : desired_host_static_id,
                # },
                {
                    "key"           : "urgency,Int32 (optional)",
                    "value"         : "<UNSET>",
                },
                # {
                #     "key"           : "Vector,requestedVehicles,count",
                #     "value"         : "0",
                # },
                {
                    "key"           : "timestamp.nanosecondsSince1970,Int64",
                    "value"         : None,
                    "mobility_timestamp_check" : True,
                                                       
                },
                { # excluding status messages because they are sent at the same time, 
                  # and sometimes tena plugins load them in a different order than the pcap
                    "key"   : "commandSpeedInMetersPerSecond,Float32 (optional)",
                    "value" : "<UNSET>",
                },

            ],

            "skip_if_eqs"       : [
                {
                    "key"   : "Metadata,Enum,Middleware::EventType",
                    "value" : "Discovery",
                },
                {
                    "key"   : "Metadata,Enum,Middleware::EventType",
                    "value" : "Destruction",
                },
                
            ],

            "match_keys"        : [
                {
                    "key"       : "timestamp.nanosecondsSince1970,Int64",
                    "multiply_by" : 1,
                },
                {
                    "key"       : "downtrackDistanceInMeters,Float32",
                    "round"     : True,
                    "round_decimals" : 3,
                    "buffer"    : 0.002,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                }
            ]
        },
        "Mobility_Request" : {
            "skip_if_neqs"      : [
                {
                    "key"           : "timestamp.nanosecondsSince1970,Int64",
                    "value"         : None,
                    "mobility_timestamp_check" : True,
                                                       
                },
                { 
                    "key"   : "commandSpeedInMetersPerSecond,Float32 (optional)",
                    "value" : "<UNSET>",
                },

            ],

            "skip_if_eqs"       : [
                {
                    "key"   : "Metadata,Enum,Middleware::EventType",
                    "value" : "Discovery",
                },
                {
                    "key"   : "Metadata,Enum,Middleware::EventType",
                    "value" : "Destruction",
                },
                
            ],

            "match_keys"        : [
                {
                    "key"       : "timestamp.nanosecondsSince1970,Int64",
                    "multiply_by" : 1,
                },
                {
                    "key"       : "requestedVehicles^strategyParameters,String (1)",
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                }
            ]
        },
        "Mobility_Response" : {
            "skip_if_neqs"      : [
                {
                    "key"           : "urgency,Int32 (optional)",
                    "value"         : "0",
                },
                {
                    "key"           : "timestamp.nanosecondsSince1970,Int64",
                    "value"         : None,
                    "mobility_timestamp_check" : True,
                                                       
                },
                { 
                    "key"   : "commandSpeedInMetersPerSecond,Float32 (optional)",
                    "value" : "<UNSET>",
                },

            ],

            "skip_if_eqs"       : [
                {
                    "key"   : "Metadata,Enum,Middleware::EventType",
                    "value" : "Discovery",
                },
                {
                    "key"   : "Metadata,Enum,Middleware::EventType",
                    "value" : "Destruction",
                },
                
            ],

            "match_keys"        : [
                {
                    "key"       : "timestamp.nanosecondsSince1970,Int64",
                    "multiply_by" : 1,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                }
            ]
        },
        "Traffic_Control_Request" : {
            "skip_if_neqs"      : [
                {
                    "key"           : "Metadata,SenderId.hostIPaddress",
                    "value"         : desired_traffic_control_ip_address,
                    "use_v2xhub_ip_for_tcm"  : True,
                },
                {
                    "key"           : "requestID,String",
                    "value"         : None,
                    "reqid_check"   : True,  
                                                       
                },
            ],

            "skip_if_eqs"       : [                
            ],

            "match_keys"        : [
                {
                    "key"       : "requestID,String",
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                }
            ]
        },
        "J2735" : {
            "skip_if_neqs"      : [
                {
                    "key"           : "Metadata,Endpoint",
                    "value"         : None,
                },
            ],
            
            "skip_if_eqs"       : [
            ],

            "match_keys"        : [
                {
                    "key"       : "binaryContent^UInt8",
                    "j2735_vector": True, # !!!! - there is a big assumption in here that J2735 SPaT are less than 255 hex bytes
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                }
            ]
        },
        "J3224" : {
            "skip_if_neqs"      : [
                {
                    "key"           : "Metadata,Endpoint",
                    "value"         : None,
                },
            ],
            
            "skip_if_eqs"       : [
            ],

            "match_keys"        : [
                {
                    "key"       : "binaryContent^UInt8",
                    "j2735_vector": True,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                },
                {
                    "key"       : None,
                }
            ]
        },
    }
}

############################## LOAD DATA ##############################

if not args.plot_only:
    print("\nTotal Packets:")

    if args.infile == None:
        load_data_user_input()
    else:
        load_data_from_csv(args.infile)

############################## MAIN ##############################

# we need to get all datasets to align to calculate performance
# this is accomplished by taking the first compliant packet (passes all EQ and NEQ) in the source data and looking for it in all other datasets
# once we find the compliant packet in the other datasets, we can start the comparison from there for all future packets
# if the source packet is not found in one of the datasets (dropped packet or something), we need to try the next packet in the source dataset
# to keep data aligned across all sets, we simply remove that packet from all data sources that have it

if not args.plot_only:
    if len(all_data) == 0:
        print("\nNo datasets loaded, exiting")
        sys.exit()

    source_data_obj_index = get_obj_by_key_value(all_data,"data_order",1)
    source_data_obj = all_data[source_data_obj_index]
    source_data_list_original = source_data_obj["original_data_list"]
    source_data_list_filtered = source_data_obj["filtered_data_list"]

    source_packet_params = source_data_obj["dataset_params"]

    all_datasets_have_offset = False

    packets_to_skip = 0
    max_packets_to_skip = 30

    source_reqid_list = []


    for dataset_to_filter in all_data:
        filter_dataset(dataset_to_filter)

    all_filtered_datasets_contain_data = True

    print("\nFiltered Packet Totals:")
    for dataset in all_data:
        
        dataset_len = len(dataset["filtered_data_list"])
        print("\t" + dataset["dataset_name"] + ": " + str(dataset_len))

        if dataset_len == 0: 
            all_filtered_datasets_contain_data = False

    if all_filtered_datasets_contain_data == False:
        print("\nERROR: One or more filtered datasets does not contain any data")
        sys.exit()


    # print("\nFilter to first unique Totals:")
    # for dataset_to_find_unique in all_data:
    #     find_first_unique_packet(dataset_to_find_unique)


    # loop through the first 30 packets of the source 
    # while all_datasets_have_offset == False and packets_to_skip <= max_packets_to_skip:
    logging.info("---------- FINDING FIRST PACKET FOR ALL DATASETS ----------")
    # logging.info("  --> Skipping first " + str(packets_to_skip) + " source packets")

    # iterate through all datasets and filter the dataset starting at the matched packet
    for source_dataset in all_data:

        all_datasets_have_offset = True
        
        for dataset_to_search in all_data:
            
            # dont align a dataset with itself
            if source_dataset["dataset_name"] == dataset_to_search["dataset_name"]:
                source_dataset ["starting_dataset_index"] = 0
                continue

            align_dataset(source_dataset,dataset_to_search)
            
            # if we go through the whole source_dataset and we haven't found the matching packet,
            # break to continue to the next source packet
            if not dataset_to_search["found_packet_matching_search"]:
                logging.debug("Could not find offset in: " + dataset_to_search["dataset_name"] )
                all_datasets_have_offset = False
                break

        

        # if all datasets found a packet matching the source packet, break to stop looking
        if all_datasets_have_offset == True:
            logging.info("All datasets found source offset:")

            for dataset in all_data:
                logging.info("  " + dataset["dataset_name"] + ": " + str(dataset["starting_dataset_index"]))

            break
        else:
            # if one of the datasets did not find the matching source packet:
            # clear filtered data, reset found_packet_matching_search, and increase the packets to skip
            logging.debug("Some datasets could not find source offset, moving to next source dataset")
            for dataset in all_data:
                dataset["found_packet_matching_search"] = False
                dataset["starting_dataset_index"] = None

            # packets_to_skip += 1
            
            # if packets_to_skip == max_packets_to_skip:
            #     logging.debug("None of the first 30 packets in the source data could be found in all subsiquent datasets, exiting")
            #     print("\nNone of the first 30 packets in the source data could be found in all subsiquent datasets, exiting")
            #     sys.exit()
            
    if all_datasets_have_offset == False:
        print("\nUnable to find the first packet of any of the datasets in all other datasets, unable to align data")
        logging.error("Unable to find the first packet of any of the datasets in all other datasets, unable to align data")
        sys.exit()

    for dataset in all_data:
        dataset["filtered_data_list"] = dataset["filtered_data_list"][dataset["starting_dataset_index"]:]


    check_for_dropped_packets()

############################## INITIALIZE CSV WRITER ##############################

if args.outfile == None:
    outfile = "performance_analysis.csv"
else:
    outfile = str(clean_name(args.outfile))

results_base_dir = "results/" + args.results_summary_prefix + "_results" 

results_filename = results_base_dir + "/" + outfile + ".csv"

if not args.plot_only:
    try:
        os.makedirs(results_base_dir)
    except:
        pass

    results_outfile_obj = open(results_filename,'w',newline='')
    results_outfile_writer = csv.writer(results_outfile_obj)

    calculate_performance_metrics()

    results_outfile_obj.close()

    performance_post_processing(results_base_dir + "/" + outfile + ".csv")


plot_latency(results_filename,results_base_dir)




print("\n----- ANALYSIS COMPLETE -----")
sys.exit()
