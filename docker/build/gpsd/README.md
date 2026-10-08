# GPSD integration

## Purpose

Run GPSD as a Docker service and route GNSS emulator output through it.
GPSD startup is independent of automatic emulator startup, allowing
the emulator to be launched manually when the test coordinator is ready.

Data flow:

    Emulator TCP -> socat -> internal UDP 5001 -> GPSD -> clients

## Configuration

Defaults are in config/gpsd.config:

- GPSD_ENABLED=true
- HWIL_GNSS_OUTPUT_MODE=gpsd
- GPSD_INPUT_PORT=55000
- GPSD_CLIENT_BIND_ADDRESS=127.0.0.1
- GPSD_CLIENT_PORT=52947

These are the current investigation defaults. Site/scenario settings
loaded before this file can override them.

GPSD_ENABLED=false disables GPSD startup.
HWIL_GNSS_OUTPUT_MODE=direct preserves the emulator's original
HWIL_GNSS_EMULATOR_SEND_ADDRESS and SEND_PORT settings.
For operation without GPSD, configure both disabled and direct mode.

The current enable default applies wherever the modified startup
script loads this configuration; it is not restricted to RHWIL scenarios.

## Integrated startup

Run dt start using the intended site and scenario configuration.

The startup helper starts GPSD and checks readiness before the main
Compose startup. If readiness fails, startup exits with an error.
Inspect the GPSD container/logs afterward; it may remain running.

The emulator launcher loads GPSD settings after the normal configuration.
In gpsd mode it sends to 127.0.0.1:GPSD_INPUT_PORT.
This relies on dt-core using host networking.

Starting the emulator does not necessarily begin GNSS transmission.
Use the scenario and start-trigger procedure documented for the
installed radio-adapter version. Verify its actual command port.

## Standalone test service

From the repository root:

    bash docker/gpsd-test.sh start
    bash docker/gpsd-test.sh status
    bash docker/gpsd-test.sh logs
    bash docker/gpsd-test.sh stop

This uses project dt-gpsd-standalone-test and fixed loopback ports
55000 and 52947. Stop it before integrated startup using the same ports.

## Commsignia validation

Loopback binding prevents remote OBU access. For a coordinated device
test, set GPSD_CLIENT_BIND_ADDRESS to the host's reachable SDN address
and recreate the GPSD service with that setting.

On Commsignia, select the GPSD navigation source and configure the
host address and GPSD_CLIENT_PORT. For the current DT4 test this would
be 192.168.55.67 and 52947 after enabling that interface.

Verify live position, timestamps, and trajectory at the OBU.
Do not use historical replay data with OBU system-time adjustment.

## Validation evidence

Passed on DT4:
- Sample NMEA and recorded UBX decoding with the emulator-style prefix.
- Expected positions returned through host-published test ports.
- A new producer connection delivered a different NMEA position
  without restarting GPSD.
- GPSD launched through the modified dt start flow.

The sample tests used smoke_test.py and captured-ubx.hex from
~/gpsd-investigation/gpsd-udp-investigation/.
These fixtures are external prerequisites, not included in this image.
Recorded UBX timestamps are historical.

Pending:
- Full live TENA emulator-to-GPSD validation.
- Commsignia end-to-end validation using this Docker setup.
- Integrated shutdown, restart, and direct-mode fallback validation.

GPSD accepting reconnects does not prove the emulator automatically
reconnects. Container health checks establish listener readiness,
not valid GNSS data or a successful TENA session.

## Shutdown

The modified start-docker.sh signal handler includes the GPSD profile
when bringing down the DT Compose project.
It no longer passes -v, preserving Compose-managed volumes.
This affects shutdown of the full DT project, not just GPSD.
