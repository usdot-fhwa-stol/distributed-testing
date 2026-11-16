#!/bin/bash
# relay.sh on|off|status - TENA -> ego BSM relay

# Get the directory where this script lives
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$SRC_DIR/tena_bsm_relay.py"

# Use /tmp for PID and logs to avoid permission denied errors
D="/tmp/carla-erv-ego-relay"
P="$D/relay.pid"

# Use the exact IPs that worked manually
BIND=${RELAY_BIND:-192.168.55.237:5398}
TO=${RELAY_TO:-192.168.55.237:47347}
CARLA=${RELAY_CARLA:-192.168.55.237:2000}

mkdir -p "$D"

case "${1:-status}" in
  on)  
       [ -f "$P" ] && kill "$(cat "$P")" 2>/dev/null
       
       echo "Starting relay in background..."
       setsid nohup python3 -u "$SRC" --bind "$BIND" --to "$TO" --carla "$CARLA" > "$D/relay.out" 2>&1 < /dev/null &
       echo $! > "$P"
       sleep 2
       
       # Check if it actually stayed alive
       if kill -0 "$(cat "$P")" 2>/dev/null; then
           echo "relay ON (PID $(cat "$P"))"
       else
           echo "relay FAILED TO START. Check relay.out:"
           cat "$D/relay.out"
       fi
       ;;
  off) 
       [ -f "$P" ] && kill "$(cat "$P")" 2>/dev/null && echo "stopped"
       rm -f "$P" 
       ;;
  *)   
       if [ -f "$P" ] && kill -0 "$(cat "$P")" 2>/dev/null; then
           echo "relay ON (PID $(cat "$P"))"
       else
           echo "relay OFF"
       fi
       tail -n 1 "$D/relay.out" 2>/dev/null 
       ;;
esac