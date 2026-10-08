#!/bin/bash
set -euo pipefail
gpsd_pid=""
bridge_pid=""
cleanup() {
    trap - EXIT
    for pid in "$bridge_pid" "$gpsd_pid"; do
        if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null || true; fi
    done
    wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 0' TERM INT

# No physical devices, virtual serial devices, or host services are involved.
gpsd -N -n -b -G -D 2 -S 2947 udp://127.0.0.1:5001 &
gpsd_pid=$!
python3 - <<'PY'
import socket
import time
deadline = time.monotonic() + 15
while True:
    try:
        with socket.create_connection(('127.0.0.1', 2947), timeout=1) as client:
            if b'VERSION' in client.recv(4096):
                break
    except OSError:
        pass
    if time.monotonic() >= deadline:
        raise SystemExit('GPSD client service did not become ready')
    time.sleep(0.1)
PY
socat -u TCP-LISTEN:51928,reuseaddr,fork UDP-SENDTO:127.0.0.1:5001 &
bridge_pid=$!
echo "GPSD: TCP producer 51928 -> internal UDP 5001 -> GPSD client TCP 2947"
# With fork, one producer disconnect does not terminate the listener or GPSD.
set +e
wait -n "$gpsd_pid" "$bridge_pid"
echo "GPSD or bridge listener exited unexpectedly" >&2
exit 1
