#!/bin/bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
compose=(
    docker compose
    -p dt-gpsd-standalone-test
    -f "$script_dir/gpsd-test.compose.yml"
)

case "${1:-status}" in
    start)
        "${compose[@]}" up -d --build --wait --wait-timeout 60 gpsd
        echo "GPSD test service is ready."
        echo "Emulator input: 127.0.0.1:55000"
        echo "GPSD clients:  127.0.0.1:52947"
        ;;
    stop)
        "${compose[@]}" down
        ;;
    status)
        "${compose[@]}" ps -a
        ;;
    logs)
        "${compose[@]}" logs --tail 50 gpsd
        ;;
    *)
        echo "Usage: bash $0 {start|stop|status|logs}" >&2
        exit 2
        ;;
esac
