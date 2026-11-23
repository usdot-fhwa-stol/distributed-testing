import json
import sys
from csv import reader, writer
import subprocess as sp
import re

print("\n----- EXTRACTING PAYLOADS FROM PCAP -----")

# print("\nARG LIST:")
# for i, arg in enumerate(sys.argv):
#     print(str(i) + ": " + str(arg))
# print("")

inFile = sys.argv[1]
outfile = sys.argv[2]

#tshark 
#-r infile                  - select file to read
#-o data.show_as_text:TRUE  - decode payload into ascii
#--disable-protocol wsmp    - ?
# -T fields                 - ?
# -E separator=,            - separate subsequent fields with ,
# -e frame.time_epoch       - get the packet timestamp
# -e data.text              - get the text payload

cmds = ["tshark", "-r",inFile , "-o", "data.show_as_text:TRUE", "--disable-protocol", "wsmp", "-T", "fields", "-E", "separator=,", "-e", "frame.time_epoch", "-e", "data.text" ]
payloads_text = sp.run(cmds, text=True, stdout=sp.PIPE)
payloads_split = payloads_text.stdout.split("\n")

total_packets = 0

with open(outfile, 'w', newline='') as write_obj:
    csv_writer = writer(write_obj)

    csv_writer.writerow(["packet_index","timestamp","payload"])

    for packet in payloads_split:
        if packet:
            # print("packet: " + packet)
            packet_list = packet.split(",")
            
            timestamp = str(packet_list[0])
            if len(packet_list[1]) > 10:
                payload = str(packet_list[1]).replace("\\n","").split("Payload=")[1].lower()
            else:
                print("\nERROR: INVALID PACKET: " + packet)
                # payload=""
                continue
            
            # print("timestamp: " + str(timestamp))
            # print("payload: " + str(payload))
            # print("")

            total_packets += 1

            csv_writer.writerow([total_packets,timestamp,payload])
        # else:
        #     print("Bad Packet: " + packet)
        

print("\n --> Total Packets: " + str(total_packets))


