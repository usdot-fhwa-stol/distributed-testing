# GPSD integration developer guide

## Overview

Run GPSD alongside the DT services to provide navigation to GPSD clients.
The GNSS emulator sends NMEA or UBX over TCP. An internal bridge forwards
that stream to GPSD over UDP.

Default data flow:

    Emulator -> host TCP 51928 -> container TCP 51928
             -> internal UDP 5001 -> GPSD
             -> container TCP 2947 -> host TCP 52947 -> client

GPSD startup is independent of automatic emulator startup. The emulator
can be started manually when the test coordinator is ready.

## Prerequisites

- A working Distributed Testing installation and Docker.
- Docker Compose with profiles support. The standalone test wrapper also
  requires support for `up --wait`.
- An installed GNSS emulator supporting the selected NMEA/UBX format.
- A configured scenario, trajectory, matching adapter ID, and reachable
  TENA Execution Manager (EM) for the live emulator test.
- For external clients, network access to the host's GPSD client endpoint.

Container health confirms listener readiness, not valid position data,
an EM connection, or reception by an external device.

## Configuration

Defaults are defined in `config/gpsd.config`:

| Variable | Default | Purpose |
| --- | --- | --- |
| GPSD_ENABLED | true | Enable GPSD startup preparation |
| HWIL_GNSS_OUTPUT_MODE | gpsd | Select GPSD routing or direct output |
| GPSD_INPUT_PORT | 51928 | Host TCP input from the emulator |
| GPSD_CLIENT_BIND_ADDRESS | 127.0.0.1 | Host interface for GPSD clients |
| GPSD_CLIENT_PORT | 52947 | Host TCP port for GPSD clients |

The configuration supplies defaults for unset or empty variables.
Site/scenario values loaded beforehand take precedence. The emulator
also loads its Docker configuration overrides before these defaults.

Persist test overrides in the selected local site/scenario configuration
so the host startup script and container launcher use matching settings.
Do not commit machine-specific addresses or test changes to shared defaults.

For remote clients, set GPSD_CLIENT_BIND_ADDRESS to a host interface
reachable from the client. Loopback permits local clients only.

In gpsd mode, the launcher sends to 127.0.0.1:GPSD_INPUT_PORT. This requires
dt-core to use host networking. The container input listener remains 51928;
changing GPSD_INPUT_PORT changes the published host port.

For operation without GPSD, configure both:

    export GPSD_ENABLED=false
    export HWIL_GNSS_OUTPUT_MODE=direct

Direct mode preserves HWIL_GNSS_EMULATOR_SEND_ADDRESS and
HWIL_GNSS_EMULATOR_SEND_PORT. Selecting gpsd output while GPSD_ENABLED
is false causes the emulator launcher to fail.

GPSD is enabled by default wherever this startup configuration is loaded;
it is not restricted to one scenario. Direct mode skips GPSD preparation.

## Integrated test procedure

### 1. Select the configuration ? host terminal

From the repository root:

```bash
dt config set
source ~/.bashrc
readlink -f ~/.dt_site_config ~/.dt_scenario_config
```

Select the intended local site and HWIL scenario. Verify the EM endpoint,
local address, installed emulator version, adapter ID, trajectory/config
file, and GNSS_TYPE.

Choose either automatic emulator startup or a manual launch:
- Automatic: enable VUG_DOCKER_START_GNSS_EMULATOR.
- Manual: disable that flag and enable another required DT core application
  so dt-core starts. Launch the emulator in step 4.

Check that the configured host ports are available. For the defaults:

```bash
ss -ltnp | grep -E ':(51928|52947)\b'
```

Investigate any existing listeners. Do not stop unrelated host services.
Stop the standalone GPSD test before integrated startup on the same ports.

Use a fresh terminal after changing configuration. Existing exported
values can retain an old port even after a default is edited.

### 2. Start DT ? host terminal A

```bash
dt start
```

Confirm the selected configurations. Expect "GPSD is ready" before the
main services start. Leave this terminal running.

If GPSD preparation fails, inspect its container and logs. The container
may remain present after the startup helper reports failure.

### 3. Observe GPSD ? host terminal B

Find the container belonging to the current DT run:

```bash
docker ps --filter label=com.docker.compose.service=gpsd \
  --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
read -r -p 'GPSD container name: ' GPSD_CONTAINER
docker inspect "$GPSD_CONTAINER" --format '{{.State.Health.Status}}'
docker port "$GPSD_CONTAINER"
docker exec "$GPSD_CONTAINER" timeout 120 gpspipe -w
```

Expect a healthy container and the configured published ports.
Container names depend on the Compose project.

VERSION, DEVICES, and WATCH messages establish a client connection;
they do not prove live position delivery. Start this reader before
triggering the trajectory. Exit code 124 is expected when timeout expires.

### 4. Launch the emulator ? host terminal C

Check for an existing emulator:

```bash
pgrep -af '[t]ena-gnss-emulator'
```

Do not start a duplicate if it is already running for this test.
For a manual launch:

```bash
dt exec
```

Then run inside the container:

```bash
bash "$HOME/distributed-testing/scripts/run_scripts/start-gnss-emulator.sh"
```

With the defaults, expect:

    GNSS destination: 127.0.0.1:51928

Leave the emulator running. Verbosity is 1, so detailed packet output
is not required for a successful run.

### 5. Trigger the trajectory ? another host terminal

Follow the installed radio adapter's README. For versions supporting
UDP start/stop commands, identify the actual command listener:

```bash
pgrep -af '[t]ena-gnss-emulator'
ss -lunp
```

Find the UDP address and port owned by the emulator. The command port
is separate from the TCP producer port and may vary by adapter version.

Send the documented start command:

```bash
read -r -p 'Emulator command IP address: ' COMMAND_ADDRESS
read -r -p 'Emulator UDP command port: ' COMMAND_PORT
python3 - "$COMMAND_ADDRESS" "$COMMAND_PORT" <<'PY'
import socket
import sys

with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
    sender.sendto(b"start", (sys.argv[1], int(sys.argv[2])))
print("Start command sent; verify reception separately.")
PY
```

If the listener shows a wildcard address, use a reachable local interface
address as the destination.

In terminal B, verify TPV reports with valid positions and advancing
timestamps. Compare multiple positions with the configured trajectory.
Compare reported UTC time against `date -u`.

Repeat with each required GNSS format, stopping the manually launched
emulator before changing its configuration and relaunching it.

### 6. Verify an external GPSD client

Record the client's original settings. Configure its navigation source
as GPSD, with the host's reachable client-interface address and
GPSD_CLIENT_PORT. Save/apply using the device's documented procedure.

Confirm docker port shows the expected interface and port. A published
binding change requires container recreation; restarting alone does
not apply it.

Open the client's live navigation status and trigger a fresh trajectory.
Verify:
- Navigation becomes valid.
- Timestamps advance.
- Positions change consistently with the route and GPSD TPV reports.

Saved connection settings alone do not demonstrate reception. Verify
source time before enabling device system-time adjustment, especially
when using recorded input.

Keep device-specific setup, lab addresses, screenshots, recordings, and
actual results in the team's integration-test documentation.

### 7. Verify producer reconnection

Record GPSD's container identity and state in terminal B:

```bash
docker inspect "$GPSD_CONTAINER" \
  --format '{{.Id}} {{.State.StartedAt}} {{.RestartCount}}'
```

Stop only the manually launched emulator using Ctrl+C in terminal C.
Keep dt start running. Relaunch the emulator, start a new GPSD reader,
and trigger another trajectory.

Confirm fresh position reports and external-client updates. Repeat the
inspection and confirm GPSD's ID, start time, and restart count are unchanged.

This checks acceptance of a new producer connection. It does not prove
the emulator reconnects automatically after a network interruption.

### 8. Verify shutdown and restart

Coordinate this check because it stops the full DT project.

Stop the manually launched emulator, then press Ctrl+C in terminal A
running foreground dt start. Check docker ps -a and confirm the recorded
GPSD container was removed along with the intended DT services.

Start DT again and repeat readiness and live-position checks.

The shutdown handler includes GPSD and uses Compose down without -v,
preserving Compose-managed named volumes. This affects the whole project.
Detached startup and other shutdown entry points require separate checks.

### 9. Verify direct-mode fallback

After stopping the test stack, set GPSD_ENABLED=false and
HWIL_GNSS_OUTPUT_MODE=direct in the selected local configuration.
Configure the intended direct receiver address and port.

Restart DT. Verify the helper does not start GPSD, and the emulator's
printed destination matches the configured direct receiver.
Verify delivery at that receiver when available.

Restore the intended operating configuration after testing.
Disabling GPSD does not itself stop an already-running container.

## Standalone readiness test

From the repository root:

```bash
bash docker/gpsd-test.sh start
bash docker/gpsd-test.sh status
bash docker/gpsd-test.sh logs
bash docker/gpsd-test.sh stop
```

This uses project dt-gpsd-standalone-test with fixed loopback ports
51928 and 52947. Do not run it beside integrated GPSD using those ports.

The wrapper checks service readiness; it does not generate positions.
Live-emulator or separate test-producer input is required for data tests.
Historical replay fixtures are not included.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Only VERSION/DEVICES/WATCH | Start the reader before triggering; verify emulator, scenario, EM connection, and destination. |
| Port conflict | Inspect host listeners and other GPSD containers. |
| Healthy container but no fix | Health confirms listeners only; inspect incoming data and TPV reports. |
| External client has invalid navigation | Check interface/port, reachability, fresh data, source time, and client fix requirements. |
| Old dates | Inspect encoder time fields; track permanent emulator timestamp fixes separately. |
| Repeated VERSION/EOF logs | Health checks periodically connect and disconnect. |
| Old producer port persists | Check loaded configuration, exported values, actual arguments, and published ports. |
| Rebuilt emulator not used | Check the executable path and container mounts. |

The bridge accepts subsequent producer connections. If GPSD or the bridge
listener exits, the entrypoint exits; integrated Compose uses the
unless-stopped restart policy. Container recovery and client recovery
must be validated separately.
