#!/bin/bash

# Define the server IP and ports
SERVER_IP="173.73.28.235"
TCP_PORT="5201"
UDP_PORT="5201"
SERVER_NAME="SRC"

# Ensure the output directory exists
output_dir="$HOME/iperf3/$SERVER_NAME"
mkdir -p "$output_dir"

# Generate a timestamp for directory naming consistency
timestamp=$(date +"%Y%m%d_%H%M%S")

# Create a new subdirectory for this test run
output_subdir="$output_dir/$timestamp"
mkdir -p "$output_subdir"

# Bandwidth values
latency_bw="10M"
pktloss_bw="10M"
udp_max_bw="100M"
udp_up_bw="100M"
udp_down_bw="100M"

# Define log file paths with timestamps and bandwidths in filenames
throughput_output="$output_subdir/${timestamp}_iperf3_throughput.txt"
tcp_output="$output_subdir/${timestamp}_iperf3_tcp_15streams.txt"
tcp_up_output="$output_subdir/${timestamp}_iperf3_tcp_up_15streams.txt"
tcp_down_output="$output_subdir/${timestamp}_iperf3_tcp_down_15streams.txt"
udp_latency_up_output="$output_subdir/${timestamp}_iperf3_udp_latency_up_${latency_bw}.txt"
udp_latency_down_output="$output_subdir/${timestamp}_iperf3_udp_latency_down_${latency_bw}.txt"
udp_pktloss_output="$output_subdir/${timestamp}_iperf3_udp_pktloss_${pktloss_bw}.txt"
udp_max_output="$output_subdir/${timestamp}_iperf3_udp_max_${udp_max_bw}.txt"
udp_up_output="$output_subdir/${timestamp}_iperf3_udp_up_${udp_up_bw}.txt"
udp_down_output="$output_subdir/${timestamp}_iperf3_udp_down_${udp_down_bw}.txt"
summary_log="$output_subdir/${timestamp}_test_summary.log"

# Create a temporary script file
temp_script="$output_subdir/run_iperf_tests.sh"

cat <<EOF > "$temp_script"
#!/bin/bash

echo "Starting iPerf3 Tests on server: $SERVER_NAME $SERVER_IP" | tee -a "$summary_log"

# Run each test with descriptive messages and log errors
echo "Running: TCP Throughput Test (throughput.txt)"
iperf3 -c $SERVER_IP -p $TCP_PORT --bidir -t 30 -i 1 2>&1 | tee "$throughput_output"

sleep 5

echo "Running: TCP 15 Streams Bidirectional (tcp_15streams.txt)"
iperf3 -c $SERVER_IP -p $TCP_PORT --bidir -P 15 -t 65 -i 1 2>&1 | tee "$tcp_output"

sleep 5

echo "Running: TCP Upload (tcp_up_15streams.txt)"
iperf3 -c $SERVER_IP -p $TCP_PORT -P 15 -t 65 -i 1 2>&1 | tee "$tcp_up_output"

sleep 5

echo "Running: TCP Download (tcp_down_15streams.txt)"
iperf3 -c $SERVER_IP -p $TCP_PORT -P 15 -t 65 -i 1 -R 2>&1 | tee "$tcp_down_output"

sleep 5

echo "Running: UDP Latency Upload Test (udp_latency_up_${latency_bw}.txt)"
iperf3 -c $SERVER_IP -p $UDP_PORT -u -b ${latency_bw} -t 20 -i 1 2>&1 | tee "$udp_latency_up_output"

sleep 5

echo "Running: UDP Latency Download Test (udp_latency_down_${latency_bw}.txt)"
iperf3 -c $SERVER_IP -p $UDP_PORT -u -b ${latency_bw} -t 20 -i 1 -R 2>&1 | tee "$udp_latency_down_output"

sleep 5

echo "Running: UDP Packet Loss Test (udp_pktloss_${pktloss_bw}.txt)"
iperf3 -c $SERVER_IP -p $UDP_PORT --bidir -u -b ${pktloss_bw} -t 20 -i 1 --pacing-timer 1000 2>&1 | tee "$udp_pktloss_output"

sleep 5

echo "Running: Maximum UDP Throughput (udp_max_${udp_max_bw}.txt)"
iperf3 -c $SERVER_IP -p $UDP_PORT --bidir -u -b ${udp_max_bw} -t 65 -i 1 2>&1 | tee "$udp_max_output"

sleep 5

echo "Running: UDP Upload (udp_up_${udp_up_bw}.txt)"
iperf3 -c $SERVER_IP -p $UDP_PORT -u -b ${udp_up_bw} -t 65 -i 1 2>&1 | tee "$udp_up_output"

sleep 5

echo "Running: UDP Download (udp_down_${udp_down_bw}.txt)"
iperf3 -c $SERVER_IP -p $UDP_PORT -u -b ${udp_down_bw} -t 65 -i 1 -R 2>&1 | tee "$udp_down_output"

echo "All Tests Completed. Logs saved in $output_subdir" | tee -a "$summary_log"

# Keep terminal open for review
exec bash
EOF

# Make the script executable
chmod +x "$temp_script"

# Open GNOME Terminal and run the script
gnome-terminal -- bash -c "$temp_script"

