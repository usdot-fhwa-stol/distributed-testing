#!/usr/bin/env python3
"""P2 - GPS Data Input.

    Requirement:  The GPS Emulator shall accept pre-computed simulated vehicle
                  trajectories as input.
    Criteria:     GPS Emulator accepts pre-computed simulated vehicle
                  trajectories.
    System:       GPS Emulator

WHAT THIS VERIFIES
------------------
This script walks through the GPS Emulator log file to verify that the trajectory 
information is accepted by the GPS emulator:
  1. Loaded a trajectory configuration file.
  2. Bounded the trajectory to this emulator's radio, by matching the radio
     identifier to a route entity identifier.
  3. Parsed the route waypoints, in a count matching the one the emulator
     itself reports, with strictly increasing times and real geometry.
  4. Resampled the route to the configured publish rate.
  5. Emitted positions that follow the trajectory it read.

Below is an example of how the log file looks like:

    [HWILgnssEmulator-1.0.0] NOTE: Route waypoint count: 61
    [HWILgnssEmulator-1.0.0] Route waypoint: absoluteNs=..., latitude=..., longitude=...
    [HWILgnssEmulator-1.0.0] NOTE: Resampling route at 10 Hz; interval=0.1 seconds.
    [HWILgnssEmulator-1.0.0] GGA: $GPGGA,204040.25,0000.0000,N,00000.0000,E,1,12,...

INPUT
-----
    ./verify_p2_trajectory_input.py gnss_log.txt

EXIT CODES
----------
    0  PASS     requirement met
    1  FAIL     requirement not met
    2  NO_DATA  log unreadable, or carries no trajectory
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

EARTH_RADIUS_M = 6_378_137.0
NMEA_LSB_DEGREES = 0.0001 / 60.0

DEFAULT_TOLERANCE_M = 1.0
DEFAULT_MIN_WAYPOINTS = 2

WAYPOINT_RE = re.compile(
    r"Route waypoint:\s*absoluteNs=(-?\d+),\s*relativeSeconds=(-?[\d.eE+-]+),"
    r"\s*latitude=(-?[\d.eE+-]+),\s*longitude=(-?[\d.eE+-]+)"
)
GGA_RE = re.compile(r"\$(G[PNLA]GGA),([^*\r\n]*)\*([0-9A-Fa-f]{2})")

CONFIG_FILE_RE = re.compile(r"Loading GNSS header from:\s*(\S+)")
MATCHED_RE = re.compile(
    r"Matched radio identifier '([^']+)' to route entity identifier '([^']+)'"
)
WAYPOINT_COUNT_RE = re.compile(r"Route waypoint count:\s*(\d+)")
RESAMPLE_RE = re.compile(
    r"Resampling route at\s*([\d.]+)\s*Hz;\s*interval=([\d.]+)\s*seconds"
)
RESAMPLED_COUNT_RE = re.compile(r"Resampled waypoint count:\s*(\d+)")
PUBLISH_RATE_RE = re.compile(r"-GNSSPublishRate\s+(\d+)")
ADAPTER_ID_RE = re.compile(r"-adapterId\s+(\S+)")
CONFIG_ARG_RE = re.compile(r"-gnssconfigFile\s+(\S+)")


@dataclass
class Ingest:
    """Everything the log says about how the trajectory was taken in.

    Attributes:
        config_file: Trajectory file the emulator loaded.
        config_arg: Trajectory file named on the command line.
        adapter_id: This emulator's adapter identifier.
        matched_radio: Radio identifier the route was bound to.
        matched_entity: Route entity identifier it was matched against.
        declared_waypoints: Waypoint count the emulator reported.
        resample_hz: Rate the route was resampled to.
        resample_interval_s: Resampling interval reported.
        resampled_count: Resampled waypoint count reported.
        publish_rate_hz: Configured publish rate.
        waypoints: Parsed (seconds, latitude, longitude) waypoints.
        positions: Emitted (latitude, longitude) positions.
        bad_checksums: Emitted sentences whose checksum failed.
    """

    config_file: str = ""
    config_arg: str = ""
    adapter_id: str = ""
    matched_radio: str = ""
    matched_entity: str = ""
    declared_waypoints: int | None = None
    resample_hz: float | None = None
    resample_interval_s: float | None = None
    resampled_count: int | None = None
    publish_rate_hz: int | None = None
    waypoints: list[tuple[float, float, float]] = field(default_factory=list)
    positions: list[tuple[float, float]] = field(default_factory=list)
    bad_checksums: int = 0


@dataclass
class Result:
    """Outcome of the P2 check."""

    status: str = "NO_DATA"
    summary: str = ""
    observations: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def checksum_ok(body: str, expected: str) -> bool:
    """Validates an NMEA checksum.

    Args:
        body: Sentence content between '$' and '*'.
        expected: Two hex digits after '*'.
    """
    value = 0
    for char in body:
        value ^= ord(char)
    return value == int(expected, 16)


def to_degrees(value: str, hemisphere: str) -> float | None:
    """Converts an NMEA ddmm.mmmm coordinate to decimal degrees.

    Args:
        value: Numeric coordinate field.
        hemisphere: One of N, S, E, W.
    """
    if not value or not hemisphere:
        return None
    try:
        numeric = float(value)
    except ValueError:
        return None
    degrees = int(numeric // 100)
    decimal = degrees + (numeric - degrees * 100) / 60.0
    return -decimal if hemisphere.upper() in ("S", "W") else decimal


def parse_log(path: Path) -> Ingest:
    """Reads the trajectory ingest sequence from the emulator log.

    Args:
        path: The emulator log file.

    Returns:
        Everything the log reports about ingest and output.
    """
    ingest = Ingest()
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            found = WAYPOINT_RE.search(line)
            if found:
                ingest.waypoints.append(
                    (
                        float(found.group(2)),
                        float(found.group(3)),
                        float(found.group(4)),
                    )
                )
                continue

            found = GGA_RE.search(line)
            if found:
                talker, body, checksum = found.group(1), found.group(2), found.group(3)
                if not checksum_ok(f"{talker},{body}", checksum):
                    ingest.bad_checksums += 1
                fields = body.split(",")
                if len(fields) >= 5:
                    lat = to_degrees(fields[1], fields[2])
                    lon = to_degrees(fields[3], fields[4])
                    if lat is not None and lon is not None:
                        ingest.positions.append((lat, lon))
                continue

            for pattern, attribute, cast in (
                (CONFIG_FILE_RE, "config_file", str),
                (CONFIG_ARG_RE, "config_arg", str),
                (ADAPTER_ID_RE, "adapter_id", str),
                (WAYPOINT_COUNT_RE, "declared_waypoints", int),
                (RESAMPLED_COUNT_RE, "resampled_count", int),
                (PUBLISH_RATE_RE, "publish_rate_hz", int),
            ):
                if getattr(ingest, attribute):
                    continue
                found = pattern.search(line)
                if found:
                    setattr(ingest, attribute, cast(found.group(1)))

            if not ingest.matched_radio:
                found = MATCHED_RE.search(line)
                if found:
                    ingest.matched_radio = found.group(1)
                    ingest.matched_entity = found.group(2)

            if ingest.resample_hz is None:
                found = RESAMPLE_RE.search(line)
                if found:
                    ingest.resample_hz = float(found.group(1))
                    ingest.resample_interval_s = float(found.group(2))
    return ingest


def distance_to_polyline_m(
    lat: float, lon: float, polyline: list[tuple[float, float]]
) -> float:
    """Shortest distance from a point to a polyline, in metres.

    Args:
        lat: Query latitude, decimal degrees.
        lon: Query longitude, decimal degrees.
        polyline: Ordered (latitude, longitude) vertices.
    """
    if not polyline:
        return math.inf
    per_lat = math.pi * EARTH_RADIUS_M / 180.0
    per_lon = per_lat * math.cos(math.radians(lat))
    if len(polyline) == 1:
        return math.hypot(
            (polyline[0][1] - lon) * per_lon, (polyline[0][0] - lat) * per_lat
        )
    best = math.inf
    for (lat1, lon1), (lat2, lon2) in zip(polyline, polyline[1:]):
        px, py = (lon - lon1) * per_lon, (lat - lat1) * per_lat
        sx, sy = (lon2 - lon1) * per_lon, (lat2 - lat1) * per_lat
        length_sq = sx * sx + sy * sy
        if length_sq == 0.0:
            best = min(best, math.hypot(px, py))
            continue
        t = max(0.0, min(1.0, (px * sx + py * sy) / length_sq))
        best = min(best, math.hypot(px - t * sx, py - t * sy))
    return best


def percentile(values: list[float], fraction: float) -> float:
    """Linear-interpolated percentile of a non-empty list.

    Args:
        values: Samples.
        fraction: Percentile as a fraction in [0, 1].
    """
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[int(position)]
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def quantization_floor_m(latitude: float) -> float:
    """Returns the two-axis NMEA coordinate rounding floor at a latitude.

    Args:
        latitude: Representative latitude, decimal degrees.
    """
    per_lat = math.pi * EARTH_RADIUS_M / 180.0
    per_lon = per_lat * math.cos(math.radians(latitude))
    return math.hypot(
        NMEA_LSB_DEGREES * per_lat / 2.0, NMEA_LSB_DEGREES * per_lon / 2.0
    )


def verify(ingest: Ingest, tolerance_m: float, min_waypoints: int) -> Result:
    """Walks the ingest path and judges whether the trajectory was accepted.

    Args:
        ingest: Everything parsed from the log.
        tolerance_m: Allowed maximum deviation of output from the trajectory.
        min_waypoints: Minimum waypoints for a route to define a path.

    Returns:
        The verification result.
    """
    result = Result()
    problems: list[str] = []

    # Refuse to judge a file that is not a GNSS emulator log. If none of the
    # ingest markers appear -- no config load, no radio binding, no waypoints
    # and no emitted positions -- the input is something else, and reporting
    # FAIL would accuse the emulator of a defect that was never observed.
    if not any(
        (
            ingest.config_file,
            ingest.config_arg,
            ingest.matched_radio,
            ingest.waypoints,
            ingest.positions,
            ingest.declared_waypoints,
        )
    ):
        result.observations.append(
            "This input contains none of the markers a GNSS emulator log "
            "carries: no trajectory file load, no radio-to-route binding, no "
            "`Route waypoint:` lines and no emitted NMEA."
        )
        result.observations.append(
            "It does not look like a GNSS emulator log, so no verdict on P2 is "
            "possible. Pass the emulator's own log file."
        )
        result.summary = "Input is not a GNSS emulator log; nothing to evaluate."
        return result

    # --- Stage 1: a trajectory file was loaded
    loaded = ingest.config_file or ingest.config_arg
    if loaded:
        result.observations.append(f"[1] Loaded trajectory file: {loaded}")
        result.metrics["trajectory_file"] = loaded
        if (
            ingest.config_file
            and ingest.config_arg
            and ingest.config_file != ingest.config_arg
        ):
            result.observations.append(
                f"    NOTE: the file loaded ({ingest.config_file}) differs from "
                f"the one requested on the command line ({ingest.config_arg})."
            )
    else:
        result.observations.append(
            "[1] No trajectory file load was recorded in the log."
        )
        problems.append("no trajectory configuration file was loaded")

    # --- Stage 2: bound to this emulator's radio
    if ingest.matched_radio:
        result.observations.append(
            f"[2] Matched radio {ingest.matched_radio!r} to route entity "
            f"{ingest.matched_entity!r}."
        )
        result.metrics["matched_radio"] = ingest.matched_radio
        result.metrics["matched_entity"] = ingest.matched_entity
        if ingest.adapter_id and ingest.adapter_id != ingest.matched_radio:
            result.observations.append(
                f"    NOTE: this adapter is {ingest.adapter_id!r} but the route "
                f"was bound to {ingest.matched_radio!r}."
            )
    else:
        result.observations.append(
            "[2] No radio-to-route binding was recorded; the emulator did not "
            "associate a trajectory with itself."
        )
        problems.append("no route was bound to this emulator's radio")

    # --- Stage 3: waypoints parsed, and consistent with the declared count
    count = len(ingest.waypoints)
    result.observations.append(
        f"[3] Parsed {count} route waypoint(s)"
        + (
            f"; the emulator declared {ingest.declared_waypoints}."
            if ingest.declared_waypoints is not None
            else "."
        )
    )
    result.metrics["waypoints_parsed"] = count
    if ingest.declared_waypoints is not None:
        result.metrics["waypoints_declared"] = ingest.declared_waypoints
        if count != ingest.declared_waypoints:
            problems.append(
                f"parsed {count} waypoint(s) but the emulator declared "
                f"{ingest.declared_waypoints}"
            )

    if count < min_waypoints:
        problems.append(
            f"{count} waypoint(s) is below the minimum of {min_waypoints} "
            "needed to define a path"
        )
    else:
        times = [t for t, _lat, _lon in ingest.waypoints]
        non_monotonic = [
            i for i in range(1, len(times)) if times[i] <= times[i - 1]
        ]
        if non_monotonic:
            problems.append(
                "waypoint times are not strictly increasing at index/indices "
                f"{non_monotonic[:5]}"
            )
        else:
            span = times[-1] - times[0]
            result.observations.append(
                f"    Trajectory spans {span:.1f} s, times strictly increasing."
            )
            result.metrics["trajectory_span_s"] = round(span, 3)
        if all(lat == 0.0 and lon == 0.0 for _t, lat, lon in ingest.waypoints):
            problems.append("every waypoint is (0, 0); the trajectory has no geometry")

    # --- Stage 4: resampled to the publish rate
    if ingest.resample_hz is not None:
        result.observations.append(
            f"[4] Resampled at {ingest.resample_hz:g} Hz "
            f"(interval {ingest.resample_interval_s:g} s)"
            + (
                f" to {ingest.resampled_count} point(s)."
                if ingest.resampled_count is not None
                else "."
            )
        )
        result.metrics["resample_hz"] = ingest.resample_hz
        if ingest.resampled_count is not None:
            result.metrics["resampled_count"] = ingest.resampled_count
        if (
            ingest.publish_rate_hz is not None
            and abs(ingest.resample_hz - ingest.publish_rate_hz) > 1e-6
        ):
            result.observations.append(
                f"    NOTE: resample rate {ingest.resample_hz:g} Hz differs from "
                f"the configured publish rate {ingest.publish_rate_hz} Hz."
            )
    else:
        result.observations.append("[4] No resampling step was recorded.")

    # --- Stage 5: output follows the trajectory
    result.observations.append(
        f"[5] Emitted {len(ingest.positions)} position(s)"
        + (
            f"; {ingest.bad_checksums} checksum failure(s)."
            if ingest.bad_checksums
            else " with no checksum failures."
        )
    )
    result.metrics["positions_emitted"] = len(ingest.positions)
    result.metrics["checksum_failures"] = ingest.bad_checksums

    if ingest.resampled_count and ingest.positions:
        shortfall = ingest.resampled_count - len(ingest.positions)
        if shortfall > 0:
            result.observations.append(
                f"    NOTE: {shortfall} fewer position(s) emitted than the "
                f"{ingest.resampled_count} resampled point(s). Expected if the "
                "log was captured before the run finished; investigate if not."
            )

    followed = False
    if count >= min_waypoints and ingest.positions:
        polyline = [(lat, lon) for _t, lat, lon in ingest.waypoints]
        errors = [
            distance_to_polyline_m(lat, lon, polyline)
            for lat, lon in ingest.positions
        ]
        median = percentile(errors, 0.5)
        p95 = percentile(errors, 0.95)
        worst = max(errors)
        mean_lat = sum(lat for lat, _lon in ingest.positions) / len(ingest.positions)
        floor = quantization_floor_m(mean_lat)
        result.observations.append(
            f"    Output vs trajectory: median {median:.4f} m, p95 {p95:.4f} m, "
            f"max {worst:.4f} m (NMEA rounding floor {floor:.3f} m)."
        )
        result.metrics["deviation_median_m"] = round(median, 4)
        result.metrics["deviation_p95_m"] = round(p95, 4)
        result.metrics["deviation_max_m"] = round(worst, 4)
        result.metrics["quantization_floor_m"] = round(floor, 4)
        if tolerance_m < floor:
            result.observations.append(
                f"    NOTE: tolerance {tolerance_m:.3f} m is below the "
                f"{floor:.3f} m NMEA rounding floor and cannot be met."
            )
        if worst <= tolerance_m:
            followed = True
            if worst <= floor * 1.5:
                result.observations.append(
                    "    The deviation is at the rounding floor: the emulator "
                    "reproduced the trajectory as closely as NMEA can express."
                )
        else:
            problems.append(
                f"emitted positions depart the parsed trajectory by up to "
                f"{worst:.4f} m, beyond the {tolerance_m:.3f} m tolerance"
            )
    elif not ingest.positions:
        problems.append(
            "the emulator emitted no positions, so the trajectory was ingested "
            "but never acted on"
        )

    result.metrics["tolerance_m"] = tolerance_m

    if problems:
        for problem in problems:
            result.observations.append(f"PROBLEM: {problem}")
        result.status = "FAIL"
        result.summary = "; ".join(problems)
        return result

    if not followed:
        result.summary = (
            "Trajectory was ingested, but there was not enough output to "
            "confirm the emulator acted on it."
        )
        return result

    result.status = "PASS"
    result.summary = (
        f"The emulator loaded a {count}-waypoint pre-computed trajectory, bound "
        f"it to radio {ingest.matched_radio!r}, resampled it, and emitted "
        f"{len(ingest.positions)} position(s) following it within "
        f"{result.metrics['deviation_max_m']:.4f} m."
    )
    return result


def render(result: Result, verbose: bool) -> None:
    """Prints the result.

    Args:
        result: Verification result.
        verbose: Whether to print metrics.
    """
    print()
    print("P2 - GPS Data Input (pre-computed trajectories)")
    print("=" * 68)
    print(f"  Result: {result.status}")
    print(f"  {result.summary}")
    print()
    for note in result.observations:
        print(f"    - {note}")
    if verbose and result.metrics:
        print()
        print("  Metrics:")
        for key, value in result.metrics.items():
            print(f"    {key} = {value}")
    print()


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments, or None to read from sys.argv.

    Returns:
        Exit code: 0 PASS, 1 FAIL, 2 NO_DATA.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Verify P2: the GPS Emulator accepts pre-computed simulated "
            "vehicle trajectories as input."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Walks the emulator's log through load, bind, parse, resample and\n"
            "emit, then checks the emitted track follows the parsed trajectory."
        ),
    )
    parser.add_argument("log", type=Path, help="GNSS emulator log file.")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_TOLERANCE_M,
        metavar="METRES",
        help=(
            "Maximum allowed deviation of emitted positions from the parsed "
            f"trajectory (default: {DEFAULT_TOLERANCE_M})."
        ),
    )
    parser.add_argument(
        "--min-waypoints",
        type=int,
        default=DEFAULT_MIN_WAYPOINTS,
        help=f"Minimum waypoints for a path (default: {DEFAULT_MIN_WAYPOINTS}).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead.")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Also print metrics."
    )
    args = parser.parse_args(argv)

    if not args.log.is_file():
        print(f"Log not found: {args.log}", file=sys.stderr)
        return 2

    try:
        ingest = parse_log(args.log)
    except OSError as exc:
        print(f"Could not read {args.log}: {exc}", file=sys.stderr)
        return 2

    result = verify(ingest, args.tolerance, args.min_waypoints)
    result.metrics["log"] = str(args.log)

    if args.json:
        print(
            json.dumps(
                {
                    "requirement": "P2",
                    "title": "GPS Data Input (pre-computed trajectories)",
                    "status": result.status,
                    "summary": result.summary,
                    "observations": result.observations,
                    "metrics": result.metrics,
                },
                indent=2,
                default=str,
            )
        )
    else:
        render(result, args.verbose)

    return {"PASS": 0, "FAIL": 1}.get(result.status, 2)


if __name__ == "__main__":
    raise SystemExit(main())