#!/usr/bin/env python3
"""E3 - Provide Route Information.

    Requirement:  The DT system shall provide path following route information
                  to the GPS emulation for the DUT.
    Criteria:     Path following route information populates in DUT.
    System:       DT System

WHAT THIS VERIFIES
------------------
This script verifies the routed entity's TENA-published track follows the route,
and the DUT consumes it. 

A TDCS file from testing is required, as well as a log file from the DUT containing the GPS information
consumed. There are a couple ways to gather this info:

'gpspipe -w -t > gpsd.jsonl' -> which creates a gpsd client output from the DUT OR
by running a tcpdump on the receiving port on the DUT to capture the GPS feed
being sent to the DUT.

INPUT
-----
Required -- the TDCS recording carrying the scenario and entity tracks:

    ./verify_e3_route_information.py run.sqlite -> Will confirm the DT side but not if the DUT is consuming GPS data
    
    To do so,

    ./verify_e3_route_information.py run.sqlite --gpsd gpsd.jsonl
    ./verify_e3_route_information.py run.sqlite --feed nmea.pcap --align

    
Additionally, 

USAGE
-----
    ./verify_e3_route_information.py run.sqlite


EXIT CODES
----------
    0  PASS     requirement met
    1  FAIL     requirement not met
    2  NO_DATA  recording unreadable, or no routes present
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import struct
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCENARIO_TYPE = "VUG::Configuration::Scenario"
ENTITY_TYPES = (
    "VUG::Entities::Radio",
    "VUG::Entities::LandVehicle",
    "VUG::Entities::VulnerableRoadUser",
    "TENA::LVC::Entity",
)

LAT_ATTR = "geodetic_asTransmitted.latitudeInDegrees"
LON_ATTR = "geodetic_asTransmitted.longitudeInDegrees"
TIME_ATTR = "time.nanosecondsSince1970"

DEFAULT_TOLERANCE_M = 2.0
DEFAULT_MIN_SAMPLES = 10
DEFAULT_PORT = 5000

EARTH_RADIUS_M = 6_378_137.0

# A georeference within this many degrees of (0, 0) is treated as unset. Null
# island is in the Gulf of Guinea, so no real test site is near it.
NULL_GEOREF_EPS = 1e-9

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

UBX_SYNC = b"\xb5\x62"
UBX_NAV_PVT = (0x01, 0x07)
PVT_VALID_DATE = 0x01
PVT_VALID_TIME = 0x02

NMEA_RE = re.compile(r"^\$(G[PNLA][A-Z]{3})((?:,[^,*\r\n]*)*)\*?([0-9A-Fa-f]{2})?")


# Geometry


def meters_per_degree(latitude: float) -> tuple[float, float]:
    """Returns metres per degree of latitude and longitude at a latitude.

    Args:
        latitude: Decimal degrees.
    """
    per_lat = math.pi * EARTH_RADIUS_M / 180.0
    return per_lat, per_lat * math.cos(math.radians(latitude))


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
    per_lat, per_lon = meters_per_degree(lat)
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


# TDCS side


def quote(identifier: str) -> str:
    """Backtick-quotes a TDCS table or column name for SQL.

    Args:
        identifier: Raw table or column name.
    """
    return "`" + identifier.replace("`", "``") + "`"


def open_recording(path: Path) -> sqlite3.Connection:
    """Opens a TDCS recording read-only, falling back for read-only media.

    Args:
        path: Recording file.

    Returns:
        An open connection with a row factory set.

    Raises:
        sqlite3.Error: If the file cannot be opened either way.
    """
    posix = path.as_posix()
    for uri in (f"file:{posix}?mode=ro", f"file:{posix}?mode=ro&immutable=1"):
        try:
            conn = sqlite3.connect(uri, uri=True)
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error:
            continue
    raise sqlite3.Error(f"Cannot open {path} read-only")


def tables(conn: sqlite3.Connection) -> set[str]:
    """Returns every table name in the recording.

    Args:
        conn: Open connection.
    """
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def type_id(conn: sqlite3.Connection, type_name: str) -> str | None:
    """Resolves a TENA type name to the hash used in its table names.

    Args:
        conn: Open connection.
        type_name: Fully-qualified TENA type name.
    """
    try:
        rows = conn.execute("SELECT Name, TypeId FROM omTypeIdMap")
    except sqlite3.Error:
        return None
    for row in rows:
        if row["Name"] == type_name:
            return str(row["TypeId"])
    return None


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """Lists the column names of a table.

    Args:
        conn: Open connection.
        table: Exact table name.
    """
    return [
        d[0] for d in conn.execute(f"SELECT * FROM {quote(table)} LIMIT 0").description
    ]


def find_column(conn: sqlite3.Connection, table: str, needle: str) -> str | None:
    """Finds the first column of a table whose name contains a substring.

    Args:
        conn: Open connection.
        table: Exact table name.
        needle: Substring to match.
    """
    for name in columns(conn, table):
        if needle in name:
            return name
    return None


@dataclass
class Route:
    """A scenario route and its waypoints.

    Attributes:
        row_id: Row id within the routes vector.
        identifier: Route name as authored.
        entity: Identifier of the entity the route is bound to.
        declared: Waypoint count declared in the route record.
        waypoints: Ordered (time_ns, latitude, longitude) tuples.
    """

    row_id: int
    identifier: str
    entity: str
    declared: int
    waypoints: list[tuple[int, float, float]] = field(default_factory=list)

    @property
    def polyline(self) -> list[tuple[float, float]]:
        """Route geometry as ordered (latitude, longitude) vertices."""
        return [(lat, lon) for _t, lat, lon in self.waypoints]


def load_georeference(conn: sqlite3.Connection) -> tuple[float, float] | None:
    """Reads the scenario's map georeference position.

    Args:
        conn: Open connection.

    Returns:
        Tuple of (latitude, longitude), or None when no geodetic georeference
        was transmitted.
    """
    hash_id = type_id(conn, SCENARIO_TYPE)
    if hash_id is None:
        return None
    const = f"Class,{SCENARIO_TYPE},{hash_id},const"
    if const not in tables(conn):
        return None
    row = conn.execute(f"SELECT * FROM {quote(const)} LIMIT 1").fetchone()
    if row is None:
        return None
    keys = set(row.keys())
    set_col = next(
        (k for k in keys if "mapGeoReferencePosition.geodetic_asTransmitted,set" in k),
        None,
    )
    if set_col and not row[set_col]:
        return None
    lat_col = next(
        (k for k in keys if "mapGeoReferencePosition." + LAT_ATTR in k), None
    )
    lon_col = next(
        (k for k in keys if "mapGeoReferencePosition." + LON_ATTR in k), None
    )
    if not lat_col or not lon_col:
        return None
    lat, lon = row[lat_col], row[lon_col]
    if lat is None or lon is None:
        return None
    return float(lat), float(lon)


def load_routes(conn: sqlite3.Connection) -> list[Route]:
    """Reads scenario routes and their waypoint vectors.

    Args:
        conn: Open connection.

    Returns:
        Every route found, each with its waypoints attached.
    """
    hash_id = type_id(conn, SCENARIO_TYPE)
    if hash_id is None:
        return []
    present = tables(conn)
    routes_table = f"VectorClass,{SCENARIO_TYPE},{hash_id},routes"
    waypoints_table = f"{routes_table},waypointVector"
    if routes_table not in present:
        return []

    routes: list[Route] = []
    for row in conn.execute(f"SELECT * FROM {quote(routes_table)} ORDER BY rowID"):
        keys = set(row.keys())
        routes.append(
            Route(
                row_id=int(row["rowID"]),
                identifier=str(row["identifier,String"]) if "identifier,String" in keys else "",
                entity=(
                    str(row["entityIdentifier,String"])
                    if "entityIdentifier,String" in keys
                    else ""
                ),
                declared=(
                    int(row["Vector,waypointVector,count"])
                    if "Vector,waypointVector,count" in keys
                    else 0
                ),
            )
        )

    if waypoints_table not in present:
        return routes
    lat_col = find_column(conn, waypoints_table, LAT_ATTR)
    lon_col = find_column(conn, waypoints_table, LON_ATTR)
    time_col = find_column(conn, waypoints_table, TIME_ATTR)
    if not lat_col or not lon_col:
        return routes
    parent = f"DB,{routes_table},rowID"

    for route in routes:
        time_expr = f"COALESCE({quote(time_col)}, 0)" if time_col else "0"
        rows = conn.execute(
            f"SELECT {time_expr} AS t, COALESCE({quote(lat_col)}, 0.0) AS lat, "
            f"COALESCE({quote(lon_col)}, 0.0) AS lon "
            f"FROM {quote(waypoints_table)} WHERE {quote(parent)} = ? ORDER BY rowID",
            (route.row_id,),
        )
        route.waypoints = [
            (int(r["t"]), float(r["lat"]), float(r["lon"])) for r in rows
        ]
    return routes


def load_entity_track(
    conn: sqlite3.Connection, entity: str
) -> tuple[str, list[tuple[float, float]]]:
    """Finds the TENA-published position track for an entity identifier.

    Args:
        conn: Open connection.
        entity: Entity identifier as named in the scenario.

    Returns:
        Tuple of (class name, ordered (latitude, longitude) samples).
    """
    present = tables(conn)
    for type_name in ENTITY_TYPES:
        hash_id = type_id(conn, type_name)
        if hash_id is None:
            continue
        state, const = f"Class,{type_name},{hash_id}", f"Class,{type_name},{hash_id},const"
        if state not in present or const not in present:
            continue
        lat_col = find_column(conn, state, LAT_ATTR)
        lon_col = find_column(conn, state, LON_ATTR)
        if not lat_col or not lon_col:
            continue
        if "identifier,String" not in columns(conn, const):
            continue
        join_key = f"DB,{const},rowID"
        rows = conn.execute(
            f"SELECT COALESCE(s.{quote(lat_col)}, 0.0) AS lat, "
            f"COALESCE(s.{quote(lon_col)}, 0.0) AS lon "
            f"FROM {quote(state)} AS s JOIN {quote(const)} AS c "
            f"ON s.{quote(join_key)} = c.rowID "
            f"WHERE c.{quote('identifier,String')} = ? ORDER BY s.rowID",
            (entity,),
        )
        samples = [(float(r["lat"]), float(r["lon"])) for r in rows]
        if samples:
            return type_name, samples
    return "", []


def read_gpsd_track(path: Path) -> list[tuple[float, float]]:
    """Reads position fixes from gpsd client output.

    Args:
        path: File with one gpsd JSON report per line.

    Returns:
        Ordered (latitude, longitude) fixes.
    """
    fixes: list[tuple[float, float]] = []
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
            lat, lon = report.get("lat"), report.get("lon")
            if lat is not None and lon is not None:
                fixes.append((float(lat), float(lon)))
    return fixes


def ubx_checksum(frame_body: bytes) -> bytes:
    """Computes the UBX 8-bit Fletcher checksum.

    Args:
        frame_body: Bytes from the class octet through the end of the payload.
    """
    ck_a = ck_b = 0
    for byte in frame_body:
        ck_a = (ck_a + byte) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return bytes([ck_a, ck_b])


def _nmea_degrees(value: str, hemisphere: str) -> float | None:
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


def parse_feed_stream(buffer: bytes) -> list[tuple[float, float]]:
    """Extracts positions from a mixed UBX/NMEA byte stream.

    Dispatches on framing and steps over each UBX frame by its declared length,
    so binary payload bytes containing 0x24 are not misread as NMEA sentences.

    Args:
        buffer: Reassembled stream bytes.

    Returns:
        Ordered (latitude, longitude) positions.
    """
    positions: list[tuple[float, float]] = []
    index, size = 0, len(buffer)
    while index < size:
        if buffer[index : index + 2] == UBX_SYNC:
            if index + 6 > size:
                break
            cls, msg_id, length = struct.unpack("<BBH", buffer[index + 2 : index + 6])
            end = index + 6 + length + 2
            if end > size:
                break
            body = buffer[index + 2 : index + 6 + length]
            if (
                ubx_checksum(body) == buffer[index + 6 + length : end]
                and (cls, msg_id) == UBX_NAV_PVT
                and length >= 92
            ):
                payload = buffer[index + 6 : index + 6 + length]
                lon, lat = struct.unpack("<ii", payload[24:32])
                positions.append((lat / 1e7, lon / 1e7))
            index = end
            continue
        if buffer[index] == 0x24:  # '$'
            end = buffer.find(b"\n", index)
            if end < 0:
                break
            text = bytes(buffer[index:end]).decode("ascii", errors="replace").strip()
            match = NMEA_RE.match(text)
            if match:
                fields = (match.group(2) or "").split(",")[1:]
                kind = match.group(1)[2:]
                if kind == "GGA" and len(fields) >= 5:
                    lat = _nmea_degrees(fields[1], fields[2])
                    lon = _nmea_degrees(fields[3], fields[4])
                    if lat is not None and lon is not None:
                        positions.append((lat, lon))
                elif kind == "RMC" and len(fields) >= 6:
                    lat = _nmea_degrees(fields[2], fields[3])
                    lon = _nmea_degrees(fields[4], fields[5])
                    if lat is not None and lon is not None:
                        positions.append((lat, lon))
                index = end + 1
                continue
            index += 1
            continue
        index += 1
    return positions


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


def read_feed_track(path: Path, port: int) -> list[tuple[float, float]]:
    """Reads positions from a capture of the GPS feed arriving at the DUT.

    Args:
        path: Capture file.
        port: TCP port carrying the feed.

    Returns:
        Ordered (latitude, longitude) positions.

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
    endian, _nanoseconds = PCAP_MAGICS[blob[:4]]
    link_type = struct.unpack(endian + "I", blob[20:24])[0]

    streams: dict[tuple, dict[int, bytes]] = {}
    offset = 24
    while offset + 16 <= len(blob):
        _s, _f, captured, _o = struct.unpack(
            endian + "IIII", blob[offset : offset + 16]
        )
        offset += 16
        if offset + captured > len(blob):
            break
        frame = blob[offset : offset + captured]
        offset += captured
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
                sequence, payload
            )

    positions: list[tuple[float, float]] = []
    for chunks in streams.values():
        buffer = bytearray()
        for sequence in sorted(chunks):
            buffer.extend(chunks[sequence])
        positions.extend(parse_feed_stream(bytes(buffer)))
    return positions


# ------------------------------------------------------------------- verdict


@dataclass
class Result:
    """Outcome of the E3 check.

    Attributes:
        status: PASS, FAIL or NO_DATA.
        tier: Evidence tier reached (1 strongest, 3 weakest, 0 none).
        summary: One-line explanation.
        observations: What the check found.
        metrics: Machine-readable measurements.
    """

    status: str = "NO_DATA"
    tier: int = 0
    summary: str = ""
    observations: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def align_polyline(
    polyline: list[tuple[float, float]], track: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Translates a route so its first vertex sits on the track's first point.

    Used only when the scenario carries a null map georeference, where absolute
    positions are not comparable. Shape is preserved; absolute location is not
    tested.

    Args:
        polyline: Route vertices.
        track: Observed track.

    Returns:
        The translated route.
    """
    if not polyline or not track:
        return polyline
    d_lat = track[0][0] - polyline[0][0]
    d_lon = track[0][1] - polyline[0][1]
    return [(lat + d_lat, lon + d_lon) for lat, lon in polyline]


def evaluate_track(
    track: list[tuple[float, float]], polyline: list[tuple[float, float]]
) -> tuple[float, float, float]:
    """Measures how closely a track follows a route.

    Args:
        track: Observed (latitude, longitude) samples.
        polyline: Route vertices.

    Returns:
        Tuple of (median, p95, max) cross-track error in metres.
    """
    errors = [distance_to_polyline_m(lat, lon, polyline) for lat, lon in track]
    return percentile(errors, 0.5), percentile(errors, 0.95), max(errors)


def verify(
    conn: sqlite3.Connection,
    dut_track: list[tuple[float, float]],
    dut_source: str,
    tolerance_m: float,
    min_samples: int,
    align: bool,
) -> Result:
    """Checks that route information was provided and followed.

    Args:
        conn: Open connection to the recording.
        dut_track: DUT-side positions, empty when none supplied.
        dut_source: Description of where the DUT track came from.
        tolerance_m: Allowed maximum cross-track error.
        min_samples: Minimum samples before judging a track.
        align: Translate the route onto the track before comparing, for use
            with a null map georeference.

    Returns:
        The verification result.
    """
    result = Result()

    routes = load_routes(conn)
    if not routes:
        result.observations.append(
            "The scenario declares no routes, so the DT system provided no "
            "route information in this run."
        )
        result.summary = "Recording contains no route information."
        return result

    georef = load_georeference(conn)
    null_georef = georef is None or (
        abs(georef[0]) < NULL_GEOREF_EPS and abs(georef[1]) < NULL_GEOREF_EPS
    )
    if georef is None:
        result.observations.append(
            "Scenario transmitted no geodetic map georeference."
        )
    else:
        result.observations.append(
            f"Scenario map georeference: {georef[0]:.7f}, {georef[1]:.7f}"
            + (" (null island - route coordinates are map-local)" if null_georef else "")
        )
        result.metrics["map_georeference"] = list(georef)
    result.metrics["null_georeference"] = null_georef

    # --- Route information exists and is well-formed.
    usable = 0
    total_waypoints = 0
    for route in routes:
        count = len(route.waypoints)
        total_waypoints += count
        result.observations.append(
            f"Route {route.identifier!r} -> entity {route.entity!r}: "
            f"{count} waypoint(s), declared {route.declared}."
        )
        if count >= 2 and route.entity:
            usable += 1

    result.metrics["routes"] = len(routes)
    result.metrics["waypoints_total"] = total_waypoints
    result.metrics["routes_usable"] = usable

    if usable == 0:
        result.observations.append(
            "No route has both an entity binding and at least two waypoints, so "
            "none can define a path to follow."
        )
        result.status = "FAIL"
        result.summary = "Route information present but unusable as a path."
        return result

    # --- Tier 1: does the DUT's own track follow a route?
    if dut_track:
        result.observations.append(
            f"DUT track: {len(dut_track)} position(s) from {dut_source}."
        )
        result.metrics["dut_samples"] = len(dut_track)

        if len(dut_track) < min_samples:
            result.observations.append(
                f"Below the minimum of {min_samples} samples for a judgement."
            )
        elif null_georef and not align:
            result.observations.append(
                "SKIPPED the DUT comparison: the scenario carries a null map "
                "georeference, so route waypoints are map-local offsets and are "
                "not in the same frame as the DUT's absolute position. "
                "Comparing them directly would report a meaningless "
                "multi-thousand-kilometre error."
            )
            result.observations.append(
                "Set a real mapGeoReferencePosition in the scenario, or pass "
                "--align to compare route shape instead of absolute position."
            )
        else:
            best = None
            for route in routes:
                if len(route.polyline) < 2:
                    continue
                polyline = (
                    align_polyline(route.polyline, dut_track)
                    if align
                    else route.polyline
                )
                median, p95, worst = evaluate_track(dut_track, polyline)
                if best is None or worst < best[3]:
                    best = (route.identifier, median, p95, worst)
            if best is not None:
                name, median, p95, worst = best
                mode = "shape only (aligned)" if align else "absolute position"
                result.observations.append(
                    f"DUT track vs route {name!r} [{mode}]: median {median:.3f} m, "
                    f"p95 {p95:.3f} m, max {worst:.3f} m."
                )
                result.metrics["dut_route"] = name
                result.metrics["dut_xtrack_p95_m"] = round(p95, 4)
                result.metrics["dut_xtrack_max_m"] = round(worst, 4)
                result.metrics["comparison_mode"] = mode
                if worst <= tolerance_m:
                    result.tier = 1
                    result.status = "PASS"
                    result.summary = (
                        f"Route information populated in the DUT: its track "
                        f"followed route {name!r} within {worst:.3f} m"
                        + (" (shape compared, not absolute position)." if align else ".")
                    )
                    return result
                result.observations.append(
                    f"PROBLEM: the DUT track departs from every route by up to "
                    f"{worst:.3f} m, beyond the {tolerance_m} m tolerance."
                )
                result.status = "FAIL"
                result.summary = (
                    f"DUT track does not follow the provided route (max "
                    f"{worst:.3f} m from {name!r})."
                )
                return result
    else:
        result.observations.append(
            "No DUT-side track supplied. Pass --gpsd or --feed to evidence the "
            "stated outcome that route information populates in the DUT."
        )

    # --- Tier 2: did the routed entity's TENA track follow its route?
    evaluated = 0
    followed = 0
    failures: list[str] = []
    for route in routes:
        if not route.entity or len(route.polyline) < 2:
            continue
        class_name, track = load_entity_track(conn, route.entity)
        if len(track) < min_samples:
            continue
        evaluated += 1
        median, p95, worst = evaluate_track(track, route.polyline)
        result.observations.append(
            f"Entity {route.entity!r} ({class_name.split('::')[-1]}) published "
            f"{len(track)} position(s); cross-track to {route.identifier!r}: "
            f"median {median:.3f} m, p95 {p95:.3f} m, max {worst:.3f} m."
        )
        result.metrics[f"{route.entity}_xtrack_max_m"] = round(worst, 4)
        if worst <= tolerance_m:
            followed += 1
        else:
            failures.append(
                f"{route.entity}: departs route {route.identifier} by up to "
                f"{worst:.3f} m"
            )

    result.metrics["entities_evaluated"] = evaluated
    result.metrics["entities_followed"] = followed
    result.metrics["tolerance_m"] = tolerance_m

    if failures:
        for failure in failures:
            result.observations.append(f"PROBLEM: {failure}")
        result.status = "FAIL"
        result.summary = (
            f"{len(failures)} of {evaluated} routed entities did not follow the "
            "route the DT system provided."
        )
        return result

    if evaluated:
        result.tier = 2
        result.status = "PASS"
        result.summary = (
            f"The DT system provided {usable} usable route(s) and {followed} of "
            f"{evaluated} routed entities followed theirs within {tolerance_m} m. "
            "Delivery to the DUT itself was not observed."
        )
        return result

    result.tier = 3
    result.status = "PASS"
    result.summary = (
        f"{usable} usable route(s) were authored, but no entity published a "
        "track and no DUT data was supplied, so delivery was not shown."
    )
    return result


def render(result: Result, verbose: bool) -> None:
    """Prints the result.

    Args:
        result: Verification result.
        verbose: Whether to print metrics.
    """
    tiers = {
        1: "1 of 3 (strongest) - the DUT's own track follows the route",
        2: "2 of 3 - a routed entity's TENA track follows the route",
        3: "3 of 3 (weakest) - routes authored, delivery not shown",
    }
    print()
    print("E3 - Provide Route Information")
    print("=" * 68)
    print(f"  Result: {result.status}")
    if result.tier:
        print(f"  Evidence tier: {tiers[result.tier]}")
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
            "Verify E3: the DT system provides path following route "
            "information to the GPS emulation for the DUT."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Supply --gpsd or --feed to evidence the stated outcome that route\n"
            "information populates in the DUT. Without either, the check can\n"
            "only show the DT-to-emulator half of the chain."
        ),
    )
    parser.add_argument("tdcs", type=Path, help="TDCS SQLite recording.")
    parser.add_argument(
        "--gpsd",
        type=Path,
        help="gpsd client output from the DUT (gpspipe -w -t).",
    )
    parser.add_argument(
        "--feed",
        type=Path,
        help="Capture of the GPS feed arriving at the DUT.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"TCP port carrying the feed (default: {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--align",
        action="store_true",
        help=(
            "Translate the route onto the DUT track before comparing, testing "
            "shape rather than absolute position. Needed when the scenario "
            "carries a null map georeference."
        ),
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_TOLERANCE_M,
        metavar="METRES",
        help=f"Maximum allowed cross-track error (default: {DEFAULT_TOLERANCE_M}).",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=DEFAULT_MIN_SAMPLES,
        help=f"Minimum positions before judging a track (default: {DEFAULT_MIN_SAMPLES}).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead.")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Also print metrics."
    )
    args = parser.parse_args(argv)

    if not args.tdcs.is_file():
        print(f"Recording not found: {args.tdcs}", file=sys.stderr)
        return 2

    dut_track: list[tuple[float, float]] = []
    dut_source = ""
    try:
        if args.gpsd:
            if not args.gpsd.is_file():
                print(f"gpsd output not found: {args.gpsd}", file=sys.stderr)
                return 2
            dut_track = read_gpsd_track(args.gpsd)
            dut_source = f"gpsd output {args.gpsd.name}"
        elif args.feed:
            if not args.feed.is_file():
                print(f"Feed capture not found: {args.feed}", file=sys.stderr)
                return 2
            dut_track = read_feed_track(args.feed, args.port)
            dut_source = f"feed capture {args.feed.name}"
    except (OSError, ValueError) as exc:
        print(f"Could not read DUT input: {exc}", file=sys.stderr)
        return 2

    try:
        conn = open_recording(args.tdcs)
    except sqlite3.Error as exc:
        print(f"Could not open {args.tdcs}: {exc}", file=sys.stderr)
        return 2

    try:
        result = verify(
            conn,
            dut_track,
            dut_source,
            args.tolerance,
            args.min_samples,
            args.align,
        )
    finally:
        conn.close()

    result.metrics["recording"] = str(args.tdcs)

    if args.json:
        print(
            json.dumps(
                {
                    "requirement": "E3",
                    "title": "Provide Route Information",
                    "status": result.status,
                    "evidence_tier": result.tier,
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
