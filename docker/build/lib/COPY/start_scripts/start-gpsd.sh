#!/bin/bash
set -euo pipefail

# Configuration is inherited from dt-core's setup-docker.sh.
input_address="${GPSD_INPUT_ADDRESS:-${VUG_LOCAL_ADDRESS:?VUG_LOCAL_ADDRESS is required}}"

for name in GPSD_INPUT_PORT GPSD_CLIENT_PORT GPSD_UDP_PORT; do
    value="${!name:-}"
    if [[ ! "$value" =~ ^[0-9]{1,5}$ ]]; then
        echo "ERROR: $name must be an integer from 1 to 65535" >&2
        exit 1
    fi
    value=$((10#$value))
    if (( value < 1 || value > 65535 )); then
        echo "ERROR: $name is outside 1 to 65535" >&2
        exit 1
    fi
    printf -v "$name" '%s' "$value"
done

if [[ "$GPSD_INPUT_PORT" == "$GPSD_CLIENT_PORT" ]]; then
    echo "ERROR: GPSD input and client TCP ports must differ" >&2
    exit 1
fi

for command in gpsd socat python3 setsid; do
    command -v "$command" >/dev/null || {
        echo "ERROR: Required command missing: $command" >&2
        exit 1
    }
done

gpsd_pid=""
bridge_pid=""

cleanup() {
    trap - EXIT TERM INT
    if [[ -n "${GPSD_READY_FILE:-}" ]]; then
        rm -f -- "$GPSD_READY_FILE"
    fi
    for pid in "$bridge_pid" "$gpsd_pid"; do
        if [[ -n "$pid" ]]; then
            kill -TERM -- "-$pid" 2>/dev/null || true
        fi
    done
    sleep 1
    for pid in "$bridge_pid" "$gpsd_pid"; do
        if [[ -n "$pid" ]]; then
            kill -KILL -- "-$pid" 2>/dev/null || true
        fi
    done
    wait 2>/dev/null || true
}

trap cleanup EXIT
trap 'exit 0' TERM INT

# Separate process groups allow cleanup of forked bridge connections.
setsid gpsd -N -n -b -G -D 1 \
    -S "$GPSD_CLIENT_PORT" \
    "udp://127.0.0.1:$GPSD_UDP_PORT" &
gpsd_pid=$!

setsid socat -u \
    "TCP-LISTEN:$GPSD_INPUT_PORT,bind=$input_address,reuseaddr,fork" \
    "UDP-SENDTO:127.0.0.1:$GPSD_UDP_PORT" &
bridge_pid=$!

# Check the actual configured endpoints, not fixed container ports.
python3 - "$input_address" "$GPSD_INPUT_PORT" "$GPSD_CLIENT_PORT" \
    "$gpsd_pid" "$bridge_pid" <<'PY'
import json
import os
import socket
import sys
import time

address, input_port, client_port, gpsd_pid, bridge_pid = sys.argv[1:]
deadline = time.monotonic() + 20

while True:
    try:
        for pid in (gpsd_pid, bridge_pid):
            os.kill(int(pid), 0)
    except ProcessLookupError:
        raise SystemExit("GPSD or bridge exited during startup")

    try:
        with socket.create_connection((address, int(input_port)), timeout=2):
            pass
        with socket.create_connection(("127.0.0.1", int(client_port)), timeout=2) as client:
            client.settimeout(2)
            with client.makefile("rb") as stream:
                response = json.loads(stream.readline(4096))
            if response.get("class") != "VERSION":
                raise ValueError("Expected GPSD VERSION response")
        break
    except (OSError, ValueError) as error:
        if time.monotonic() >= deadline:
            raise SystemExit("GPSD readiness failed: {}".format(error))
        time.sleep(0.2)
PY

kill -0 "$gpsd_pid" "$bridge_pid"
if [[ -n "${GPSD_READY_FILE:-}" ]]; then
    printf 'ready\n' > "$GPSD_READY_FILE"
fi
echo "GPSD ready: producer $input_address:$GPSD_INPUT_PORT; client TCP $GPSD_CLIENT_PORT"

set +e
wait -n "$gpsd_pid" "$bridge_pid"
echo "ERROR: GPSD or bridge exited unexpectedly" >&2
exit 1
