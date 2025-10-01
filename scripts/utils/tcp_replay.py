#!/usr/bin/env python3
# udp_replay.py
# pip install scapy
import argparse
import socket
import time
from scapy.all import PcapReader, UDP, IP, Raw

def main():
    ap = argparse.ArgumentParser(description="Replay UDP packets from a pcap to a given IP/port")
    ap.add_argument("pcap", help="Path to pcap/pcapng file")
    ap.add_argument("--dst-ip", default="127.0.0.1", help="Destination IP (default: localhost)")
    ap.add_argument("--dst-port", type=int, required=True, help="Destination UDP port")
    ap.add_argument("--speed", type=float, default=1.0, help="Speed multiplier for playback")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    prev_ts = None
    with PcapReader(args.pcap) as r:
        for pkt in r:
            if UDP in pkt and Raw in pkt:
                payload = bytes(pkt[Raw].load)

                # sleep to match timing if available
                if prev_ts is not None:
                    dt = (pkt.time - prev_ts) / max(args.speed, 1e-9)
                    if dt > 0:
                        time.sleep(float(dt))
                prev_ts = pkt.time

                sock.sendto(payload, (args.dst_ip, args.dst_port))
                print(f"Sent {len(payload)} bytes to {args.dst_ip}:{args.dst_port}")

    sock.close()

if __name__ == "__main__":
    main()
