"""
bsm_example.py generates BSMs using the position information contained in bsm_positions.json

It then sends them to the v2x adapter to be published to the network

This script also ingests incoming V2X messages from the v2x adapter, decodes them, and displays the bsmid along with the location to the terminal.
"""

import os
import sys
import json
import time
import threading
import argparse
import socket

import binascii as ba
import j2735_202409 as J2735

from datetime import datetime
from time import sleep


# Global variables
msgCnt = 0
msgCnt_lock = threading.Lock()

org_bsmid_map = {
    "Omniair": "a7c29e41",
    "Keysight": "3f8b12d6",
    "Kapsch": "e05a74bc",
    "Indra": "91d4f603"
}
# For easy reverse searching (organization using the bsm ID), create the same map in reverse "<bsm ID>":"<organization>"
bsmid_org_map = {v: k for k, v in org_bsmid_map.items()}

HOST = os.getenv("VUG_LOCAL_ADDRESS")
V2X_PUB_PORT = os.getenv("VUG_V2X_ADAPTER_RECEIVE_PORT")
V2X_LISTEN_PORT = int(os.getenv("VUG_V2X_ADAPTER_SEND_PORT"))

# Latest known position for each organization
latest_positions = {}

def handle_bsm(bsm):

    core_data = bsm["value"]["coreData"]

    org = bsmid_org_map[core_data["id"]]
    latest_positions[org] = {
        "lat": core_data["lat"],
        "long": core_data["long"],
        "elev": core_data["elev"],
        "heading": core_data["heading"]
    }

def print_positions():
    # Move cursor to the top-left and clear the console
    print("\033[2J\033[H", end="")

    print("\n--- Latest BSM Positions ---")
    for org, pos in latest_positions.items():
        print(
            f"{org}: "
            f"lat={pos['lat']}, "
            f"long={pos['long']}, "
            f"elev={pos['elev']}, "
            f"heading={pos['heading']}"
        )


def listen_v2x(stdout_lock):
    """
    Creates a UDP socket, binding to HOST:V2X_LISTEN_PORT

    When a V2X Message is received, it will be decoded, then if it's a BSM, this function will match the BSM ID to an organization, update the location of that orgs vehicle and print all organization vehicle locations to the console.

    If the V2X Message is not a BSM, it will be ignored
    """

    listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listen_socket.bind((HOST, V2X_LISTEN_PORT))

    latest_positions = {}

    while True:
        try:
            # Receive message
            data, addr = listen_socket.recvfrom(8192)

            # Decode to JSON
            decoded_msg = J2735.MessageFrame.MessageFrame
            decoded_msg.from_uper(data)
            decoded_msg_json = decoded_msg.to_json()

            if isinstance(decoded_msg_json, str):
                decoded_msg_json = json.loads(decoded_msg_json)

            if(decoded_msg_json["messageId"]==20):
                print("Received BSM")
                handle_bsm(decoded_msg_json)
            
            # Print updated locations to console
            print_positions()
        
        except Exception as e:
            print(f"\nError decoding packet: {e}")
        
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
    
    # Link the receive thread to run the code in listen_v2x()
    listen_thread = threading.Thread(target=listen_v2x, args=(stdout_lock,), name="ReceiveThread")

    # Link the send thread to run the code in send_bsm()
    send_thread = threading.Thread(target=send_bsm, args=(stdout_lock,), name="SendThread")

    # Start both threads
    listen_thread.start()
    send_thread.start()

if __name__ == "__main__":
    main()