#!/bin/sh

# Check if chrony is installed
if dpkg -s chrony >/dev/null 2>&1; then
    echo "Chrony is already installed."
else
    echo "Installing chrony..."
    if ! (export DEBIAN_FRONTEND=noninteractive; apt-get update -qq >/dev/null 2>&1 && apt-get install -y chrony tzdata -qq >/dev/null 2>&1); then
        echo "There was an error installing chrony. Please check your package manager."
        exit 1
    fi
fi


CONF_FILE="/etc/chrony/chrony.conf"
[ ! -f "$CONF_FILE" ] && CONF_FILE="/etc/chrony.conf"

# Server list
DESIRED_SERVERS="server time.cloudflare.com iburst
server time1.google.com iburst
server time2.google.com iburst
server time3.google.com iburst
server time4.google.com iburst
server time.aws.com iburst
server time1.facebook.com iburst
server time2.facebook.com iburst
server time3.facebook.com iburst
server time4.facebook.com iburst
server time5.facebook.com iburst"

# Check if servers already added
CURRENT_SERVERS=$(grep -E '^(server|pool) ' "$CONF_FILE")

if [ "$CURRENT_SERVERS" = "$DESIRED_SERVERS" ]; then
    echo "Chrony configuration is already updated."
    RESTART_NEEDED=false
else
    echo "Updating chrony servers..."

    sed -i '/^pool /d' "$CONF_FILE"
    sed -i '/^server /d' "$CONF_FILE"

    echo "$DESIRED_SERVERS" >> "$CONF_FILE"

    RESTART_NEEDED=true
fi

if [ "$RESTART_NEEDED" = true ]; then
    echo "Restarting chronyd..."
    /etc/init.d/chrony restart >/dev/null 2>&1 || { pkill chronyd 2>/dev/null; /usr/sbin/chronyd >/dev/null 2>&1; }

    sleep 2
else
    echo "No restart required."
    /etc/init.d/chrony start >/dev/null 2>&1 || /usr/sbin/chronyd >/dev/null 2>&1
fi


CURRENT_OFFSET=$(chronyc tracking | awk '/System time/ {print $4}')
: "${VUG_TIMESYNC_THRESHOLD_MS:=5}" 

# Check if already synchronized
if awk -v current="$CURRENT_OFFSET" -v target="$VUG_TIMESYNC_THRESHOLD_MS" \
   'BEGIN { abs_val = (current < 0) ? -current : current; target_sec = target / 1000; exit !(abs_val <= target_sec) }'; then
    echo "Time is already synchronized within $VUG_TIMESYNC_THRESHOLD_MS ms (Offset: $CURRENT_OFFSET)."
else
    echo "Forcing initial time step (makestep)..."
    #chronyc makestep [threshold] [limit]
    # -a (allow step at any time) - forces a step if the offset exceeds the threshold
    # threshold: 0.005 seconds (5 ms) - step if offset exceeds 5 ms
    # limit: -1 (unlimited) - allow unlimited steps at startup
    chronyc -a makestep 0.005 -1

    echo "Waiting for synchronization to settle (waitsync)..."
    # chronyc waitsync [max_tries] [max_correction] [max_skew] [interval]
    # max_correction: 0.002 seconds (2 ms) target for last sample
    # max_skew: 0.05 seconds (50 ms) target for confidence
    if chronyc waitsync 30 0.002 0.05 1; then
            echo "Time successfully synchronized within the 2ms offset and 50ms confidence bounds."
            chronyc tracking
    else
            echo "WARNING: Failed to reliably synchronize within the strict accuracy goals."
            
            OFFSET=$(chronyc tracking | grep 'System time' | awk '{print $4, $5}')
            SKEW=$(chronyc tracking | grep 'Root dispersion' | awk '{print $4, $5}')
            
            echo "Current System Time Offset: $OFFSET"
            echo "Current Confidence/Skew: $SKEW"
            
            echo "Advice:"
            echo "- If confidence (skew) is over +/- 50 ms, it indicates that network jitter is making it difficult to accurately synchronize your clock."
            echo "  It is recommended that you find ways to stabilize your connection (e.g., use a wired ethernet connection instead of Wi-Fi)."
            echo "- If the offset is consistently high, check if outbound UDP port 123 is blocked by a firewall."
            echo "- If sync persistently fails to meet these strict requirements, please contact and discuss with the event host."
            
            exit 1
    fi
fi