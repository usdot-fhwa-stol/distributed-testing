#!/usr/bin/env python3
"""D4 - Acceptance of simulated GPS input.

    Requirement:  The DUT shall accept emulated NMEA strings via netcat-gpsd
                  service.
    Criteria:     DUT uses netcat-gpsd to accept NMEA string.
    System:       DUT (OBU)

WHAT THIS VERIFIES
------------------

This script verifies that well formed GPS data arrives on the DUT on the
netcat port.

INPUT
-----
A capture of the netcat port, captured by:

    tcpdump -i any -w d4_nmea.pcap tcp port X

Capture BOTH directions to capture handshake

USAGE
-----
    ./verify_d4_nmea_input.py d4_nmea.pcap
    ./verify_d4_nmea_input.py d4_nmea.pcap -v
    ./verify_d4_nmea_input.py d4_nmea.pcap --require-nmea GGA RMC ZDA
    ./verify_d4_nmea_input.py nmea.log --json

EXIT CODES
----------
    0  PASS     requirement met
    1  FAIL     requirement not met
    2  NO_DATA  input unreadable, or contains no GPS data at all
"""

from __future__ import annotations

import argparse
import json
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
DEFAULT_MIN_MESSAGES = 20

# UBX framing: sync chars, then class, id, little-endian length, payload, and a
# two-octet Fletcher checksum over everything from class through payload.
UBX_SYNC = b"\xb5\x62"
UBX_NAV_PVT = (0x01, 0x07)
UBX_NAV_TIMEGPS = (0x01, 0x20)
UBX_NAV_SAT = (0x01, 0x35)
UBX_NAMES = {
    UBX_NAV_PVT: "NAV-PVT",
    UBX_NAV_TIMEGPS: "NAV-TIMEGPS",
    UBX_NAV_SAT: "NAV-SAT",
    (0x01, 0x02): "NAV-POSLLH",
    (0x01, 0x03): "NAV-STATUS",
    (0x01, 0x12): "NAV-VELNED",
    (0x01, 0x21): "NAV-TIMEUTC",
}

# NAV-PVT `valid` bit flags.
PVT_VALID_DATE = 0x01
PVT_VALID_TIME = 0x02
PVT_FULLY_RESOLVED = 0x04

NMEA_RE = re.compile(r"^\$(G[PNLA][A-Z]{3}|P[A-Z]{4})((?:,[^,*\r\n]*)*)\*?([0-9A-Fa-f]{2})?")

TIMESTAMP_RES = [
    (re.compile(r"^\s*(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?)"), "iso"),
    (re.compile(r"^\s*(\d{10}(?:\.\d{1,9})?)\b"), "epoch"),
]


# --------------------------------------------------------------- data models


@dataclass
class Sentence:
    """A decoded NMEA sentence.

    Attributes:
        kind: Sentence type, e.g. "GGA".
        talker: Full identifier without '$', e.g. "GNZDA".
        fields: Field values after the identifier.
        checksum_ok: True/False when a checksum was present, None otherwise.
        latitude: Decimal degrees, when the sentence carries a position.
        longitude: Decimal degrees, when the sentence carries a position.
        time_decimals: Decimal places in the time-of-day field, when present.
        arrival: Capture or log time.
        raw: Matched sentence text.
    """

    kind: str
    talker: str
    fields: list[str]
    checksum_ok: bool | None
    latitude: float | None
    longitude: float | None
    time_decimals: int | None
    arrival: datetime | None
    raw: str


@dataclass
class UbxMessage:
    """A decoded UBX binary message.

    Attributes:
        cls_id: (class, id) pair.
        name: Human-readable name when recognised.
        checksum_ok: Whether the Fletcher checksum validated.
        length: Declared payload length.
        arrival: Capture time.
        latitude: Decimal degrees, for NAV-PVT.
        longitude: Decimal degrees, for NAV-PVT.
        utc: UTC instant, for NAV-PVT.
        fix_type: NAV-PVT fixType (3 = 3D).
        num_sv: Satellites used.
        h_acc_m: Horizontal accuracy estimate, metres.
        t_acc_ns: Time accuracy estimate, nanoseconds.
        speed_mps: Ground speed, metres per second.
        valid_flags: NAV-PVT `valid` bitfield.
    """

    cls_id: tuple[int, int]
    name: str
    checksum_ok: bool
    length: int
    arrival: datetime | None
    latitude: float | None = None
    longitude: float | None = None
    utc: datetime | None = None
    fix_type: int | None = None
    num_sv: int | None = None
    h_acc_m: float | None = None
    t_acc_ns: int | None = None
    speed_mps: float | None = None
    valid_flags: int | None = None


# ------------------------------------------------------------- NMEA decoding


def checksum_valid(body: str, expected: str) -> bool:
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
    """Converts ddmm.mmmm / dddmm.mmmm plus hemisphere to decimal degrees.

    Args:
        value: Numeric NMEA coordinate field.
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


def decode_nmea(text: str, arrival: datetime | None) -> Sentence | None:
    """Decodes one NMEA sentence.

    Args:
        text: Sentence text beginning with '$'.
        arrival: Capture or log time.

    Returns:
        The decoded sentence, or None if the text is not a sentence.
    """
    match = NMEA_RE.match(text)
    if not match:
        return None
    talker = match.group(1)
    blob = match.group(2) or ""
    checksum = match.group(3)
    fields = blob.split(",")[1:] if blob else []
    ok = checksum_valid(f"{talker}{blob}", checksum) if checksum else None

    kind = talker[2:]
    lat = lon = None
    if kind == "GGA" and len(fields) >= 5:
        lat, lon = to_degrees(fields[1], fields[2]), to_degrees(fields[3], fields[4])
    elif kind == "RMC" and len(fields) >= 6:
        lat, lon = to_degrees(fields[2], fields[3]), to_degrees(fields[4], fields[5])

    # Time-of-day resolution matters for P7: two decimal places means the
    # sentence can only express time to 10 ms.
    decimals = None
    if kind in ("GGA", "RMC", "ZDA", "GLL", "GST") and fields:
        head = fields[0]
        if head and head.replace(".", "").isdigit():
            decimals = len(head.split(".", 1)[1]) if "." in head else 0

    return Sentence(kind, talker, fields, ok, lat, lon, decimals, arrival, match.group(0))


# -------------------------------------------------------------- UBX decoding


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


def decode_nav_pvt(payload: bytes, message: UbxMessage) -> None:
    """Fills a message with fields decoded from a NAV-PVT payload.

    Args:
        payload: The 92-byte NAV-PVT payload.
        message: Message to populate in place.
    """
    if len(payload) < 92:
        return
    year, month, day, hour, minute, second, valid = struct.unpack(
        "<HBBBBBB", payload[4:12]
    )
    t_acc, nano = struct.unpack("<Ii", payload[12:20])
    fix_type, _flags, _flags2, num_sv = struct.unpack("<BBBB", payload[20:24])
    lon, lat, _height, _h_msl = struct.unpack("<iiii", payload[24:40])
    h_acc, _v_acc = struct.unpack("<II", payload[40:48])
    (g_speed,) = struct.unpack("<i", payload[60:64])

    message.valid_flags = valid
    message.fix_type = fix_type
    message.num_sv = num_sv
    message.t_acc_ns = t_acc
    message.h_acc_m = h_acc / 1000.0
    message.speed_mps = g_speed / 1000.0
    # Coordinates are 1e-7 degree integers.
    message.latitude = lat / 1e7
    message.longitude = lon / 1e7

    if valid & (PVT_VALID_DATE | PVT_VALID_TIME):
        try:
            base = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
        except ValueError:
            return
        # `nano` is a signed correction and may push the instant either way.
        message.utc = base + timedelta(microseconds=nano / 1000.0)


def decode_nav_timegps(payload: bytes, message: UbxMessage) -> None:
    """Fills a message with fields decoded from a NAV-TIMEGPS payload.

    Args:
        payload: The 16-byte NAV-TIMEGPS payload.
        message: Message to populate in place.
    """
    if len(payload) < 16:
        return
    (i_tow,) = struct.unpack("<I", payload[0:4])
    (f_tow,) = struct.unpack("<i", payload[4:8])
    (week,) = struct.unpack("<h", payload[8:10])
    leap_s = struct.unpack("<b", payload[10:11])[0]
    valid = payload[11]
    (t_acc,) = struct.unpack("<I", payload[12:16])
    message.valid_flags = valid
    message.t_acc_ns = t_acc
    if valid & 0x03 == 0x03:  # towValid and weekValid
        gps_epoch = datetime(1980, 1, 6, tzinfo=timezone.utc)
        message.utc = (
            gps_epoch
            + timedelta(weeks=week, milliseconds=i_tow, microseconds=f_tow / 1000.0)
            - timedelta(seconds=leap_s if valid & 0x04 else 0)
        )


# ------------------------------------------------------------- co-parsing


def parse_stream(
    buffer: bytes, stamps: list[datetime] | None
) -> tuple[list[Sentence], list[UbxMessage], int]:
    """Walks a mixed UBX/NMEA byte stream, dispatching on framing.

    Stepping over each UBX frame by its declared length is what prevents binary
    payload bytes containing 0x24 ('$') from being misread as NMEA sentences.

    Args:
        buffer: Reassembled stream bytes.
        stamps: Per-byte capture times, or None when unavailable.

    Returns:
        Tuple of (sentences, ubx messages, bytes skipped as unparsable).
    """
    sentences: list[Sentence] = []
    messages: list[UbxMessage] = []
    skipped = 0
    index = 0
    size = len(buffer)

    def stamp_at(position: int) -> datetime | None:
        if not stamps:
            return None
        return stamps[min(position, len(stamps) - 1)]

    while index < size:
        if buffer[index : index + 2] == UBX_SYNC:
            if index + 6 > size:
                break
            cls, msg_id, length = struct.unpack("<BBH", buffer[index + 2 : index + 6])
            end = index + 6 + length + 2
            if end > size:
                break
            body = buffer[index + 2 : index + 6 + length]
            payload = buffer[index + 6 : index + 6 + length]
            ok = ubx_checksum(body) == buffer[index + 6 + length : end]
            message = UbxMessage(
                cls_id=(cls, msg_id),
                name=UBX_NAMES.get((cls, msg_id), f"0x{cls:02X}/0x{msg_id:02X}"),
                checksum_ok=ok,
                length=length,
                arrival=stamp_at(end - 1),
            )
            if ok and (cls, msg_id) == UBX_NAV_PVT:
                decode_nav_pvt(payload, message)
            elif ok and (cls, msg_id) == UBX_NAV_TIMEGPS:
                decode_nav_timegps(payload, message)
            messages.append(message)
            index = end
            continue

        if buffer[index] == 0x24:  # '$'
            end = buffer.find(b"\n", index)
            if end < 0:
                break
            text = bytes(buffer[index:end]).decode("ascii", errors="replace").strip()
            decoded = decode_nmea(text, stamp_at(end))
            if decoded is not None:
                sentences.append(decoded)
                index = end + 1
                continue
            # A '$' that does not begin a valid sentence: step one byte.
            skipped += 1
            index += 1
            continue

        skipped += 1
        index += 1

    return sentences, messages, skipped


# -------------------------------------------------------------- input reading


def network_layer(link_type: int, frame: bytes) -> tuple[bytes, int] | None:
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


def read_pcap(
    path: Path, port: int
) -> tuple[list[Sentence], list[UbxMessage], dict]:
    """Reads a TCP capture, reassembling streams and co-parsing their content.

    Args:
        path: Capture file.
        port: TCP port carrying the GPS feed.

    Returns:
        Tuple of (sentences, ubx messages, capture statistics).

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
    frames = 0
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
        frames += 1
        when = datetime.fromtimestamp(seconds + fraction / divisor, tz=timezone.utc)

        located = network_layer(link_type, frame)
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

    sentences: list[Sentence] = []
    messages: list[UbxMessage] = []
    skipped_total = 0
    for chunks in streams.values():
        buffer = bytearray()
        stamps: list[datetime] = []
        for sequence in sorted(chunks):
            payload, when = chunks[sequence]
            buffer.extend(payload)
            stamps.extend([when] * len(payload))
        found_nmea, found_ubx, skipped = parse_stream(bytes(buffer), stamps)
        sentences.extend(found_nmea)
        messages.extend(found_ubx)
        skipped_total += skipped

    stats = {
        "frames": frames,
        "tcp_streams": len(streams),
        "unparsed_bytes": skipped_total,
    }
    return sentences, messages, stats


# Markers identifying the GNSS emulator's own log. D4 is a DUT-side
# requirement, so the emulator's log is the wrong artifact for it: the emulator
# emitting NMEA says nothing about whether the DUT received any.
EMULATOR_LOG_MARKERS = ("HWILgnssEmulator", "Route waypoint:", "tena-gnss-emulator")


def read_text(path: Path) -> tuple[list[Sentence], list[UbxMessage], dict]:
    """Reads NMEA sentences from a text log.

    Args:
        path: Log file.

    Returns:
        Tuple of (sentences, empty UBX list, statistics).
    """
    sentences: list[Sentence] = []
    lines = 0
    emulator_markers = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            lines += 1
            arrival = None
            for pattern, kind in TIMESTAMP_RES:
                found = pattern.match(line)
                if not found:
                    continue
                try:
                    if kind == "iso":
                        parsed = datetime.fromisoformat(
                            found.group(1).replace(" ", "T")
                        )
                        arrival = (
                            parsed.replace(tzinfo=timezone.utc)
                            if parsed.tzinfo is None
                            else parsed
                        )
                    else:
                        arrival = datetime.fromtimestamp(
                            float(found.group(1)), tz=timezone.utc
                        )
                except ValueError:
                    arrival = None
                break
            if any(marker in line for marker in EMULATOR_LOG_MARKERS):
                emulator_markers += 1
            start = line.find("$")
            if start >= 0:
                decoded = decode_nmea(line[start:], arrival)
                if decoded is not None:
                    sentences.append(decoded)
    return sentences, [], {"lines": lines, "emulator_markers": emulator_markers}


# ------------------------------------------------------------------- verdict


@dataclass
class Result:
    """Outcome of the D4 check."""

    status: str = "NO_DATA"
    summary: str = ""
    observations: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def median(values: list[float]) -> float:
    """Returns the median of a non-empty list.

    Args:
        values: Samples.
    """
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def verify(
    sentences: list[Sentence],
    messages: list[UbxMessage],
    stats: dict,
    require_nmea: list[str],
    min_messages: int,
    max_checksum_error_rate: float,
) -> Result:
    """Evaluates the parsed stream against the D4 criteria.

    Args:
        sentences: Decoded NMEA sentences.
        messages: Decoded UBX messages.
        stats: Capture statistics.
        require_nmea: NMEA sentence types that must be present. Empty means
            capabilities may be satisfied from either protocol.
        min_messages: Minimum total messages for a conclusive result.
        max_checksum_error_rate: Allowed fraction of checksum failures.

    Returns:
        The verification result.
    """
    result = Result()
    result.metrics.update(stats)

    if stats.get("emulator_markers"):
        result.observations.append(
            f"WARNING: this input carries {stats['emulator_markers']} GNSS "
            "emulator log marker(s), so it appears to be the emulator's own "
            "log rather than a capture taken at the DUT. D4 is about what the "
            "DUT received; the emulator emitting NMEA does not establish that. "
            "Capture the netcat port on the DUT instead. The result below "
            "describes the emulator's output, not the DUT's input."
        )

    total = len(sentences) + len(messages)
    if total == 0:
        result.summary = "No NMEA sentences or UBX messages found in the input."
        result.observations.append(
            "Confirm the capture filter and port, and that the GPS source was "
            "running for the duration of the capture."
        )
        return result

    # --- NMEA inventory
    nmea_counts: dict[str, int] = {}
    for sentence in sentences:
        nmea_counts[sentence.kind] = nmea_counts.get(sentence.kind, 0) + 1
    nmea_checked = [s for s in sentences if s.checksum_ok is not None]
    nmea_bad = [s for s in nmea_checked if s.checksum_ok is False]

    # --- UBX inventory
    ubx_counts: dict[str, int] = {}
    for message in messages:
        ubx_counts[message.name] = ubx_counts.get(message.name, 0) + 1
    ubx_bad = [m for m in messages if not m.checksum_ok]

    if sentences:
        result.observations.append(
            f"NMEA: {len(sentences)} sentence(s) - "
            + ", ".join(f"{k}={v}" for k, v in sorted(nmea_counts.items()))
        )
        if nmea_checked:
            rate = len(nmea_bad) / len(nmea_checked)
            result.observations.append(
                f"      {len(nmea_bad)} of {len(nmea_checked)} failed checksum "
                f"({rate:.4%})."
            )
    if messages:
        result.observations.append(
            f"UBX:  {len(messages)} message(s) - "
            + ", ".join(f"{k}={v}" for k, v in sorted(ubx_counts.items()))
        )
        result.observations.append(
            f"      {len(ubx_bad)} of {len(messages)} failed checksum."
        )

    checked = len(nmea_checked) + len(messages)
    failures = len(nmea_bad) + len(ubx_bad)
    error_rate = failures / checked if checked else 0.0

    result.metrics["nmea_sentences"] = len(sentences)
    result.metrics["nmea_types"] = nmea_counts
    result.metrics["ubx_messages"] = len(messages)
    result.metrics["ubx_types"] = ubx_counts
    result.metrics["checksum_checked"] = checked
    result.metrics["checksum_failures"] = failures

    if stats.get("unparsed_bytes"):
        result.observations.append(
            f"{stats['unparsed_bytes']} byte(s) matched neither framing and were "
            "skipped."
        )

    # --- Capabilities: position and time, from either protocol.
    nmea_positions = [s for s in sentences if s.latitude is not None]
    pvt = [
        m
        for m in messages
        if m.cls_id == UBX_NAV_PVT and m.checksum_ok and m.latitude is not None
    ]
    positions = [(s.latitude, s.longitude) for s in nmea_positions] + [
        (m.latitude, m.longitude) for m in pvt
    ]
    has_position = bool(positions)

    time_sources = []
    if any(s.kind in ("ZDA", "RMC", "GGA") for s in sentences):
        time_sources.append("NMEA")
    if any(
        m.cls_id in (UBX_NAV_PVT, UBX_NAV_TIMEGPS) and m.checksum_ok for m in messages
    ):
        time_sources.append("UBX")
    has_time = bool(time_sources)

    result.observations.append(
        f"Position available: {'yes' if has_position else 'NO'}"
        + (
            f" ({len(nmea_positions)} from NMEA, {len(pvt)} from UBX NAV-PVT)"
            if has_position
            else ""
        )
    )
    result.observations.append(
        f"Time available: {'yes' if has_time else 'NO'}"
        + (f" (from {', '.join(time_sources)})" if has_time else "")
    )
    result.metrics["has_position"] = has_position
    result.metrics["has_time"] = has_time

    if pvt:
        fix3d = sum(1 for m in pvt if m.fix_type == 3)
        sats = [m.num_sv for m in pvt if m.num_sv is not None]
        h_acc = [m.h_acc_m for m in pvt if m.h_acc_m is not None]
        t_acc = [m.t_acc_ns for m in pvt if m.t_acc_ns is not None]
        speeds = [m.speed_mps for m in pvt if m.speed_mps is not None]
        result.observations.append(
            f"NAV-PVT: {fix3d}/{len(pvt)} with a 3D fix, "
            f"{median([float(s) for s in sats]):.0f} satellites (median), "
            f"hAcc {median(h_acc):.2f} m, tAcc {median([float(t) for t in t_acc]):.0f} ns."
        )
        result.metrics["nav_pvt_3d_fixes"] = fix3d
        result.metrics["nav_pvt_median_hacc_m"] = round(median(h_acc), 3)
        result.metrics["nav_pvt_median_tacc_ns"] = int(median([float(t) for t in t_acc]))
        if speeds:
            result.metrics["nav_pvt_max_speed_mps"] = round(max(speeds), 3)

    distinct = {(round(lat, 7), round(lon, 7)) for lat, lon in positions}
    if positions:
        result.observations.append(
            f"{len(positions)} position(s) carried, {len(distinct)} distinct."
        )
        result.metrics["positions"] = len(positions)
        result.metrics["distinct_positions"] = len(distinct)

    # --- Arrival rate
    arrivals = sorted(
        [s.arrival for s in sentences if s.arrival]
        + [m.arrival for m in messages if m.arrival]
    )
    if len(arrivals) >= 3:
        gaps = [
            (arrivals[i] - arrivals[i - 1]).total_seconds()
            for i in range(1, len(arrivals))
            if (arrivals[i] - arrivals[i - 1]).total_seconds() > 0
        ]
        if gaps:
            span = (arrivals[-1] - arrivals[0]).total_seconds()
            result.observations.append(
                f"Arrival rate ~{1.0 / median(gaps):.2f} Hz over {span:.1f} s."
            )
            result.metrics["arrival_rate_hz"] = round(1.0 / median(gaps), 3)
            result.metrics["span_seconds"] = round(span, 3)

    # --- Time resolution note, which bears on P7 rather than D4.
    decimals = {s.time_decimals for s in sentences if s.time_decimals is not None}
    if decimals:
        finest = 1000.0 / (10 ** max(decimals))
        result.metrics["nmea_time_resolution_ms"] = finest
        if finest >= 10.0:
            result.observations.append(
                f"NOTE: NMEA time fields carry {max(decimals)} decimal place(s), "
                f"a resolution of {finest:.0f} ms. That is the whole of the P7 "
                "10 ms budget, so these sentences cannot support a P7 "
                "measurement. UBX NAV-TIMEGPS in the same stream carries "
                "nanosecond accuracy and should be used instead."
            )

    for sentence in sentences[:2]:
        result.observations.append(f"sample NMEA: {sentence.raw[:100]}")

    # --- Verdict
    problems: list[str] = []
    if require_nmea:
        missing = [k for k in require_nmea if nmea_counts.get(k, 0) == 0]
        if missing:
            problems.append(
                f"required NMEA type(s) absent: {', '.join(missing)}"
            )
    else:
        if not has_position:
            problems.append(
                "the stream carried no position from either NMEA (GGA/RMC) or "
                "UBX (NAV-PVT)"
            )
        if not has_time:
            problems.append("the stream carried no time from either protocol")

    if total < min_messages:
        problems.append(
            f"only {total} message(s) captured, below the minimum of {min_messages}"
        )
    if error_rate > max_checksum_error_rate:
        problems.append(
            f"checksum failure rate {error_rate:.4%} exceeds the allowed "
            f"{max_checksum_error_rate:.4%}"
        )

    if has_position and len(distinct) == 1:
        result.observations.append(
            "NOTE: every position carries the same coordinates. The DUT is "
            "receiving GPS data, but the source is stationary -- check that a "
            "route is loaded if this run was meant to move."
        )

    if problems:
        for problem in problems:
            result.observations.append(f"PROBLEM: {problem}")
        result.status = "FAIL"
        result.summary = "; ".join(problems)
    else:
        parts = []
        if sentences:
            parts.append(f"{len(sentences)} NMEA sentence(s)")
        if messages:
            parts.append(f"{len(messages)} UBX message(s)")
        result.status = "PASS"
        result.summary = (
            f"DUT received {' and '.join(parts)} carrying position and time."
        )
    return result


def render(result: Result, verbose: bool) -> None:
    """Prints the result.

    Args:
        result: Verification result.
        verbose: Whether to print metrics.
    """
    print()
    print("D4 - Acceptance of simulated GPS input")
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
            "Verify D4: the DUT accepts emulated GPS input via netcat-gpsd. "
            "Parses both NMEA sentences and UBX binary messages."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Collect the capture on the DUT with:\n"
            "    tcpdump -i any -w d4_nmea.pcap tcp port 5000\n"
            "\n"
            "Capture BOTH directions - do not add a `dst` qualifier."
        ),
    )
    parser.add_argument(
        "input", type=Path, help="Capture (.pcap) or text log of the GPS feed."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"TCP port carrying the feed in a capture (default: {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--require-nmea",
        nargs="+",
        default=[],
        metavar="TYPE",
        help=(
            "Require these NMEA sentence types specifically, e.g. GGA RMC ZDA. "
            "Use when the test demands NMEA-only operation. By default the "
            "check requires position and time from either NMEA or UBX."
        ),
    )
    parser.add_argument(
        "--min-messages",
        type=int,
        default=DEFAULT_MIN_MESSAGES,
        help=f"Minimum total messages (default: {DEFAULT_MIN_MESSAGES}).",
    )
    parser.add_argument(
        "--max-checksum-errors",
        type=float,
        default=0.0,
        metavar="FRACTION",
        help="Allowed checksum failure rate as a fraction (default: 0.0).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead.")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Also print metrics."
    )
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 2

    try:
        if args.input.suffix.lower() in (".pcap", ".cap", ".dmp"):
            sentences, messages, stats = read_pcap(args.input, args.port)
        else:
            sentences, messages, stats = read_text(args.input)
    except (OSError, ValueError) as exc:
        print(f"Could not read {args.input}: {exc}", file=sys.stderr)
        return 2

    result = verify(
        sentences,
        messages,
        stats,
        [r.upper() for r in args.require_nmea],
        args.min_messages,
        args.max_checksum_errors,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "requirement": "D4",
                    "title": "Acceptance of simulated GPS input",
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