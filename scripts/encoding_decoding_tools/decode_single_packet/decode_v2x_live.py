"""
V2X Adapter Listener Script
---------------------------

PURPOSE:
This script is designed to listen for incoming UDP packets containing V2X messages from the V2X adapter.
It will receive the packets, decode them, and print the decoded messages to the console.
It can be expanded to do something else with the packets as needed.

USAGE:
This script should be run with one of the following commands, from inside the dt-core container (use 'dt exec' to enter the container)
    python3 decode_v2x_live.py -h $VUG_V2X_ADAPTER_SEND_ADDRESS -p $VUG_V2X_ADAPTER_SEND_PORT
    python3 decode_v2x_live.py --host $VUG_V2X_ADAPTER_SEND_ADDRESS --port $VUG_V2X_ADAPTER_SEND_ADDRESS
"""

import J2735_201603_2023_06_22 as J2735
import socket
import binascii as ba
import argparse

def start_v2x_listener(host: str, port: int):
    """
    Creates a UDP socket and listens for incoming packets.
    """

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))

    print(f"Listening for V2X messages on {host}:{port}...")

    while True:
        try:
            data, addr = sock.recvfrom(4096)
            hex_data = data.hex()
            
            #CUSTOM LOGIC FOR DECODING J2735 HERE
            decoded_msg = J2735.DSRC.MessageFrame
            decoded_msg.from_uper(ba.unhexlify(hex_data))
            decoded_msg_json = decoded_msg.to_json()

            print(f'Decoded msg from {addr}:')
            print(f'\t{decoded_msg_json}')
            
        except KeyboardInterrupt:
            print("\nShutting down V2X listener.")
            break

        except Exception as e:
            print(f"\nError decoding packet: {e}")


def main():
    """
    Entry point: parses CLI arguments and starts listener
    """

    parser = argparse.ArgumentParser(
        description="V2X Adapter Listener",
        add_help=False
    )
    parser.add_argument(
        "-h", "--host",
        dest="host",
        type=str,
        default="127.0.0.1",
        help="IP address to bind to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "-p", "--port",
        dest="port",
        type=int,
        default=5398,
        help="UDP port to listen on (default: 5398)"
    )
    parser.add_argument(
        "--help",
        action="help",
        help="Show this help message and exit"
    )
    args = parser.parse_args()

    start_v2x_listener(args.host, args.port)

if __name__ == "__main__":
    main()

