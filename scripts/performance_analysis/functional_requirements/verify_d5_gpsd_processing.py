#!/usr/bin/env python3
"""D5 - Processing of simulated NMEA data.

    Requirement:  The DUT shall process emulated NMEA strings through GPSD as
                  ground truth.
    Criteria:     DUT uses GPSD [Ground Truth] to process NMEA strings.
    System:       DUT (OBU)

WHAT THIS VERIFIES
------------------
That gpsd produced position fixes, and that those fixes derive from the
*emulated* NMEA rather than from a real antenna.

That second half is the substance of the check. Observing that gpsd is running
and emitting TPV reports proves nothing on its own -- a DUT with a live GNSS
antenna does exactly that while ignoring the emulator entirely. So each gpsd fix
is paired with the injected sentence nearest it in time and the horizontal
separation is measured. gpsd passes NMEA positions through essentially
unchanged, so agreement should be sub-metre; a large separation means gpsd is
reading something other than the emulated stream.

INPUT
-----
1. gpsd client output, one JSON report per line:

       gpspipe -w -t > d5_gpsd.json

2. The injected NMEA, as a capture or a text log:

       tcpdump -i any -w d5_nmea.pcap tcp port 5000

Both must come from the same run, on a common clock.

USAGE
-----
    ./verify_d5_gpsd_processing.py d5_gpsd.json d5_nmea.pcap

EXIT CODES
----------
    0  PASS     requirement met
    1  FAIL     requirement not met
    2  NO_DATA  an input was unreadable, or too few pairs to judge
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import re
import struct
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

PCAP_MAGICS = {
    b"\xd4\xc3\xb2\xa1": ("<", False),
    b"\xa1\xb2\xc3\xd4": (">", False),
    b"\x4d\x3c\xb2\xa1": ("<", True),
    b"\xa1\xb2\x3c\x4d": (">", True),
}
LINKTYPE_ETHERNET, LINKTYPE_RAW = 1, 101
LINKTYPE_LINUX_SLL, LINKTYPE_LINUX_SLL2 = 113, 276
ETHERTYPE_IPV4, ETHERTYPE_IPV6, ETHERTYPE_VLAN = b"\x08\x00", b"\x86\xDD", b"\x81\x00"
IPPROTO_TCP = 6

DEFAULT_PORT = 5000
DEFAULT_TOLERANCE_M = 1.0
DEFAULT_MAX_PAIR_GAP_S = 0.5
DEFAULT_MIN_PAIRS = 10

EARTH_RADIUS_M = 6_378_137.0

NMEA_RE = re.compile(r"\$(G[PNLA][A-Z]{3})((?:,[^,*\r\n]*)*)\*?([0-9A-Fa-f]{2})?")
ISO_RE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?)")
EPOCH_RE = re.compile(r"^\s*(\d{10}(?:\.\d{1,9})?)\b")


@dataclass
class Fix:
    """A position with a time, from either source.

    Attributes:
        when: UTC instant of the position.
        latitude: Decimal degrees.
        longitude: Decimal degrees.
        mode: gpsd fix mode, when the fix came from gpsd.
    """

    when: datetime
    latitude: float
    longitude: float
    mode: int = 0


# Geometry


def separation_m(a: Fix, b: Fix) -> float:
    """Approximates the horizontal distance between two WGS 84 positions.

    A local equirectangular projection is accurate well past the metre level at
    these separations and avoids a geodesic dependency.

    Args:
        a: First position.
        b: Second position.

    Returns:
        Distance in metres.
    """
    mean_lat = math.radians((a.latitude + b.latitude) / 2.0)
    per_degree = math.pi * EARTH_RADIUS_M / 180.0
    dy = (b.latitude - a.latitude) * per_degree
    dx = (b.longitude - a.longitude) * per_degree * math.cos(mean_lat)
    return math.hypot(dx, dy)


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


# GPSD side


def read_gpsd(path: Path) -> tuple[list[Fix], dict[int, int]]:
    """Reads TPV position reports from gpsd client output.

    Args:
        path: File with one gpsd JSON report per line.

    Returns:
        Tuple of (fixes, count of reports by fix mode).
    """
    fixes: list[Fix] = []
    modes: dict[int, int] = {}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            start = line.find("{")
            if start < 0:
                continue
            try:
                report = json.loads(line[start:])
            except json.JSONDecodeError:
                continue
            if not isinstance(report, dict) or report.get("class") != "TPV":
                continue
            mode = int(report.get("mode", 0))
            modes[mode] = modes.get(mode, 0) + 1
            when = _parse_iso(report.get("time"))
            lat, lon = report.get("lat"), report.get("lon")
            if when is None or lat is None or lon is None:
                continue
            fixes.append(Fix(when, float(lat), float(lon), mode))
    fixes.sort(key=lambda f: f.when)
    return fixes, modes


def _parse_iso(value) -> datetime | None:
    """Parses an ISO-8601 timestamp, returning None on anything unparsable.

    Args:
        value: Timestamp string.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (
        parsed.replace(tzinfo=timezone.utc)
        if parsed.tzinfo is None
        else parsed.astimezone(timezone.utc)
    )


# Injected side


def _to_degrees(value: str, hemisphere: str) -> float | None:
    """Converts an NMEA coordinate field to decimal degrees.

    Args:
        value: Numeric NMEA coordinate.
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


def _time_of_day(value: str) -> timedelta | None:
    """Parses an NMEA hhmmss.sss field.

    Args:
        value: Time field as transmitted.
    """
    if not value or len(value) < 6:
        return None
    try:
        return timedelta(
            hours=int(value[0:2]), minutes=int(value[2:4]), seconds=float(value[4:])
        )
    except ValueError:
        return None


def _decode_position(text: str, arrival: datetime | None) -> Fix | None:
    """Extracts a positioned fix from an NMEA sentence.

    GGA carries no date, so the arrival time supplies the day, choosing the
    candidate nearest the arrival to survive midnight wrap-around. RMC carries
    its own date and is used directly.

    Args:
        text: Line containing a sentence.
        arrival: Capture or log time of the line.

    Returns:
        The fix, or None if the sentence carries no usable position.
    """
    match = NMEA_RE.search(text)
    if not match:
        return None
    talker, blob = match.group(1), match.group(2) or ""
    fields = blob.split(",")[1:] if blob else []
    kind = talker[2:]

    if kind == "GGA" and len(fields) >= 5:
        lat = _to_degrees(fields[1], fields[2])
        lon = _to_degrees(fields[3], fields[4])
        offset = _time_of_day(fields[0])
        if lat is None or lon is None:
            return None
        if offset is not None and arrival is not None:
            midnight = arrival.replace(hour=0, minute=0, second=0, microsecond=0)
            when = min(
                (
                    midnight + offset - timedelta(days=1),
                    midnight + offset,
                    midnight + offset + timedelta(days=1),
                ),
                key=lambda c: abs((c - arrival).total_seconds()),
            )
        elif arrival is not None:
            when = arrival
        else:
            return None
        return Fix(when, lat, lon)

    if kind == "RMC" and len(fields) >= 9:
        lat = _to_degrees(fields[2], fields[3])
        lon = _to_degrees(fields[4], fields[5])
        offset = _time_of_day(fields[0])
        date_field = fields[8]
        if lat is None or lon is None or offset is None or len(date_field) != 6:
            return None
        try:
            base = datetime(
                2000 + int(date_field[4:6]),
                int(date_field[2:4]),
                int(date_field[0:2]),
                tzinfo=timezone.utc,
            )
        except ValueError:
            return None
        return Fix(base + offset, lat, lon)
    return None


def read_injected(path: Path, port: int) -> list[Fix]:
    """Reads injected NMEA positions from a capture or a text log.

    Args:
        path: Capture (.pcap) or text log.
        port: TCP port carrying NMEA within a capture.

    Returns:
        Positions sorted by time.

    Raises:
        ValueError: If a capture cannot be parsed.
    """
    if path.suffix.lower() in (".pcap", ".cap", ".dmp"):
        fixes = _read_injected_pcap(path, port)
    else:
        fixes = []
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                arrival = None
                found = ISO_RE.match(line) or EPOCH_RE.match(line)
                if found:
                    text = found.group(1)
                    try:
                        if "-" in text:
                            parsed = datetime.fromisoformat(text.replace(" ", "T"))
                            arrival = (
                                parsed.replace(tzinfo=timezone.utc)
                                if parsed.tzinfo is None
                                else parsed
                            )
                        else:
                            arrival = datetime.fromtimestamp(
                                float(text), tz=timezone.utc
                            )
                    except ValueError:
                        arrival = None
                fix = _decode_position(line, arrival)
                if fix:
                    fixes.append(fix)
    fixes.sort(key=lambda f: f.when)
    return fixes


def _read_injected_pcap(path: Path, port: int) -> list[Fix]:
    """Reads injected NMEA positions from a TCP capture.

    Args:
        path: Capture file.
        port: TCP port carrying NMEA.

    Returns:
        Positions in stream order.

    Raises:
        ValueError: If the file is not a classic libpcap capture.
    """
    blob = path.read_bytes()
    if len(blob) < 24 or blob[:4] not in PCAP_MAGICS:
        if blob[:4] == b"\x0a\x0d\x0d\x0a":
            raise ValueError(
                f"{path.name} is pcapng. Convert with "
                "`editcap -F pcap in.pcapng out.pcap`."
            )
        raise ValueError(f"{path.name} is not a libpcap capture")
    endian, nanoseconds = PCAP_MAGICS[blob[:4]]
    divisor = 1e9 if nanoseconds else 1e6
    link_type = struct.unpack(endian + "I", blob[20:24])[0]

    streams: dict[tuple, dict[int, tuple[bytes, datetime]]] = {}
    offset = 24
    while offset + 16 <= len(blob):
        seconds, fraction, captured, _orig = struct.unpack(
            endian + "IIII", blob[offset : offset + 16]
        )
        offset += 16
        if offset + captured > len(blob):
            break
        frame = blob[offset : offset + captured]
        offset += captured
        when = datetime.fromtimestamp(seconds + fraction / divisor, tz=timezone.utc)

        located = _network_layer(link_type, frame)
        if located is None:
            continue
        ethertype, at = located
        if ethertype == ETHERTYPE_IPV4:
            if len(frame) < at + 20 or frame[at + 9] != IPPROTO_TCP:
                continue
            src, dst = frame[at + 12 : at + 16].hex(), frame[at + 16 : at + 20].hex()
            tcp_at = at + (frame[at] & 0x0F) * 4
        elif ethertype == ETHERTYPE_IPV6:
            if len(frame) < at + 40 or frame[at + 6] != IPPROTO_TCP:
                continue
            src, dst = frame[at + 8 : at + 24].hex(), frame[at + 24 : at + 40].hex()
            tcp_at = at + 40
        else:
            continue
        if len(frame) < tcp_at + 20:
            continue
        src_port, dst_port, sequence = struct.unpack(
            ">HHI", frame[tcp_at : tcp_at + 8]
        )
        if port not in (src_port, dst_port):
            continue
        payload = frame[tcp_at + (frame[tcp_at + 12] >> 4) * 4 :]
        if payload:
            streams.setdefault((src, src_port, dst, dst_port), {}).setdefault(
                sequence, (payload, when)
            )

    fixes: list[Fix] = []
    for chunks in streams.values():
        buffer = bytearray()
        stamps: list[datetime] = []
        for sequence in sorted(chunks):
            payload, when = chunks[sequence]
            buffer.extend(payload)
            stamps.extend([when] * len(payload))
        start = 0
        while True:
            begin = buffer.find(b"$", start)
            if begin < 0:
                break
            end = buffer.find(b"\n", begin)
            if end < 0:
                break
            arrival = stamps[min(end, len(stamps) - 1)] if stamps else None
            fix = _decode_position(
                bytes(buffer[begin:end]).decode("ascii", errors="replace"), arrival
            )
            if fix:
                fixes.append(fix)
            start = end + 1
    return fixes


def _network_layer(link_type: int, frame: bytes) -> tuple[bytes, int] | None:
    """Finds the network header inside a link-layer frame.

    Args:
        link_type: libpcap link-layer type.
        frame: Frame bytes.
    """
    if link_type == LINKTYPE_ETHERNET:
        if len(frame) < 14:
            return None
        ethertype, offset = frame[12:14], 14
    elif link_type == LINKTYPE_LINUX_SLL:
        if len(frame) < 16:
            return None
        ethertype, offset = frame[14:16], 16
    elif link_type == LINKTYPE_LINUX_SLL2:
        if len(frame) < 20:
            return None
        ethertype, offset = frame[0:2], 20
    elif link_type == LINKTYPE_RAW:
        if not frame:
            return None
        version = frame[0] >> 4
        if version == 4:
            return ETHERTYPE_IPV4, 0
        if version == 6:
            return ETHERTYPE_IPV6, 0
        return None
    else:
        return None
    while ethertype == ETHERTYPE_VLAN and len(frame) >= offset + 4:
        ethertype, offset = frame[offset + 2 : offset + 4], offset + 4
    return ethertype, offset


# Result


@dataclass
class Result:
    """Outcome of the D5 check."""

    status: str = "NO_DATA"
    summary: str = ""
    observations: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def verify(
    gpsd_fixes: list[Fix],
    gpsd_modes: dict[int, int],
    injected: list[Fix],
    tolerance_m: float,
    max_gap_s: float,
    min_pairs: int,
) -> Result:
    """Correlates gpsd fixes against the injected NMEA positions.

    Args:
        gpsd_fixes: Positions reported by gpsd.
        gpsd_modes: Count of gpsd TPV reports by fix mode.
        injected: Positions from the injected NMEA stream.
        tolerance_m: Allowed p95 separation.
        max_gap_s: Maximum time difference for a valid pairing.
        min_pairs: Minimum pairs for a conclusive result.

    Returns:
        The verification result.
    """
    result = Result()

    if not gpsd_fixes:
        result.observations.append(
            "gpsd output contains no TPV report carrying both a time and a "
            "position."
        )
        if gpsd_modes:
            result.observations.append(
                "TPV modes seen: "
                + ", ".join(f"{k}={v}" for k, v in sorted(gpsd_modes.items()))
                + " (0/1 = no fix, 2 = 2D, 3 = 3D)."
            )
        result.status = "FAIL"
        result.summary = "gpsd produced no position fixes during the run."
        return result

    result.observations.append(
        f"{len(gpsd_fixes)} gpsd fix(es); modes "
        + ", ".join(f"{k}={v}" for k, v in sorted(gpsd_modes.items()))
        + " (2 = 2D, 3 = 3D)."
    )
    result.metrics["gpsd_fixes"] = len(gpsd_fixes)
    result.metrics["gpsd_modes"] = gpsd_modes

    if not injected:
        result.observations.append(
            "The injected NMEA source carries no timestamped positions, so "
            "gpsd's fixes cannot be shown to derive from the emulator rather "
            "than a live antenna."
        )
        result.summary = "No injected positions to correlate against."
        return result

    result.observations.append(f"{len(injected)} injected position(s).")
    result.metrics["injected_positions"] = len(injected)

    times = [f.when for f in injected]
    separations: list[float] = []
    unmatched = 0
    for fix in gpsd_fixes:
        index = bisect.bisect_left(times, fix.when)
        candidates = []
        if index < len(injected):
            candidates.append(injected[index])
        if index > 0:
            candidates.append(injected[index - 1])
        if not candidates:
            unmatched += 1
            continue
        nearest = min(
            candidates, key=lambda f: abs((f.when - fix.when).total_seconds())
        )
        if abs((nearest.when - fix.when).total_seconds()) > max_gap_s:
            unmatched += 1
            continue
        separations.append(separation_m(fix, nearest))

    result.metrics["matched"] = len(separations)
    result.metrics["unmatched"] = unmatched
    result.metrics["tolerance_m"] = tolerance_m

    if not separations:
        result.observations.append(
            f"None of the {len(gpsd_fixes)} gpsd fix(es) fell within "
            f"{max_gap_s} s of an injected sentence."
        )
        result.observations.append(
            "Either gpsd is reading a different source, or the two captures "
            "are not on a common clock. Check both before treating this as a "
            "requirement failure."
        )
        result.status = "FAIL"
        result.summary = "gpsd fixes could not be matched to any injected sentence."
        return result

    median = percentile(separations, 0.5)
    p95 = percentile(separations, 0.95)
    worst = max(separations)
    result.observations.append(
        f"Matched {len(separations)} of {len(gpsd_fixes)} fix(es); separation "
        f"median {median:.3f} m, p95 {p95:.3f} m, max {worst:.3f} m."
    )
    result.metrics["separation_median_m"] = round(median, 4)
    result.metrics["separation_p95_m"] = round(p95, 4)
    result.metrics["separation_max_m"] = round(worst, 4)

    if len(separations) < min_pairs:
        result.observations.append(
            f"Only {len(separations)} matched pair(s); below the minimum of "
            f"{min_pairs} for a conclusive judgement."
        )
        result.summary = "Too few matched pairs to judge."
        return result

    if p95 > tolerance_m:
        result.status = "FAIL"
        result.summary = (
            f"gpsd fixes diverge from the injected NMEA by {p95:.3f} m at p95, "
            f"beyond the {tolerance_m} m tolerance. gpsd is not processing the "
            "emulated stream as ground truth."
        )
        return result

    result.status = "PASS"
    result.summary = (
        f"gpsd processed the emulated NMEA as ground truth; {len(separations)} "
        f"fix(es) tracked the injected positions within {p95:.3f} m (p95)."
    )
    return result


def render(result: Result, verbose: bool) -> None:
    """Prints the result.

    Args:
        result: Verification result.
        verbose: Whether to print metrics.
    """
    print()
    print("D5 - Processing of simulated NMEA data")
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
            "Verify D5: the DUT processes emulated NMEA through GPSD as "
            "ground truth."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Collect both artifacts on the DUT during the same run:\n"
            "    gpspipe -w -t > d5_gpsd.jsonl\n"
            "    tcpdump -i any -w d5_nmea.pcap tcp port 5000"
        ),
    )
    parser.add_argument("gpsd", type=Path, help="gpsd client output (JSON per line).")
    parser.add_argument(
        "injected", type=Path, help="Injected NMEA capture (.pcap) or text log."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"TCP port carrying NMEA in a capture (default: {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_TOLERANCE_M,
        metavar="METRES",
        help=(
            "Allowed p95 separation between a gpsd fix and the injected "
            f"position (default: {DEFAULT_TOLERANCE_M})."
        ),
    )
    parser.add_argument(
        "--max-gap",
        type=float,
        default=DEFAULT_MAX_PAIR_GAP_S,
        metavar="SECONDS",
        help=(
            "Maximum time difference for pairing a fix with a sentence "
            f"(default: {DEFAULT_MAX_PAIR_GAP_S}). Must exceed one emulator "
            "update interval."
        ),
    )
    parser.add_argument(
        "--min-pairs",
        type=int,
        default=DEFAULT_MIN_PAIRS,
        help=f"Minimum matched pairs (default: {DEFAULT_MIN_PAIRS}).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead.")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Also print metrics."
    )
    args = parser.parse_args(argv)

    for path in (args.gpsd, args.injected):
        if not path.is_file():
            print(f"Input not found: {path}", file=sys.stderr)
            return 2

    try:
        gpsd_fixes, gpsd_modes = read_gpsd(args.gpsd)
        injected = read_injected(args.injected, args.port)
    except (OSError, ValueError) as exc:
        print(f"Could not read input: {exc}", file=sys.stderr)
        return 2

    result = verify(
        gpsd_fixes,
        gpsd_modes,
        injected,
        args.tolerance,
        args.max_gap,
        args.min_pairs,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "requirement": "D5",
                    "title": "Processing of simulated NMEA data",
                    "status": result.status,
                    "summary": result.summary,
                    "observations": result.observations,
                    "metrics": result.metrics,
                },
                indent=2,
            )
        )
    else:
        render(result, args.verbose)

    return {"PASS": 0, "FAIL": 1}.get(result.status, 2)


if __name__ == "__main__":
    raise SystemExit(main())
