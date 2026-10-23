"""
bsm_example.py generates BSMs using the position information contained in bsm_positions.json

It then sends them to the v2x adapter to be published to the network

This script also ingests incoming V2X messages from the v2x adapter, decodes them, and displays the bsmid along with the location to the terminal.
"""

import os
import sys
import ast
import json
import time
import threading
import argparse
import socket
import random

import binascii as ba
import j2735_202409 as J2735

from datetime import datetime, timezone
from time import sleep


# Global variables
msgCount = 0

# Change with organizations participating in your connectivity test
org_bsmid_map = {
    "Omniair": "a7c29e41",
    "Keysight": "3f8b12d6",
    "Kapsch": "e05a74bc",
    "Indra": "91d4f603"
}
# For easy reverse searching (organization using the bsm ID), create the same map in reverse "<bsm ID>":"<organization>"
bsmid_org_map = {v: k for k, v in org_bsmid_map.items()}

HOST = os.getenv("VUG_LOCAL_ADDRESS")
V2X_PUB_PORT = int(os.getenv("VUG_V2X_ADAPTER_RECEIVE_PORT"))
V2X_LISTEN_PORT = int(os.getenv("VUG_V2X_ADAPTER_SEND_PORT"))

SEND_RATE_HZ = 10
SEND_INTERVAL = 1.0 / SEND_RATE_HZ #0.1 seconds

# Latest known position for each organization
latest_positions = {}

def handle_bsm(bsm, pos_lock):
    with pos_lock:
        core_data = bsm["value"]["coreData"]

        org = bsmid_org_map[core_data["id"]]
        latest_positions[org] = {
            "lat": core_data["lat"],
            "long": core_data["long"],
            "elev": core_data["elev"],
            "heading": core_data["heading"]
        }

def listen_v2x(pos_lock):
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
                handle_bsm(decoded_msg_json, pos_lock)
        
        except Exception as e:
            print(f"\nError decoding packet: {e}")

def build_bsm(position, org, pos_lock):
    """
    Builds a BSM using the position information from the loaded JSON file
    """

    # Determine secMark using current utc time
    now = datetime.now(timezone.utc)
    secMark = (now.second * 1000) + (now.microsecond // 1000)

    global msgCount
    count = msgCount
    msgCount = (msgCount + 1) & 0x7F

    bsm_id = bytes.fromhex(org_bsmid_map[org])

    bsm_dict = {
        "messageId": 20,
        "value": (
            "BasicSafetyMessage", 
            {
                "coreData": {
                    "msgCnt": count,
                    "id": bsm_id,
                    "secMark": secMark,
                    "lat": position["lat"],
                    "long": position["long"],
                    "elev": position["elevation"],
                    "accuracy":{
                        "semiMajor": 255,
                        "semiMinor": 255,
                        "orientation": 65535
                    },
                    "transmission": "unavailable",
                    "speed": 0,
                    "heading": position["heading"],
                    "angle": 127,
                    "accelSet": {
                        "long": 0,
                        "lat": 2000,
                        "vert": 1,
                        "yaw": 0
                    },
                    "brakes": {
                        "wheelBrakes": (0, 5),
                        "traction": "unavailable",
                        "abs": "unavailable",
                        "scs": "unavailable",
                        "brakeBoost": "unavailable",
                        "auxBrakes": "unavailable"
                    },
                    "size": {
                        "width": 50,
                        "length": 50
                    }
                }
            }
        )
    }

    # Update latest positions for your own vehicle
    with pos_lock:
        latest_positions[org] = {
            "lat": position["lat"],
            "long": position["long"],
            "elev": position["elevation"],
            "heading": position["heading"]
        }

    bsm = ast.literal_eval(str(bsm_dict))
    frame = J2735.MessageFrame.MessageFrame
    frame.set_val(bsm)
    frame_uper = frame.to_uper()

    amf = f'Version=0.7\nType=BSM\nPSID=0x20\nPriority=2\nTxMode=CONT\nTxChannel=183\nTxInterval=0\nDeliveryStart=\nDeliveryStop=\nSignature=False\nEncryption=False\nPayload='

    amf += str(frame_uper.hex())

    return amf

def send_bsm(org, pos_lock):

    # Create publish socket
    publish_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = (HOST, V2X_PUB_PORT)

    # Get the path to the positions json file
    script_dir = os.path.dirname(os.path.abspath(__name__))
    position_path = os.path.join(script_dir,"bsm_positions.json")

    # Read the json file and set the positions into an array
    with open(position_path, "r") as f:
        position_json = json.load(f)
    positions = position_json["positions"]
    
    # Determine a random starting position
    position_index = random.randrange(len(positions))

    while True:
        loop_start = time.perf_counter()

        position = positions[position_index]
        bsm = build_bsm(position, org, pos_lock)
        
        publish_socket.sendto(bsm.encode("ascii"), target)

        position_index = (position_index + 1) % len(positions)

        elapsed = time.perf_counter() - loop_start
        sleep_time = SEND_INTERVAL - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)

def print_positions():
    while True:
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

        time.sleep(0.1)

def main():

    parser = argparse.ArgumentParser(description="V2X BSM Connectivity Test Script")

    parser.add_argument("--org", type=str, required=True, default="FHWA", help="Your organization, used to determine BSM ID")
    args = parser.parse_args()
    org = args.org

    positions_lock = threading.Lock()
    
    # Link the receive thread to run the code in listen_v2x()
    listen_thread = threading.Thread(target=listen_v2x, args=(positions_lock,), name="ReceiveThread")

    # Link the send thread to run the code in send_bsm()
    send_thread = threading.Thread(target=send_bsm, args=(org,positions_lock,), name="SendThread")

    # Print latest positions to the console
    print_thread = threading.Thread(target=print_positions, name="PrintThread")

    # Start both threads
    listen_thread.start()
    send_thread.start()
    print_thread.start()

if __name__ == "__main__":
    main()