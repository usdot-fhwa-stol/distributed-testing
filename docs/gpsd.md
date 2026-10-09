# GPSD developer guide

## Architecture

GPSD and its TCP-to-UDP bridge run inside dt-core. No separate GPSD
container or published Docker port mapping is required because dt-core
uses host networking.

Default data flow:

    GNSS emulator
      -> configured host address, TCP 51928
      -> socat bridge
      -> loopback UDP 5001
      -> GPSD
      -> host TCP 52947
      -> GPSD clients

GPSD runs independently of automatic emulator startup. Other DT
applications can initialize while GPSD starts. Automatic emulator launch
waits for GPSD readiness.

## Image and runtime requirements

Use a published dt-core image containing:

- gpsd and gpsd-tools
- socat
- python3
- util-linux, providing setsid
- the updated startup-apps.sh and start-gpsd.sh scripts

These changes must be included in the project's normal dt-core image
build and Harbor publication process. An older image does not acquire
the packages or startup scripts simply by updating the repository.

Normal users should use the published image; building an image is a
developer/release task. Do not add local development mounts to the shared
Compose file.

The installed GNSS emulator must support the selected NMEA/UBX format,
the configured scenario, and its documented start/stop mechanism.

## Site configuration

GPSD settings belong in the selected site configuration.

| Setting | Default | Purpose |
| --- | --- | --- |
| GPSD_ENABLED | true | Start GPSD inside dt-core |
| HWIL_GNSS_OUTPUT_MODE | gpsd | Route emulator output through GPSD |
| GPSD_INPUT_ADDRESS | empty | Use effective VUG_LOCAL_ADDRESS |
| GPSD_INPUT_PORT | 51928 | TCP bridge listener |
| GPSD_CLIENT_PORT | 52947 | GPSD client TCP listener |
| GPSD_UDP_PORT | 5001 | Loopback UDP connection between bridge and GPSD |

Site/scenario configuration and Docker overrides are loaded before the
service starts. An empty GPSD_INPUT_ADDRESS selects VUG_LOCAL_ADDRESS
after those overrides.

The bridge listens on the selected input address. GPSD uses -G to listen
for clients on all host interfaces, not exclusively VUG_LOCAL_ADDRESS.
Clients should connect using the appropriate reachable host address.
No Docker port translation occurs.

All ports must be integers from 1 to 65535. Input and client TCP ports
must differ. The configured listeners must not conflict with other host
services, including an existing host GPSD installation.

GPSD_ENABLED=true enables the dt-core profile even if no other core
application is selected. Existing site files without this setting do not
automatically enable the service.

For direct emulator output without GPSD, use:

    export GPSD_ENABLED=false
    export HWIL_GNSS_OUTPUT_MODE="direct"

Direct mode preserves HWIL_GNSS_EMULATOR_SEND_ADDRESS and
HWIL_GNSS_EMULATOR_SEND_PORT. GPSD enablement is independent of output
mode: direct mode does not disable GPSD when GPSD_ENABLED remains true.

Keep lab-specific settings in local site configuration and internal test
documentation. Do not commit machine-specific addresses or credentials.

## Integrated test procedure

### 1. Configure the participant ? host terminal

From the repository root:

```bash
dt config set
source ~/.bashrc
```

Select the intended site and scenario. Confirm GPSD settings, local
address, EM endpoint, emulator version, adapter ID, GNSS configuration
file, and GNSS_TYPE.

For a manual test, set VUG_DOCKER_START_GNSS_EMULATOR=false.
For automatic launch, set it to true and skip the manual launch below.

Check TCP and UDP listeners before starting DT:

```bash
ss -ltnp
ss -lunp
```

Confirm the selected input, client, and UDP bridge ports are available.
Coordinate use of shared services and devices. Do not stop unrelated
listeners to free ports without identifying them.

When migrating from the separate-container implementation, stop its old
GPSD container during the agreed switchover. Removing its Compose
definition alone does not stop an existing container.

### 2. Start DT ? host terminal A

```bash
dt start
```

Confirm the selected configuration. Expect STARTING GPSD and a
GPSD ready message showing the configured producer address and client
port. Leave this terminal running.

GPSD and bridge process failures during initialization cause readiness
to fail. Readiness confirms listeners and the GPSD VERSION response;
it does not confirm valid position data or an EM connection.

### 3. Observe GPSD ? host terminal B

```bash
docker logs --tail 100 dt-core
```

Use the configured GPSD client port when observing data. For the default:

```bash
docker exec -i dt-core python3 -u - <<'PY'
import socket
import time

deadline = time.monotonic() + 120
with socket.create_connection(("127.0.0.1", 52947), timeout=5) as client:
    client.sendall(b'?WATCH={"enable":true,"json":true};\n')
    client.settimeout(1)
    pending = b""
    while time.monotonic() < deadline:
        try:
            data = client.recv(65536)
        except socket.timeout:
            continue
        if not data:
            print("GPSD closed the connection.")
            break
        pending += data
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            print(line.decode("utf-8", errors="replace"))
PY
```

Start the reader before triggering the trajectory.

VERSION, DEVICES, and WATCH responses alone are not position reports.
Expect TPV reports once the emulator sends data. The Python reader exits after its 120-second observation window.

### 4. Launch the emulator ? host terminal C

Check for an existing emulator before starting another:

```bash
pgrep -af '[t]ena-gnss-emulator'
```

For manual startup:

```bash
dt exec
```

Inside the container:

```bash
bash "$HOME/distributed-testing/scripts/run_scripts/start-gnss-emulator.sh"
```

Confirm the printed destination matches the configured bridge address
and input port. Leave the emulator running. Normal verbosity is 1;
detailed packet logging is not required for a successful run.

Starting the emulator may only make it ready to accept a start command.

### 5. Trigger a trajectory ? another host terminal

Follow the installed radio adapter's README. For versions using UDP
start/stop commands, identify the actual listener:

```bash
pgrep -af '[t]ena-gnss-emulator'
ss -lunp
```

The emulator command port is separate from the GPSD TCP input port.
Do not assume a fixed command port across adapter versions.

```bash
read -r -p 'Emulator command IP address: ' COMMAND_ADDRESS
read -r -p 'Emulator UDP command port: ' COMMAND_PORT
python3 - "$COMMAND_ADDRESS" "$COMMAND_PORT" <<'PY'
import socket
import sys

with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
    sender.sendto(b"start", (sys.argv[1], int(sys.argv[2])))
print("Start command sent; verify position reports separately.")
PY
```

For a wildcard listener, send to a reachable local interface address.

Verify TPV reports contain valid coordinates and advancing timestamps.
Compare several positions with the configured trajectory and compare
reported UTC time against date -u.

Repeat with each required GNSS format, stopping the manually launched
emulator before changing its configuration and relaunching it.

### 6. Verify a remote GPSD client

Record the client's original settings. Configure its navigation source
as GPSD and select the host's reachable address and GPSD_CLIENT_PORT.
Apply changes using the device's documented procedure.

Open the client's live navigation status, start the GPSD reader, and
trigger a fresh trajectory. Verify:

- Navigation becomes valid.
- Timestamps advance.
- Positions change consistently with the route and GPSD TPV reports.

Saved connection settings or a TCP connection alone do not prove that
the device accepts navigation data.

Check source time before enabling device system-time adjustment,
especially when replaying historical data.

Store device-specific instructions, addresses, screenshots, recordings,
and actual test results in the team's integration-testing documentation.

### 7. Verify producer reconnection

Keep DT running. Record dt-core's container identity and GPSD process:

```bash
docker inspect dt-core \
  --format '{{.Id}} {{.State.StartedAt}} {{.RestartCount}}'
docker exec dt-core pgrep -ax gpsd
```

Stop only the manually launched emulator with Ctrl+C in its terminal.
Relaunch it, start another GPSD reader, and trigger a new trajectory.

Verify fresh positions and external-client updates. Repeat the
inspection and confirm the container and GPSD process did not restart.

This checks a new producer connection, not automatic emulator recovery
after a network interruption.

### 8. Verify shutdown and restart

This stops the full DT project; coordinate the test window.

Stop the manually launched emulator. Press Ctrl+C in terminal A running
foreground dt start. Verify dt-core is removed and the GPSD TCP/UDP
listeners are no longer present.

Start DT again and repeat readiness and fresh-position checks.

The GPSD launcher manages separate process groups for GPSD and the
forking bridge. Its cleanup terminates those groups. dt-core's cleanup
also signals and waits for the launcher.

The current foreground DT shutdown preserves Compose-managed named
volumes. Detached startup and other stop entry points require separate
validation.

### 9. Verify direct-mode fallback

Stop the stack, disable GPSD, and select direct output in the local site
configuration. Set the direct receiver's address and port.

Ensure dt-core is enabled by the emulator or another required core
application. Restart DT and verify no GPSD service starts. Launch the
emulator and verify its printed destination matches the direct settings.
Verify delivery at the receiver when available.

Restore the intended operating configuration afterward.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Required command missing | The dt-core image must include the GPSD dependencies. |
| No STARTING GPSD message | Check the selected site settings, dev mode, and image startup-script version. |
| Port already in use | Inspect TCP/UDP listeners and any old standalone GPSD container. |
| Readiness fails | Check configured addresses, ports, process exits, and dt-core logs. |
| Only VERSION/DEVICES/WATCH | Check emulator state, scenario/EM connection, destination, and start trigger. |
| Remote client has invalid navigation | Check reachability, fresh TPV data, fix quality, time, and device requirements. |
| Old dates | Inspect emulator time fields; permanent encoder fixes are separate from GPSD integration. |
| New emulator build not used | Verify the executable supplied by the image or an explicit local development override. |

GPSD readiness is not a continuous navigation-quality check. The launcher
logs and exits if GPSD or the bridge listener exits. Other applications
may keep dt-core running, so container uptime alone does not prove GPSD
is still available. Check logs and the actual listener/data path.
