import sys
import re

ip_map = {
    "10.91.0.35" : "UCLA",
    "10.91.0.4" : "MCITY",
    "10.91.0.3" : "FHWA",
    "10.91.0.163" : "ORNL",
    "10.91.0.164" : "ANL",

}


infile = "run5-latency.txt"
infile_obj = open(infile,'r')

is_inside_desired_dataset = False

results_dataset = {}

num_failed_pings = 0

for line_i,line in enumerate(infile_obj):
    current_line = line.strip()
    # print(str(line_i) + " - " + current_line)
    source_ip_search = re.search("{(.*)}: Success",current_line)
        
    if(source_ip_search):
        source_ip_search_result = source_ip_search.group(1)
        # print("Found Source IP: " + source_ip_search_result)     
        source_ip_port_trimmed_search = re.sub(":(.*)","",source_ip_search_result)
    
        if (source_ip_port_trimmed_search):
            source_ip_port_trimmed_search_result = source_ip_port_trimmed_search
            # print("Trimmed Source IP: " + source_ip_port_trimmed_search_result)
        
        is_inside_desired_dataset = True
        continue
        
    
    if is_inside_desired_dataset == True :
        if current_line == "":
            # print("Found end of results group: ")
            is_inside_desired_dataset = False
            continue
        
        dest_ip_search = re.search("{(.*)}: - Success",current_line)
        
        if(dest_ip_search):
            dest_ip_search_result = dest_ip_search.group(1)
            # print("  Found Dest IP: " + dest_ip_search_result)
            dest_ip_port_trimmed_search = re.sub(":(.*)","",dest_ip_search_result)
    
            if (dest_ip_port_trimmed_search):
                dest_ip_port_trimmed_search_result = dest_ip_port_trimmed_search
                # print("Trimmed Dest IP: " + dest_ip_port_trimmed_search)
            else:
                print("FAILED TO TRIM IP: " + dest_ip_search_result)
                continue
                # sys.exit()
        else:
            if re.search("Ping failed.",current_line) or re.search("Ping canceled",current_line):
                num_failed_pings += 1
                continue
            else:
                print("NO DEST IP FOUND: " + current_line)
                sys.exit()
                        
        round_trip_latency_search = re.search("Round trip latency (.*), clock skew",current_line)
        
        if(round_trip_latency_search):
            round_trip_latency_search_result = round_trip_latency_search.group(1)
            # print("  - Latency: " + round_trip_latency_search_result)
            
            if round_trip_latency_search_result[-2] == "ms":
                round_trip_latency_search_result = float(round_trip_latency_search_result.replace("ms",""))
            elif round_trip_latency_search_result[-1] == "s":
                round_trip_latency_search_result = float(round_trip_latency_search_result.replace("s","")) * 1000
            else:
                print("What time unit is this: " + round_trip_latency_search_result)
            # print("  - Clean Latency: " + str(round_trip_latency_search_result))
            
            if not source_ip_port_trimmed_search_result in results_dataset:
                print("Adding new source: " + source_ip_port_trimmed_search_result)
                results_dataset[source_ip_port_trimmed_search_result] = {}
                results_dataset[source_ip_port_trimmed_search_result][str(dest_ip_port_trimmed_search_result)] =  [round_trip_latency_search_result] 
            else:
                # print("Source data: " + str(results_dataset[source_ip_port_trimmed_search_result]))
                # print("Dest IP: " + dest_ip_port_trimmed_search_result)
                if not dest_ip_port_trimmed_search_result in results_dataset[source_ip_port_trimmed_search_result]:
                    print("  Adding new dest (" + dest_ip_port_trimmed_search_result + ") to source: " + source_ip_port_trimmed_search_result )
                    results_dataset[source_ip_port_trimmed_search_result][dest_ip_port_trimmed_search_result] =  [round_trip_latency_search_result]
                else:
                    # print("  Appending new value to from dest (" + dest_ip_port_trimmed_search_result + ") to source: " + source_ip_port_trimmed_search_result )
                    results_dataset[source_ip_port_trimmed_search_result][dest_ip_port_trimmed_search_result].append(round_trip_latency_search_result)

print("\n---------- RESULTS ----------")               
for source_app in results_dataset:
    if source_app in ip_map:
        print("\nSource: " + ip_map[source_app])
    else:
        print("\nSource: " + source_app)
    for dest_app in results_dataset[source_app]:
        # print(str(results_dataset[source_app][dest_app]))
        num_dest_app_datapoints = len(results_dataset[source_app][dest_app])
        dest_app_latency_average = sum(results_dataset[source_app][dest_app])/num_dest_app_datapoints
        
        ping_diff_list = []
        for ping_i,ping_value in enumerate(results_dataset[source_app][dest_app]):
            if ping_i == 0:
                continue
            
            ping_diff_list.append(abs(float(results_dataset[source_app][dest_app][ping_i]) - float(results_dataset[source_app][dest_app][ping_i -1])))
        
        
        # print(str(ping_diff_list))
        dest_app_jitter = sum(ping_diff_list)/len(ping_diff_list)
        
        if dest_app in ip_map:
            print("    Dest: " + ip_map[dest_app])
        else:
            print("    Dest: " + dest_app)
        # print("    Dest: " + dest_app)
        print("        Pings: " + str(num_dest_app_datapoints))
        print("        Latency: " + str(dest_app_latency_average)  + " ms")
        print("        Jitter: " + str(dest_app_jitter)  + " ms")
        
        
        
print("\nNumber of Failed Pings: " + str(num_failed_pings))