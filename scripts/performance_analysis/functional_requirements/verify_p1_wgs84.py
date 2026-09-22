#!/usr/bin/env python3
"""P1 - Coordinate systems.

    Requirement:  All positions shall be described using the WGS 84 coordinate
                  system.
    Criteria:     GPS Emulator positions conform to WGS84 coordinate system.
    System:       GPS Emulator

WHAT THIS VERIFIES
------------------
That the positions the GPS emulator emits are well-formed WGS 84 coordinates,
and that they agree with the WGS 84 route it was given.

The log file being used to verify this functionality is the log file from the
GPS Emulator. It contains both the route information in the following format:

    [HWILgnssEmulator-1.0.0] Route waypoint: absoluteNs=..., latitude=..., longitude=...
    [HWILgnssEmulator-1.0.0] GGA: $GPGGA,204040.25,0000.0000,N,00000.0000,E,1,12,...

This script is verifying that each emitted position parses as valid 
WGS 84 coordinate (which is essentially just a normal coordinate system with degrees, minutes, seconds)

INPUT
-----
The GNSS emulator's log:

    ./verify_p1_wgs84.py gnss_log.txt

EXIT CODES
----------
    0  PASS     requirement met
    1  FAIL     requirement not met
    2  NO_DATA  log unreadable, or carries no positions
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

# One NMEA coordinate least-significant digit is 0.0001 minute of arc.
NMEA_LSB_DEGREES = 0.0001 / 60.0

# Default tolerance for output-versus-route agreement. Chosen just above the
# two-axis NMEA quantization floor so rounding alone cannot fail the check.
DEFAULT_TOLERANCE_M = 1.0

WAYPOINT_RE = re.compile(
    r"Route waypoint:\s*absoluteNs=(-?\d+),\s*relativeSeconds=(-?[\d.eE+-]+),"
    r"\s*latitude=(-?[\d.eE+-]+),\s*longitude=(-?[\d.eE+-]+)"
)
# Position-bearing NMEA sentences the emulator may emit.
GGA_RE = re.compile(r"\$(G[PNLA]GGA),([^*\r\n]*)\*([0-9A-Fa-f]{2})")
RMC_RE = re.compile(r"\$(G[PNLA]RMC),([^*\r\n]*)\*([0-9A-Fa-f]{2})")
GLL_RE = re.compile(r"\$(G[PNLA]GLL),([^*\r\n]*)\*([0-9A-Fa-f]{2})")

GNSS_TYPE_RE = re.compile(r"-gnssType\s+(\S+)")
PUBLISH_RATE_RE = re.compile(r"-GNSSPublishRate\s+(\d+)")
ADAPTER_ID_RE = re.compile(r"-adapterId\s+(\S+)")


@dataclass
class Position:
    """One emitted position.

    Attributes:
        kind: Sentence type, "GGA", "RMC" or "GLL".
        time_field: Time-of-day field as transmitted.
        latitude: Decimal degrees, positive north.
        longitude: Decimal degrees, positive east.
        fix_quality: GGA fix quality indicator, when applicable.
        checksum_ok: Whether the sentence checksum validated.
        raw: The matched sentence text.
        problem: Why the coordinate was rejected, when applicable.
    """

    kind: str
    time_field: str
    latitude: float | None
    longitude: float | None
    fix_quality: int | None
    checksum_ok: bool
    raw: str
    problem: str = ""


@dataclass
class Result:
    """Outcome of the P1 check."""

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


def parse_coordinate(
    value: str, hemisphere: str, is_latitude: bool
) -> tuple[float | None, str]:
    """Parses an NMEA ddmm.mmmm coordinate, validating it structurally.

    Args:
        value: Numeric coordinate field as transmitted.
        hemisphere: One of N, S, E, W.
        is_latitude: True for latitude, which uses two degree digits and is
            bounded at 90; False for longitude, three digits and 180.

    Returns:
        Tuple of (decimal degrees or None, problem description).
    """
    if not value:
        return None, "empty coordinate field"
    expected = "NS" if is_latitude else "EW"
    if hemisphere not in expected:
        return None, f"hemisphere {hemisphere!r} is not one of {expected}"
    try:
        numeric = float(value)
    except ValueError:
        return None, f"coordinate {value!r} is not numeric"
    if numeric < 0:
        return None, "coordinate field is negative; sign belongs in the hemisphere"

    degrees = int(numeric // 100)
    minutes = numeric - degrees * 100
    # Minutes are sixtieths: a field like 0075.0000 is malformed, not 75 minutes.
    if minutes >= 60.0:
        return None, f"minutes field {minutes:.4f} is not below 60"
    decimal = degrees + minutes / 60.0
    limit = 90.0 if is_latitude else 180.0
    if decimal > limit:
        return None, f"{'latitude' if is_latitude else 'longitude'} {decimal} exceeds {limit}"
    if hemisphere in "SW":
        decimal = -decimal
    return decimal, ""


def parse_log(path: Path) -> tuple[list[tuple[float, float, float]], list[Position], dict]:
    """Reads route waypoints, emitted positions and configuration from the log.

    Args:
        path: The emulator log file.

    Returns:
        Tuple of (waypoints as (seconds, lat, lon), positions, configuration).
    """
    waypoints: list[tuple[float, float, float]] = []
    positions: list[Position] = []
    config: dict = {}

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not config.get("gnss_type"):
                found = GNSS_TYPE_RE.search(line)
                if found:
                    config["gnss_type"] = found.group(1)
            if not config.get("publish_rate_hz"):
                found = PUBLISH_RATE_RE.search(line)
                if found:
                    config["publish_rate_hz"] = int(found.group(1))
            if not config.get("adapter_id"):
                found = ADAPTER_ID_RE.search(line)
                if found:
                    config["adapter_id"] = found.group(1)

            found = WAYPOINT_RE.search(line)
            if found:
                waypoints.append(
                    (
                        float(found.group(2)),
                        float(found.group(3)),
                        float(found.group(4)),
                    )
                )
                continue

            for pattern, kind in (
                (GGA_RE, "GGA"),
                (RMC_RE, "RMC"),
                (GLL_RE, "GLL"),
            ):
                match = pattern.search(line)
                if not match:
                    continue
                talker, body, checksum = match.group(1), match.group(2), match.group(3)
                ok = checksum_ok(f"{talker},{body}", checksum)
                fields = body.split(",")
                lat = lon = None
                quality = None
                problem = ""
                if kind == "GGA" and len(fields) >= 6:
                    lat, problem = parse_coordinate(fields[1], fields[2], True)
                    if not problem:
                        lon, problem = parse_coordinate(fields[3], fields[4], False)
                    try:
                        quality = int(fields[5])
                    except (ValueError, IndexError):
                        quality = None
                    time_field = fields[0]
                elif kind == "RMC" and len(fields) >= 6:
                    lat, problem = parse_coordinate(fields[2], fields[3], True)
                    if not problem:
                        lon, problem = parse_coordinate(fields[4], fields[5], False)
                    time_field = fields[0]
                elif kind == "GLL" and len(fields) >= 4:
                    lat, problem = parse_coordinate(fields[0], fields[1], True)
                    if not problem:
                        lon, problem = parse_coordinate(fields[2], fields[3], False)
                    time_field = fields[4] if len(fields) > 4 else ""
                else:
                    continue
                positions.append(
                    Position(
                        kind, time_field, lat, lon, quality, ok, match.group(0), problem
                    )
                )
                break
    return waypoints, positions, config


def distance_to_polyline_m(
    lat: float, lon: float, polyline: list[tuple[float, float]]
) -> float:
    """Shortest distance from a point to a polyline, in metres.

    Args:
        lat: Query latitude, decimal degrees.
        lon: Query longitude, decimal degrees.
        polyline: Ordered (latitude, longitude) vertices.

    Returns:
        Distance in metres, or infinity for an empty polyline.
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
    # Half a least-significant bit on each axis, combined.
    half_lat = NMEA_LSB_DEGREES * per_lat / 2.0
    half_lon = NMEA_LSB_DEGREES * per_lon / 2.0
    return math.hypot(half_lat, half_lon)


def verify(
    waypoints: list[tuple[float, float, float]],
    positions: list[Position],
    config: dict,
    tolerance_m: float,
) -> Result:
    """Evaluates the emulator's emitted positions against the P1 criteria.

    Args:
        waypoints: Route waypoints the emulator parsed.
        positions: Positions the emulator emitted.
        config: Configuration scraped from the log.
        tolerance_m: Allowed maximum disagreement with the route.

    Returns:
        The verification result.
    """
    result = Result()
    if config:
        result.observations.append(
            "Emulator configuration: "
            + ", ".join(f"{k}={v}" for k, v in sorted(config.items()))
        )
        result.metrics.update(config)

    if not positions:
        result.observations.append(
            "The log contains no NMEA position sentences (GGA, RMC or GLL)."
        )
        result.summary = "No emitted positions found in the log."
        return result

    kinds: dict[str, int] = {}
    for position in positions:
        kinds[position.kind] = kinds.get(position.kind, 0) + 1
    result.observations.append(
        f"{len(positions)} position sentence(s): "
        + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items()))
    )
    result.metrics["positions"] = len(positions)
    result.metrics["sentence_types"] = kinds

    # --- Check 1: format and checksum
    bad_checksum = [p for p in positions if not p.checksum_ok]
    malformed = [p for p in positions if p.problem]
    usable = [
        p for p in positions if p.latitude is not None and p.longitude is not None
    ]

    result.observations.append(
        f"{len(bad_checksum)} checksum failure(s); "
        f"{len(malformed)} malformed coordinate(s)."
    )
    result.metrics["checksum_failures"] = len(bad_checksum)
    result.metrics["malformed_coordinates"] = len(malformed)

    for position in malformed[:5]:
        result.observations.append(
            f"PROBLEM: {position.problem} in {position.raw[:80]}"
        )

    if not usable:
        result.status = "FAIL"
        result.summary = "No emitted sentence carried a usable WGS 84 coordinate."
        return result

    lats = [p.latitude for p in usable]
    lons = [p.longitude for p in usable]
    result.observations.append(
        f"Coordinate extent: lat {min(lats):+.7f}..{max(lats):+.7f}, "
        f"lon {min(lons):+.7f}..{max(lons):+.7f}"
    )
    result.metrics["distinct_positions"] = len(
        {(round(p.latitude, 9), round(p.longitude, 9)) for p in usable}
    )

    # --- Check 2: fix validity
    gga = [p for p in usable if p.kind == "GGA" and p.fix_quality is not None]
    no_fix = [p for p in gga if p.fix_quality == 0]
    if gga:
        qualities = sorted({p.fix_quality for p in gga})
        result.observations.append(
            f"GGA fix quality values seen: {qualities} "
            "(0 = invalid, 1 = GPS fix, 2 = DGPS)."
        )
        result.metrics["fix_qualities"] = qualities
        result.metrics["no_fix_sentences"] = len(no_fix)

    # --- Check 3: agreement with the WGS 84 route the emulator parsed
    floor = quantization_floor_m(sum(lats) / len(lats))
    result.observations.append(
        f"NMEA coordinate resolution is {NMEA_LSB_DEGREES * 60:.4f} min, giving a "
        f"two-axis rounding floor of {floor:.3f} m at this latitude."
    )
    result.metrics["quantization_floor_m"] = round(floor, 4)

    if tolerance_m < floor:
        result.observations.append(
            f"NOTE: the requested tolerance {tolerance_m:.3f} m is below the "
            f"{floor:.3f} m NMEA rounding floor, so it cannot be met by any "
            "emulator however correct. Raise it above the floor."
        )

    agreement_measured = False
    if len(waypoints) >= 2:
        polyline = [(lat, lon) for _t, lat, lon in waypoints]
        errors = [
            distance_to_polyline_m(p.latitude, p.longitude, polyline) for p in usable
        ]
        median = percentile(errors, 0.5)
        p95 = percentile(errors, 0.95)
        worst = max(errors)
        agreement_measured = True
        result.observations.append(
            f"Emitted positions vs the {len(waypoints)}-waypoint route the "
            f"emulator parsed: median {median:.4f} m, p95 {p95:.4f} m, "
            f"max {worst:.4f} m."
        )
        result.metrics["route_waypoints"] = len(waypoints)
        result.metrics["agreement_median_m"] = round(median, 4)
        result.metrics["agreement_p95_m"] = round(p95, 4)
        result.metrics["agreement_max_m"] = round(worst, 4)
        if worst <= floor * 1.5:
            result.observations.append(
                "The disagreement is at the NMEA rounding floor, so the "
                "emulator reproduced its input frame exactly; no datum shift, "
                "projection or axis swap is present."
            )
    else:
        result.observations.append(
            "The log carries fewer than two route waypoints, so emitted "
            "positions could not be compared against the input frame. Format "
            "and fix validity were still checked."
        )

    for position in usable[:2]:
        result.observations.append(f"sample: {position.raw[:100]}")

    # --- Verdict
    problems: list[str] = []
    if bad_checksum:
        problems.append(f"{len(bad_checksum)} sentence(s) failed checksum")
    if malformed:
        problems.append(
            f"{len(malformed)} sentence(s) carried a malformed WGS 84 coordinate"
        )
    if no_fix:
        problems.append(
            f"{len(no_fix)} GGA sentence(s) reported fix quality 0 (no valid fix)"
        )
    if agreement_measured and result.metrics["agreement_max_m"] > tolerance_m:
        problems.append(
            f"emitted positions disagree with the parsed route by up to "
            f"{result.metrics['agreement_max_m']:.4f} m, beyond the "
            f"{tolerance_m:.3f} m tolerance"
        )

    if problems:
        for problem in problems:
            result.observations.append(f"PROBLEM: {problem}")
        result.status = "FAIL"
        result.summary = "; ".join(problems)
        return result

    result.status = "PASS"
    if agreement_measured:
        result.summary = (
            f"All {len(usable)} emitted position(s) were well-formed WGS 84 "
            f"coordinates and matched the parsed route within "
            f"{result.metrics['agreement_max_m']:.4f} m."
        )
    else:
        result.summary = (
            f"All {len(usable)} emitted position(s) were well-formed WGS 84 "
            "coordinates; no route was present to compare the frame against."
        )
    return result


def render(result: Result, verbose: bool) -> None:
    """Prints the result.

    Args:
        result: Verification result.
        verbose: Whether to print metrics.
    """
    print()
    print("P1 - Coordinate systems (WGS 84)")
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
            "Verify P1: GPS Emulator positions conform to the WGS 84 "
            "coordinate system."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Reads the emulator's own log, which carries both the route it\n"
            "parsed and the NMEA it emitted, and checks that the emitted\n"
            "coordinates are well-formed and agree with the input frame."
        ),
    )
    parser.add_argument("log", type=Path, help="GNSS emulator log file.")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_TOLERANCE_M,
        metavar="METRES",
        help=(
            "Maximum allowed disagreement between emitted positions and the "
            f"parsed route (default: {DEFAULT_TOLERANCE_M}). Cannot meaningfully "
            "be set below the NMEA rounding floor of about 0.13 m."
        ),
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
        waypoints, positions, config = parse_log(args.log)
    except OSError as exc:
        print(f"Could not read {args.log}: {exc}", file=sys.stderr)
        return 2

    result = verify(waypoints, positions, config, args.tolerance)
    result.metrics["log"] = str(args.log)

    if args.json:
        print(
            json.dumps(
                {
                    "requirement": "P1",
                    "title": "Coordinate systems (WGS 84)",
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