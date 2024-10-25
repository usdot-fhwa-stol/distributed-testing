import json
import re
import argparse
import os

id_ip_found_map_e2 = {}
ip_map_event2 = {
    "10.91.0.35" : "UCLA",
    "10.91.0.4" : "MCITY",
    "10.91.0.3" : "FHWA",
    "10.91.0.163" : "ORNL",
    "10.91.0.164" : "ANL",
    "10.91.0.2" : "AWS TDCS",
    "10.91.0.34" : "AWS JSON Streamer",
    "unknown" : "FHWA",

}

id_ip_found_map_e1 = {
    "11" : "10.0.0.170",
    "13" : "10.0.0.170",
    "14" : "192.168.201.33",
    "15" : "192.168.201.33",
}

ip_map_event1 = {
    "192.168.201.33" : "VW",
    "10.0.0.170" : "TTS",
    "192.168.1.90" : "FHWA",
    "141.211.55.146" : "MCITY",
    "192.168.201.33" : "?",
    # "unknown" : "FHWA",

}

id_ip_found_map_e0 = {
    
}

ip_map_event0 = {
    "192.168.2.6" : "UCLA",
    "141.211.55.146" : "MCITY",
    "192.168.1.90" : "FHWA",
    "10.7.108.132" : "ORNL",
    "192.168.26.101" : "ANL",
    "192.168.201.33" : "VW",
    "10.0.0.170" : "TTS",
    "10.40.36.12" : "Econ",
    # "" : "AWS TDCS",
    # "" : "AWS JSON Streamer",
    # "unknown" : "FHWA",

}

id_ip_found_map = id_ip_found_map_e2
ip_map = ip_map_event2

def repair_current_entry(repaired_entry):

    if repaired_entry["IP address"] == "unknown":
        # print(f'Entry name unknown')
        if repaired_entry["ID"] in id_ip_found_map:
            print(f'updated entry IP for: {repaired_entry["ID"]} - {id_ip_found_map[repaired_entry["ID"]]}')
            repaired_entry['IP address'] = id_ip_found_map[repaired_entry["ID"]]
        else:
            for ping_result in repaired_entry['ping_results']:
                if ping_result['Round trip latency (ms)'] == None:
                    continue
                # if the result is less than 10 ms, we know it is a local application so it has the same IP
                # the IP of the result must be known or there is nothing to match
                if ping_result['Round trip latency (ms)'] < 10 and ping_result['IP address'] != "unknown":
                    print(f'entry - Latency is less than 10ms, must be same IP')
                    repaired_entry['IP address'] = ping_result['IP address']
                    print(f'Adding ID IP entry for: {repaired_entry["ID"]} : {ping_result["IP address"]}')
                    id_ip_found_map[repaired_entry["ID"]] = ping_result['IP address']

    
    for i_pr,ping_result in enumerate(repaired_entry['ping_results']):
        if ping_result['Round trip latency (ms)'] == None:
            continue

        if ping_result['IP address'] == "unknown":
            # print(f'Found unknown IP')
            # print(f'ping_result["ID"]: {ping_result["ID"]} --- id_ip_found_map: {id_ip_found_map}')
            if ping_result["ID"] in id_ip_found_map:
                print(f'Updated IP for known ID: {ping_result["ID"]} - {id_ip_found_map[ping_result["ID"]]}')
                repaired_entry['ping_results'][i_pr]["IP address"] = id_ip_found_map[ping_result["ID"]]
            else:
                # if the result is less than 10 ms, we know it is a local application so it has the same IP
                # the IP of the entry must be known or there is nothing to match
                if ping_result['Round trip latency (ms)'] < 10 and repaired_entry['IP address'] != "unknown":
                    print(f'result - Latency is less than 10ms, must be same IP')
                    ping_result['IP address'] = repaired_entry['IP address']
                    print(f'Adding ID IP entry for: {ping_result["ID"]} : {repaired_entry["IP address"]}')
                    id_ip_found_map[ping_result["ID"]] = repaired_entry['IP address']

    return repaired_entry
                



def convert_to_ms(time_str):
    if time_str.endswith('ms'):
        return float(time_str[:-2])
    elif time_str.endswith('s'):
        return float(time_str[:-1]) * 1000
    return float(time_str)

def parse_ping_data(data):
    result = []
    current_entry = None
    
    for line in data.splitlines():
        if line.strip() == "":
            continue
        
        if line.startswith("  "):
            # Process ping result line
            if current_entry:
                ping_result = {}
                parts = line.strip().split(": ")
                
                # Ensure the parts list has the expected number of elements
                if len(parts) < 2:
                    continue
                
                # Extract latency and clock skew
                latency_skew, details = parts[0], parts[1]

                ping_result['Result'] = parts[-1].replace("- ","")
                if ping_result['Result'] != "Success":
                    ping_result['Round trip latency (ms)'] = None
                    ping_result['Clock skew (ms)'] = None
                    ping_result['Clock skew margin (ms)'] = None
                else:
                    latency_skew_parts = latency_skew.split(", ")
                    ping_result['Round trip latency (ms)'] = convert_to_ms(latency_skew_parts[0].split()[-1])
                    ping_result['Clock skew (ms)'] = convert_to_ms(latency_skew_parts[1].split()[2])
                    ping_result['Clock skew margin (ms)'] = convert_to_ms(latency_skew_parts[1].split()[-1])
                
                # check special case where latency, skew, and margin are all 0 indicating a bad result
                if ( 
                    ping_result['Round trip latency (ms)'] == 0 and 
                    ping_result['Clock skew (ms)'] == 0 and 
                    ping_result['Clock skew margin (ms)'] == 0 
                ):
                    ping_result['Round trip latency (ms)'] = None
                    ping_result['Clock skew (ms)'] = None
                    ping_result['Clock skew margin (ms)'] = None

                # Extract application details
                app_details = details.split(", ")
                ping_result['Application name'] = app_details[0] if app_details[0] else "unknown"
                ping_result['ID'] = app_details[1].split()[-1]
                ping_result['IP address'] = app_details[2].split(":")[0].replace("{","") if 'unknown' not in app_details[2] else "unknown"
                
                
                current_entry['ping_results'].append(ping_result)
        else:
            # Process new entry line
            if current_entry:
                # print(json.dumps(current_entry, indent=4))
                # print(f'Found new entry, repairing and saving current')
                repaired_entry = repair_current_entry(current_entry)
                # print(json.dumps(repaired_entry, indent=4))
                result.append(repaired_entry)
            
            parts = line.split(": ")
            
            # Ensure the parts list has the expected number of elements
            if len(parts) < 2:
                continue
            
            entry_details, entry_result = parts[0], parts[1]
            entry_parts = entry_details.split(", ")
            current_entry = {
                'Application name': entry_parts[0] if entry_parts[0] else "unknown", 
                'ID': entry_parts[1].split()[-1],
                'IP address': entry_parts[2].split()[0][1:-1].split(":")[0] if 'unknown' not in entry_parts[2] else "unknown",
                'Result': entry_result,
                'ping_results': []
            }

            # print(f'current_entry: {current_entry}' )
    
    if current_entry:
        result.append(current_entry)
    
    return result

def generate_averages(parsed_data,args):
    
    input_file = args.input_file
    results_file_name = f"{os.path.splitext(input_file)[0]}_results.txt"
    results_file = open(results_file_name, "w")

    combined_data = {}

    app_ip_id_map = {}

    for entry in parsed_data:

        if entry["IP address"] not in app_ip_id_map:
            app_ip_id_map[entry["IP address"]] = [entry['ID']]
        else:
            if entry['ID'] not in app_ip_id_map[entry["IP address"]]:
                app_ip_id_map[entry["IP address"]].append(entry['ID'])

        for ping_result in entry['ping_results']:

            if ping_result['Round trip latency (ms)'] == None:
                continue

            if ping_result["IP address"] not in app_ip_id_map:
                app_ip_id_map[ping_result["IP address"]] = [ping_result['ID']]
            else:
                if ping_result['ID'] not in app_ip_id_map[ping_result["IP address"]]:
                    app_ip_id_map[ping_result["IP address"]].append(ping_result['ID'])

            if not entry["IP address"] in combined_data:
                print("Adding new source: " + entry["IP address"])
                combined_data[entry["IP address"]] = {}
                combined_data[entry["IP address"]][ping_result["IP address"]] = [ping_result["Round trip latency (ms)"]] 
            else:
                # print("Source data: " + str(combined_data[entry["IP address"]]))
                # print("Dest IP: " + ping_result["IP address"])
                if not ping_result["IP address"] in combined_data[entry["IP address"]]:
                    print("  Adding new dest (" + ping_result["IP address"] + ") to source: " + entry["IP address"] )
                    combined_data[entry["IP address"]][ping_result["IP address"]] =  [ping_result["Round trip latency (ms)"]]
                else:
                    # print("  Appending new value to from dest (" + ping_result["IP address"] + ") to source: " + entry["IP address"] )
                    combined_data[entry["IP address"]][ping_result["IP address"]].append(ping_result["Round trip latency (ms)"])
    
    for source_app in combined_data:
        if source_app in ip_map:
            results_file.write("\nSource: " + ip_map[source_app] + "\n")
        else:
            results_file.write("\nSource: " + source_app + "\n")
        for dest_app in combined_data[source_app]:
            # print(str(combined_data[source_app][dest_app]))
            num_dest_app_datapoints = len(combined_data[source_app][dest_app])
            dest_app_latency_average = sum(combined_data[source_app][dest_app])/num_dest_app_datapoints
            
            ping_diff_list = []
            for ping_i,ping_value in enumerate(combined_data[source_app][dest_app]):
                if ping_i == 0:
                    continue
                
                ping_diff_list.append(abs(float(combined_data[source_app][dest_app][ping_i]) - float(combined_data[source_app][dest_app][ping_i -1])))
            
            
            # print(str(ping_diff_list))
            if len(ping_diff_list) > 0:
                dest_app_jitter = sum(ping_diff_list)/len(ping_diff_list)
            else:
                dest_app_jitter = "NA"
            
            if dest_app in ip_map:
                results_file.write("    Dest: " + ip_map[dest_app] + "\n")
            else:
                results_file.write("    Dest: " + dest_app + "\n")
            # print("    Dest: " + dest_app)
            results_file.write("        Pings: " + str(num_dest_app_datapoints) + "\n")
            results_file.write("        Round Trip Latency: " + str(dest_app_latency_average)  + " ms" + "\n")
            results_file.write("        One Way Latency: " + str(dest_app_latency_average/2)  + " ms" + "\n")
            results_file.write("        Jitter: " + str(dest_app_jitter)  + " ms" + "\n")

    print(f'app_ip_id_map: \n {app_ip_id_map}')
    seen_values = []
    for ip in app_ip_id_map:
        for id in app_ip_id_map[ip]:
            if id in seen_values:
                print(f'ID {id} found in multiple IPs')
            seen_values.append(id)

def main():
    parser = argparse.ArgumentParser(description="Parse ping data and output JSON.")
    parser.add_argument('input_file', help="Input file containing ping data")
    args = parser.parse_args()
    
    input_file = args.input_file
    output_file = f"{os.path.splitext(input_file)[0]}_parse_data.json"
    
    with open(input_file, 'r') as f:
        data = f.read()
    
    parsed_data = parse_ping_data(data)

    # repair again with all information
    for i_e,entry in enumerate(parsed_data):
        parsed_data[i_e] = repair_current_entry(entry)

    generate_averages(parsed_data,args)


    with open(output_file, 'w') as f:
        json.dump(parsed_data, f, indent=4)
    
    print(f"Parsed data has been written to {output_file}")

if __name__ == "__main__":
    main()
