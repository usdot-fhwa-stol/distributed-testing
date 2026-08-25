#!/bin/bash

# this script ssh into 2 OBUs and start pcap recording at the same time.

USER="user"
IP_out="192.168.55.82"  # IP of OBU sending BSM
IP_in="192.168.55.81"   # IP of OBU receiving BSM rebroadcasted by the proxy radio
IFACE_out="rmnet_data16"
IFACE_in="rmnet_data15"
SOURCE_FILTER="80f8:f80:f80f:80f8::3e:7eff"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

# Function to stop both tcpdump instances at the exact same time
stop_dumps() {
    echo -e "\nStopping captures simultaneously..."
    ssh -n "$USER@$IP_out" "sudo pkill -f tcpdump"
    ssh -n "$USER@$IP_in" "sudo pkill -f tcpdump"

    sleep 2
    
    echo "Transferring files to local host..."
    scp "$USER@$IP_out:/tmp/capture_${TIMESTAMP}.pcap" "./capture_${TIMESTAMP}_outbound.pcap"
    scp "$USER@$IP_in:/tmp/capture_${TIMESTAMP}.pcap" "./capture_${TIMESTAMP}_inbound.pcap"
    
    echo "Transfers complete. Files saved as:"
    echo " - ./capture_${TIMESTAMP}_outbound.pcap"
    echo " - ./capture_${TIMESTAMP}_inbound.pcap"

    exit 0
}

# Catch Ctrl+C (SIGINT) and trigger the stop function
trap stop_dumps INT

echo "Starting tcpdump on $IP_out and $IP_in. Press Ctrl+C to stop both."

# Launch both remote captures in the background using subshells
ssh "$USER@$IP_out" "sudo tcpdump -i $IFACE_out -Q out -nn -w /tmp/capture_${TIMESTAMP}.pcap" &
ssh "$USER@$IP_in" "sudo tcpdump -i $IFACE_in -Q in -nn src ${SOURCE_FILTER}  -w /tmp/capture_${TIMESTAMP}.pcap" &

# Wait for background jobs to run until interrupted
wait