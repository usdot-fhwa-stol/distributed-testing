#!/bin/bash
set -uo pipefail

source /home/carla/start_scripts/setup-carla-docker.sh

case "$VUG_DOCKER_START_CARLA" in
    local)
        echo "STARTING CARLA DOCKER"
        ;;
    remote)
        echo "USING REMOTE CARLA, CARLA DOCKER NOT STARTING"
        exit 1
        ;;
    off)
        echo "CARLA SET TO OFF, CARLA DOCKER NOT STARTING"
        exit 1
        ;;
    *)
        echo "UNKNOWN VUG_DOCKER_START_CARLA VALUE: ${VUG_DOCKER_START_CARLA:-<unset>}, CARLA DOCKER NOT STARTING"
        echo "    VALID VUG_DOCKER_START_CARLA VALUES: local, remote, off"
        exit 1
        ;;
esac

carla_graphics_quality_arg=""
case "$VUG_CARLA_QUALITY_LEVEL" in
    Epic)
        echo "CARLA GRAPHICS QUALITY SET TO EPIC"
        carla_graphics_quality_arg="-quality-level=Epic"
        ;;
    Low)
        echo "CARLA GRAPHICS QUALITY SET TO LOW"
        carla_graphics_quality_arg="-quality-level=Low"
        ;;
    *)
        echo "CARLA GRAPHICS QUALITY NOT SET (or unrecognized: ${VUG_CARLA_QUALITY_LEVEL:-<unset>}), USING DEFAULT"
        ;;
esac

# TFHRC needs a new digital twin for UE5
if [[ "$VUG_CARLA_MAP_NAME" == "TFHRC" ]]; then
    CARLA_LOCATION="/home/CARLA_TFHRC"
else
    CARLA_LOCATION="/home/carla"
fi

CARLA_BIN="$CARLA_LOCATION/CarlaUnreal.sh"
if [[ ! -x "$CARLA_BIN" ]]; then
    echo "ERROR: CARLA binary not found or not executable at $CARLA_BIN"
    exit 1
fi

echo "STARTING CARLA"

setsid "$CARLA_BIN" $carla_graphics_quality_arg -nosound &
CARLA_PID=$!

cleanup() {
    echo "Stopping CARLA gracefully..."
    kill -INT "-$CARLA_PID" 2>/dev/null || true

    local end=$((SECONDS + ${GRACE_SECONDS:-10}))
    while (( SECONDS < end )) && kill -0 "$CARLA_PID" 2>/dev/null; do
        sleep 1
    done

    if kill -0 "$CARLA_PID" 2>/dev/null; then
        echo "CARLA did not exit in time, forcing SIGTERM..."
        kill -TERM "-$CARLA_PID" 2>/dev/null || true
        sleep 2
    fi

    if kill -0 "$CARLA_PID" 2>/dev/null; then
        echo "CARLA still alive, sending SIGKILL..."
        kill -KILL "-$CARLA_PID" 2>/dev/null || true
    fi

    exit 0
}
trap cleanup TERM INT

sleep 5s
echo "VUG CARLA STARTUP COMPLETE"

wait "$CARLA_PID"
