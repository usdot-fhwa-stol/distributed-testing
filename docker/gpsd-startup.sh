#!/bin/bash

dt_gpsd_prepare() {
    # GPSD may be needed before a manually launched emulator.
    case "${GPSD_ENABLED:-false}" in
        false) return 0 ;;
        true) ;;
        *)
            echo "ERROR: GPSD_ENABLED must be true or false" >&2
            return 1
            ;;
    esac

    case "${HWIL_GNSS_OUTPUT_MODE:-}" in
        direct)
            echo "GNSS output: existing direct destination"
            return 0
            ;;
        gpsd)
            ;;
        *)
            echo "ERROR: HWIL_GNSS_OUTPUT_MODE must be gpsd or direct" >&2
            return 1
            ;;
    esac

    local port
    for port in "${GPSD_INPUT_PORT:-}" "${GPSD_CLIENT_PORT:-}"; do
        if [[ ! "$port" =~ ^[0-9]{1,5}$ ]]; then
            echo "ERROR: GPSD ports must be numbers from 1 to 65535" >&2
            return 1
        fi
        if (( 10#$port < 1 || 10#$port > 65535 )); then
            echo "ERROR: GPSD port out of range: $port" >&2
            return 1
        fi
    done

    if (( 10#$GPSD_INPUT_PORT == 10#$GPSD_CLIENT_PORT )); then
        echo "ERROR: GPSD input and client ports must differ" >&2
        return 1
    fi

    compose_profile_args+=(--profile gpsd)

    echo "Starting GPSD before the GNSS emulator"
    if ! $docker_compose_cmd "${compose_env_args[@]}" \
        -f "$docker_compose_file" "${compose_profile_args[@]}" \
        up -d --build --no-deps gpsd; then
        echo "ERROR: GPSD startup failed; aborting DT startup" >&2
        return 1
    fi

    local attempt
    for attempt in {1..30}; do
        if $docker_compose_cmd "${compose_env_args[@]}" \
            -f "$docker_compose_file" "${compose_profile_args[@]}" \
            exec -T gpsd python3 /opt/gpsd/healthcheck.py \
            >/dev/null 2>&1; then
            echo "GPSD is ready"
            return 0
        fi
        sleep 1
    done

    echo "ERROR: GPSD did not become ready; aborting DT startup" >&2
    $docker_compose_cmd "${compose_env_args[@]}" \
        -f "$docker_compose_file" "${compose_profile_args[@]}" \
        logs --tail 30 gpsd
    return 1
}
