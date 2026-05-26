#!/bin/sh

# Check if chrony is installed
if dpkg -s chrony >/dev/null 2>&1; then
    echo "Chrony is already installed."
else
    echo "Installing chrony..."
    if ! DEBIAN_FRONTEND=noninteractive apt-get install -y -qq chrony >/dev/null 2>&1; then
        echo "There was an error installing chrony. Please check your package manager."
        exit 1
    fi
fi

CONF_FILE="/etc/chrony/chrony.conf"
[ ! -f "$CONF_FILE" ] && CONF_FILE="/etc/chrony.conf"
USER_BACKUP="${CONF_FILE}.original"

# Server list
DESIRED_SERVERS="server time.cloudflare.com iburst
pool pool.ntp.org iburst
server time.windows.com iburst"

# Create a backup of the user's original config if it doesn't already exist
if [ ! -f "$USER_BACKUP" ]; then
    echo "Backing up your original chrony config to $USER_BACKUP"
    cp "$CONF_FILE" "$USER_BACKUP"
fi

# Check if our custom config already exists and is active
CURRENT_SERVERS=$(grep -E '^(server|pool) ' "$CONF_FILE")

if [ "$CURRENT_SERVERS" = "$DESIRED_SERVERS" ]; then
    echo "Chrony configuration is already updated."
    RESTART_NEEDED=false
else
    echo "Updating chrony configuration..."
    # Always base our configuration on their preserved original config
    # Keeps references to other config relates files intact
    cp "$USER_BACKUP" "$CONF_FILE"
    sed -i '/^pool /d' "$CONF_FILE"
    sed -i '/^server /d' "$CONF_FILE"
    echo "$DESIRED_SERVERS" >> "$CONF_FILE"

    echo "--------------------------------------------------------"
    echo "NOTE: Your original chrony configuration is saved at:"
    echo "  $USER_BACKUP"
    echo "To revert back to your original chrony configuration, run:"
    echo "  sudo cp $USER_BACKUP $CONF_FILE"
    echo "  sudo systemctl restart chrony"
    echo "--------------------------------------------------------"
    
    RESTART_NEEDED=true
fi

if [ "$RESTART_NEEDED" = true ]; then
    echo "Restarting chronyd..."
    systemctl restart chrony >/dev/null 2>&1
    sleep 10
elif ! pgrep -x chronyd >/dev/null 2>&1; then
    echo "Starting chronyd..."
    systemctl start chrony >/dev/null 2>&1
    sleep 10
else
    echo "Chronyd is already running. No restart required."
fi

TARGET_OFFSET=$(awk -v t="${VUG_MAXIMUM_OFFSET_MS:-5}" 'BEGIN { print t/1000 }')
TARGET_DISPERSION="${VUG_MAXIMUM_DISPERSION:-0.050}"
IDEAL_OFFSET=$(awk -v t="${VUG_IDEAL_OFFSET_MS:-2}" 'BEGIN { print t/1000 }')
IDEAL_DISPERSION="${VUG_IDEAL_DISPERSION:-0.050}"

#chronyc tracking
# Last offset: This is the estimated local offset on the last clock update. 
# Root dispersion: This is the total dispersion accumulated through all the computers back to the stratum-1 computer from which the computer is ultimately synchronised. 
# Leap status: Current leap second status of the source, which can be Normal, Insert second, Delete second or Not synchronised.
START_TRACKING_OUT=$(chronyc tracking)
START_OFFSET=$(echo "$START_TRACKING_OUT" | awk '/Last offset/ {val = $4; gsub(/[+-]/, "", val); print val }')
START_DISPERSION=$(echo "$START_TRACKING_OUT" | awk '/Root dispersion/ {print $4}')
START_LEAP_STATUS=$(echo "$START_TRACKING_OUT" | grep 'Leap status' | awk -F ': ' '{print $2}')

# Check if already synchronized
IS_SYNCED=false
if [ -n "$START_OFFSET" ] && [ -n "$START_DISPERSION" ] && [ "$START_LEAP_STATUS" != "Not synchronised" ]; then

    if awk -v current="$START_OFFSET" -v target="$TARGET_OFFSET" 'BEGIN { exit !(current <= target) }'; then
        echo "Time is already synchronized within minimum ${VUG_MAXIMUM_OFFSET_MS:-5} ms threshold."
        IS_SYNCED=true
    fi

    if awk -v current="$START_OFFSET" -v dispersion="$START_DISPERSION" -v ideal_o="$IDEAL_OFFSET" -v ideal_d="$IDEAL_DISPERSION" \
       'BEGIN { exit !(current <= ideal_o && dispersion <= ideal_d) }'; then
        echo "Ideal Measurements Achieved: Your system time is within ${VUG_IDEAL_OFFSET_MS:-2} ms offset and confidence is less than +/- $(awk -v d="${IDEAL_DISPERSION}" 'BEGIN {print d*1000}') ms."
    else
        echo "Note: Your system time is outside the ideal measurements (Offset <= ${VUG_IDEAL_OFFSET_MS:-2}ms, Confidence <= $(awk -v d="${IDEAL_DISPERSION}" 'BEGIN {print d*1000}')ms). Offset: $START_OFFSET, Dispersion: $START_DISPERSION."
    fi
fi

if [ "$IS_SYNCED" = true ]; then
    echo "Skipping forced time step."
else
    echo "Forcing immediate time step (makestep 0.1 -1)..."

    #chronyc makestep [threshold] [limit]
    # threshold: if offset is more than threshold, jump
    # limit: number of jumps allowed, (if -1 then unlimited)
    chronyc makestep 0.1 -1 >/dev/null 2>&1

    #chronyc burst [good] [max]
    # good: try to collect 4 good samples from each source
    # max: max number of measurement attempts per source
    chronyc burst 10/20 >/dev/null 2>&1

    echo "Waiting for time synchronization to converge..."
    
    SYNC_SUCCESS=false
    MAX_TRIES=30
    INTERVAL=3


    for i in $(seq 1 $MAX_TRIES); do
        TRACKING_OUT=$(chronyc tracking)
        OFFSET=$(echo "$TRACKING_OUT" | awk '/Last offset/ {val = $4; gsub(/[+-]/, "", val); print val }')
        DISPERSION=$(echo "$TRACKING_OUT" | awk '/Root dispersion/ {print $4}')
        LEAP_STATUS=$(echo "$TRACKING_OUT" | awk -F ': ' '/Leap status/ {print $2}')
        
        if [ -n "$OFFSET" ] && [ -n "$DISPERSION" ] && [ "$LEAP_STATUS" != "Not synchronised" ]; then
            if awk -v o="$OFFSET" -v d="$DISPERSION" -v to="$TARGET_OFFSET" -v td="$TARGET_DISPERSION" \
                'BEGIN { exit !(o <= to && d <= td) }'; then
                SYNC_SUCCESS=true
                break
            else
                echo "Try $i: Offset = $OFFSET s, Dispersion = $DISPERSION s."
            fi
        fi
        sleep "$INTERVAL"
    done

    if [ "$SYNC_SUCCESS" = true ]; then
            echo "Time successfully synchronized within the $(awk -v d="${TARGET_OFFSET}" 'BEGIN {print d*1000}')ms offset and $(awk -v d="${TARGET_DISPERSION}" 'BEGIN {print d*1000}')ms dispersion."
            chronyc tracking
    else
            echo "WARNING: Failed to reliably synchronize within the strict accuracy goals."

            LAST_TRACKING_OUT=$(chronyc tracking)
            LAST_OFFSET=$(echo "$LAST_TRACKING_OUT" | awk '/Last offset/ {val = $4; gsub(/[+-]/, "", val); print val }')
            LAST_DISPERSION=$(echo "$LAST_TRACKING_OUT" | awk '/Root dispersion/ {print $4}')
            echo "FINAL System Time Offset: $LAST_OFFSET"
            echo "FINAL Root Dispersion: $LAST_DISPERSION"

            echo "Advice:"
            echo "- If root dispersion is over 50 ms, it indicates high uncertainty in your clock accuracy."
            echo "- This can be caused by network jitter, unstable time sources, or high latency."
            echo "- It is recommended that you find ways to stabilize your connection (e.g., use a wired ethernet connection instead of Wi-Fi)."
            echo "- If the offset is consistently high, check if outbound UDP port 123 is blocked by a firewall."
            echo "- If sync persistently fails to meet these strict requirements, please contact and discuss with the event host."

            read -p "Press Enter to continue anyway, or Ctrl+C to abort and troubleshoot." _
    fi
fi 