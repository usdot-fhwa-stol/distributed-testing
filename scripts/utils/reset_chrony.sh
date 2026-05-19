#!/bin/bash

# Ensure running as root
if [ "$EUID" -ne 0 ]; then
  echo "Error: Please run as root."
  exit 1
fi

CONFIG_FILE="/etc/chrony/chrony.conf"

echo "Stopping chrony service..."
systemctl stop chrony 2>/dev/null || systemctl stop chronyd 2>/dev/null

echo "Original system time: $(date)"
echo "Artificially offsetting system time by -30 seconds..."
date -s "-30 seconds" >/dev/null 2>&1 
echo "New system time: $(date)"

echo "Resetting configuration to default pool servers..."
cat << EOF > "$CONFIG_FILE"
# Default chrony configuration
pool pool.ntp.org iburst
driftfile /var/lib/chrony/drift
makestep 1.0 3
rtcsync
logdir /var/log/chrony
EOF

echo "Starting chrony service..."
systemctl start chrony 2>/dev/null || systemctl start chronyd 2>/dev/null

echo "Chrony reset complete, you can now test timesync.sh"