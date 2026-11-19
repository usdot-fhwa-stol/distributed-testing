import json
import sys
from csv import reader, writer
import subprocess as sp
import re

print("\n----- EXTRACTING RAW PACKET FRAMES FROM PCAP -----")

# print("\nARG LIST:")
# for i, arg in enumerate(sys.argv):
#     print(str(i) + ": " + str(arg))
# print("")

inFile = sys.argv[1]
outfile = sys.argv[2]

cmds = ["tshark", "-x", "-r",inFile , "-T", "json"]
frames_text = sp.check_output(cmds, text=True)
frames_json = json.loads(frames_text)

total_packets = 0

with open(outfile, 'w', newline='') as write_obj:
    csv_writer = writer(write_obj)
    
    csv_writer.writerow(["packet_index","timestamp","frame_raw"])

    for packet in frames_json:

        frame_raw = str(packet["_source"]["layers"]["frame_raw"][0])

        timestamp = packet["_source"]["layers"]["frame"]["frame.time_epoch"]

        total_packets += 1

        csv_writer.writerow([total_packets,timestamp,frame_raw])
        

print("\n --> Total Packets: " + str(total_packets))


