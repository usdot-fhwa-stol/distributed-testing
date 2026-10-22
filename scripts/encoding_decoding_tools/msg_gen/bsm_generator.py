"""
bsm_example.py generates BSMs using the position information contained in bsm_positions.json

It then sends them to the v2x adapter to be published to the network

This script also ingests incoming V2X messages from the v2x adapter, decodes them, and displays the bsmid along with the location to the terminal.
"""

import os
import sys
import json
from datetime import datetime
from time import sleep
import time
import threading
import argparse


# Global variables
msgCnt = 0
msgCnt_lock = threading.Lock()

def receive_v2x(stdout_lock):
    while True:
        with stdout_lock:
            print(f"Received V2X")
        sleep(0.01)
        
def send_bsm(stdout_lock):
    # Get the path to the positions json file
    script_dir = os.path.dirname(os.path.abspath(__file__))
    position_path = os.path.join(script_dir,"bsm_positions.json")

    # Read the json file and set the positions into an array
    with open(position_path, "r") as f:
        position_json = json.load(f)
    positions = position_json["pos"]
    print(positions[0])

    while True:
        with stdout_lock:
            print(f"Sending BSM")
        sleep(0.1)

def main():

    parser = argparse.ArgumentParser(description="V2X BSM Connectivity Test Script")

    parser.add_argument("--org", type=str, default="FHWA", help="Your organization, used to determine BSM ID")

    # Create a lock so threads are not accessing stdout at the same time
    stdout_lock = threading.Lock()
    
    # Link the receive thread to run the code in receive_v2x()
    receive_thread = threading.Thread(target=receive_v2x, args=(stdout_lock,), name="ReceiveThread")

    # Link the send thread to run the code in send_bsm()
    send_thread = threading.Thread(target=send_bsm, args=(stdout_lock,), name="SendThread")

    # Start both threads
    receive_thread.start()
    send_thread.start()

if __name__ == "__main__":
    main()