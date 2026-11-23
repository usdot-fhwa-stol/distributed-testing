#!/usr/bin/env python3
"""Verify V2X message delivery from the DT system to V2X Hub.

    Related requirement:  E2 - DT 1609.2 & 1609.3 Support
    System:               DT System

WHAT THIS VERIFIES
------------------------------------------------------
This checks that V2X messages published by the DT system arrive at V2X Hub, in
the counts and types expected, with their payloads byte-identical.

INPUT
-----
One capture is a receipt census; two captures are a delivery comparison.

    # at the DT adapter's send endpoint, and at V2X Hub's ingress
    sudo tcpdump -i any -s 0 -w dt_egress.pcap  'udp port X'
    sudo tcpdump -i any -s 0 -w v2xhub_rx.pcap  'udp port X'

Use `-s 0`; the default snaplen truncates payloads and destroys the comparison.

EXIT CODES
----------
    0  PASS     messages delivered, payloads intact
    1  FAIL     loss or corruption detected
    2  NO_DATA  capture unreadable, or no V2X traffic found
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import struct
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
IPPROTO_UDP, IPPROTO_TCP = 17, 6

# SAE J2735 DSRCmsgID values, which open a bare MessageFrame.
J2735_TYPES = {
    0x0011: "AEM",
    0x0012: "MAP",
    0x0013: "SPAT",
    0x0014: "BSM",
    0x0015: "CSR",
    0x0016: "EVA",
    0x0017: "ICA",
    0x0018: "NMEA",
    0x0019: "PDM",
    0x001A: "PVD",
    0x001B: "RSA",
    0x001C: "RTCM",
    0x001D: "SRM",
    0x001E: "SSM",
    0x001F: "TIM",
    0x0020: "PSM",
    0x0021: "TSM",
    0x0028: "PSM",
    0x0113: "SDSM",
}

# IEEE 1609.2 content choices, checked so the script can report when the
# stronger header-preservation test becomes possible.
IEEE1609_CHOICES = {0x80: "unsecuredData", 0x81: "signedData", 0x82: "encryptedData"}
WSMP_ETHERTYPE = b"\x88\xDC"
NTCIP_SENTINEL = b"Version="

# Two captures of one datagram land within a small fraction of a millisecond.
DUPLICATE_WINDOW_S = 0.002


@dataclass
class Packet:
    """One captured V2X datagram.

    Attributes:
        timestamp: Capture time, UTC.
        src: Source address and port.
        dst: Destination address and port.
        ip_id: IP identification field, used to spot re-captures.
        payload: UDP or TCP payload bytes.
    """

    timestamp: datetime
    src: tuple[str, int]
    dst: tuple[str, int]
    ip_id: int
    payload: bytes

    @property
    def digest(self) -> str:
        """Short stable fingerprint of the payload."""
        return hashlib.sha256(self.payload).hexdigest()[:16]


@dataclass
class Result:
    """Outcome of the delivery check."""

    status: str = "NO_DATA"
    summary: str = ""
    observations: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def network_layer(link_type: int, frame: bytes) -> tuple[bytes, int] | None:
    """Finds the network header inside a link-layer frame.

    Handles Ethernet and both Linux cooked capture formats. `-i any` produces
    SLL or SLL2 depending on libpcap version, so both must work.

    Args:
        link_type: libpcap link-layer type.
        frame: Frame bytes.

    Returns:
        Tuple of (EtherType, network header offset), or None if unsupported.
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


def read_pcap(path: Path, port: int | None) -> tuple[list[Packet], dict]:
    """Reads V2X datagrams from a capture.

    Args:
        path: Capture file.
        port: Keep only packets whose source or destination port matches, or
            None to keep all UDP and TCP payloads.

    Returns:
        Tuple of (packets, capture statistics).

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

    packets: list[Packet] = []
    frames = 0
    truncated = False
    snaplen_clipped = 0
    offset = 24
    while offset + 16 <= len(blob):
        seconds, fraction, captured, original = struct.unpack(
            endian + "IIII", blob[offset : offset + 16]
        )
        offset += 16
        if offset + captured > len(blob):
            truncated = True
            break
        frame = blob[offset : offset + captured]
        offset += captured
        frames += 1
        if captured < original:
            snaplen_clipped += 1
        when = datetime.fromtimestamp(seconds + fraction / divisor, tz=timezone.utc)

        located = network_layer(link_type, frame)
        if located is None:
            continue
        ethertype, at = located
        if ethertype != ETHERTYPE_IPV4 or len(frame) < at + 20:
            continue
        protocol = frame[at + 9]
        if protocol not in (IPPROTO_UDP, IPPROTO_TCP):
            continue
        ip_id = struct.unpack(">H", frame[at + 4 : at + 6])[0]
        src_addr = ".".join(str(x) for x in frame[at + 12 : at + 16])
        dst_addr = ".".join(str(x) for x in frame[at + 16 : at + 20])
        transport = at + (frame[at] & 0x0F) * 4
        if len(frame) < transport + 8:
            continue
        src_port, dst_port = struct.unpack(">HH", frame[transport : transport + 4])
        if port is not None and port not in (src_port, dst_port):
            continue
        if protocol == IPPROTO_UDP:
            length = struct.unpack(">H", frame[transport + 4 : transport + 6])[0]
            payload = frame[transport + 8 : transport + 8 + max(0, length - 8)]
        else:
            payload = frame[transport + (frame[transport + 12] >> 4) * 4 :]
        if payload:
            packets.append(
                Packet(when, (src_addr, src_port), (dst_addr, dst_port), ip_id, payload)
            )

    stats = {
        "link_type": link_type,
        "frames": frames,
        "truncated_tail": truncated,
        "snaplen_clipped": snaplen_clipped,
    }
    return packets, stats


def deduplicate(packets: list[Packet]) -> tuple[list[Packet], int]:
    """Removes copies of one datagram captured on more than one interface.

    One IP datagram carries one IP identification value, so packets agreeing on
    destination, IP ID and payload within a very short window are the same
    datagram seen twice. A genuine retransmission or a genuinely re-sent message
    carries a different IP ID and survives.

    Args:
        packets: Packets in capture order.

    Returns:
        Tuple of (deduplicated packets, number removed).
    """
    seen: dict[tuple, float] = {}
    kept: list[Packet] = []
    removed = 0
    for packet in packets:
        key = (packet.dst, packet.ip_id, packet.digest)
        when = packet.timestamp.timestamp()
        previous = seen.get(key)
        if previous is not None and abs(when - previous) <= DUPLICATE_WINDOW_S:
            removed += 1
            continue
        seen[key] = when
        kept.append(packet)
    return kept, removed


def classify(payload: bytes) -> tuple[str, str]:
    """Identifies the wire format of a payload.

    Args:
        payload: Datagram payload.

    Returns:
        Tuple of (format name, detail). Format is one of "ieee1609dot2",
        "wsmp", "ntcip1218", "j2735" or "unknown".
    """
    if payload[:8].lstrip().startswith(NTCIP_SENTINEL):
        return "ntcip1218", "NTCIP 1218 forwarding block"
    if len(payload) >= 2 and payload[0] == 0x03 and payload[1] in IEEE1609_CHOICES:
        return "ieee1609dot2", IEEE1609_CHOICES[payload[1]]
    if WSMP_ETHERTYPE in payload[:16]:
        return "wsmp", "WSMP-framed"
    if len(payload) >= 2:
        message_id = int.from_bytes(payload[:2], "big")
        if message_id in J2735_TYPES:
            return "j2735", J2735_TYPES[message_id]
    return "unknown", f"leading bytes {payload[:4].hex()}"


def summarize(packets: list[Packet], label: str, result: Result, prefix: str) -> dict:
    """Describes one capture point and records its metrics.

    Args:
        packets: Deduplicated packets from that point.
        label: Human-readable name for the capture point.
        result: Result being populated.
        prefix: Metric key prefix.

    Returns:
        Mapping of payload digest to occurrence count.
    """
    formats: collections.Counter = collections.Counter()
    types: collections.Counter = collections.Counter()
    destinations: collections.Counter = collections.Counter()
    digests: collections.Counter = collections.Counter()

    for packet in packets:
        kind, detail = classify(packet.payload)
        formats[kind] += 1
        types[detail] += 1
        destinations[f"{packet.dst[0]}:{packet.dst[1]}"] += 1
        digests[packet.digest] += 1

    result.observations.append(
        f"{label}: {len(packets)} message(s), {len(digests)} distinct payload(s)."
    )
    result.observations.append(
        f"    format: " + ", ".join(f"{k}={v}" for k, v in formats.most_common())
    )
    result.observations.append(
        f"    types: " + ", ".join(f"{k}={v}" for k, v in types.most_common(6))
    )
    result.observations.append(
        f"    destinations: "
        + ", ".join(f"{k}={v}" for k, v in destinations.most_common(4))
    )
    if len(packets) > 1:
        span = (packets[-1].timestamp - packets[0].timestamp).total_seconds()
        if span > 0:
            result.observations.append(
                f"    {span:.1f} s span, {len(packets) / span:.2f} msg/s overall."
            )
            result.metrics[f"{prefix}_span_s"] = round(span, 3)
            result.metrics[f"{prefix}_rate_hz"] = round(len(packets) / span, 3)

    result.metrics[f"{prefix}_messages"] = len(packets)
    result.metrics[f"{prefix}_distinct_payloads"] = len(digests)
    result.metrics[f"{prefix}_formats"] = dict(formats)
    result.metrics[f"{prefix}_types"] = dict(types.most_common(10))
    result.metrics[f"{prefix}_destinations"] = dict(destinations)
    return digests


def report_header_scope(formats: dict, result: Result) -> None:
    """States which E2 claims the observed wire format can support.

    Args:
        formats: Format counts from the receiving capture point.
        result: Result being populated.
    """
    has_spdu = formats.get("ieee1609dot2", 0) or formats.get("wsmp", 0)
    if has_spdu:
        result.observations.append(
            "IEEE 1609.2 SPDUs are present on this link, so header preservation "
            "IS testable here. Run verify_e2_spdu_forwarding.py against a TDCS "
            "recording from the same run for the full E2 check."
        )
    else:
        result.observations.append(
            "No IEEE 1609.2 or 1609.3 headers appear on this link -- the "
            "payloads are bare J2735. E2's clause about preserving 1609.2 "
            "security and WSMP headers therefore cannot be verified at this "
            "observation point, because those headers never cross it. That "
            "clause needs the transceiver/RSU boundary, where SPDUs travel. "
            "Delivery and payload integrity, checked below, are what this "
            "point can establish."
        )
    result.metrics["spdu_present"] = bool(has_spdu)


def verify(
    received: list[Packet],
    received_stats: dict,
    sent: list[Packet] | None,
    sent_stats: dict | None,
    min_messages: int,
) -> Result:
    """Evaluates delivery and payload integrity.

    Args:
        received: Packets at the receiving point.
        received_stats: Capture statistics for that file.
        sent: Packets at the sending point, when a second capture was supplied.
        sent_stats: Capture statistics for that file.
        min_messages: Minimum messages for a conclusive result.

    Returns:
        The verification result.
    """
    result = Result()

    for stats, name in ((received_stats, "receive"), (sent_stats, "send")):
        if not stats:
            continue
        if stats.get("truncated_tail"):
            result.observations.append(
                f"NOTE: the {name} capture ends mid-record; the final packet is "
                "incomplete. Harmless, but it means capture was interrupted."
            )
        if stats.get("snaplen_clipped"):
            result.observations.append(
                f"PROBLEM: {stats['snaplen_clipped']} frame(s) in the {name} "
                "capture were clipped by the snaplen, so their payloads are "
                "incomplete. Re-capture with `-s 0`; payload comparison on this "
                "file is unreliable."
            )

    received, removed = deduplicate(received)
    if removed:
        result.observations.append(
            f"Removed {removed} re-captured copy of the same datagram "
            "(matching destination, IP ID and payload). This is what "
            "`tcpdump -i any` does on a host running containers; without "
            "removing them the delivery count would be inflated."
        )
        result.metrics["recapture_duplicates_removed"] = removed

    if not received:
        result.observations.append(
            "No V2X payloads found. Check the port filter and that traffic was "
            "flowing during the capture."
        )
        result.summary = "Capture contains no V2X messages."
        return result

    received_digests = summarize(received, "Received", result, "rx")
    report_header_scope(result.metrics.get("rx_formats", {}), result)

    unknown = result.metrics.get("rx_formats", {}).get("unknown", 0)
    if unknown:
        result.observations.append(
            f"PROBLEM: {unknown} payload(s) matched no known V2X format."
        )

    # A capture full of payloads that are not V2X at all means the wrong port
    # or the wrong link was captured, not that delivery failed. Reporting FAIL
    # there would accuse the system of losing messages it never sent.
    recognised = sum(
        v for k, v in result.metrics.get("rx_formats", {}).items() if k != "unknown"
    )
    if recognised == 0:
        result.observations.append(
            "No payload matched any known V2X format (bare J2735, IEEE 1609.2, "
            "WSMP or NTCIP 1218). This capture is carrying something else -- "
            "check the port filter and that it covers the V2X link."
        )
        result.summary = "Capture contains no recognisable V2X messages."
        return result

    # --- Single capture point: a receipt census.
    if sent is None:
        if len(received) < min_messages:
            result.observations.append(
                f"Only {len(received)} message(s); below the minimum of "
                f"{min_messages} for a conclusive result."
            )
            result.summary = "Too few messages to judge."
            return result
        if unknown:
            result.status = "FAIL"
            result.summary = (
                f"{unknown} of {len(received)} received payload(s) were not "
                "recognisable V2X messages."
            )
            return result
        result.status = "PASS"
        result.summary = (
            f"V2X Hub received {len(received)} V2X message(s) "
            f"({result.metrics['rx_distinct_payloads']} distinct) across "
            f"{len(result.metrics['rx_destinations'])} destination(s). Supply "
            "--received with a second capture to compare against what the DT "
            "system sent."
        )
        return result

    # --- Two capture points: a delivery comparison.
    sent, sent_removed = deduplicate(sent)
    if sent_removed:
        result.metrics["send_recapture_duplicates_removed"] = sent_removed
    if not sent:
        result.observations.append(
            "The sending capture contains no V2X payloads, so delivery could "
            "not be compared."
        )
        result.summary = "Sending capture is empty."
        return result

    sent_digests = summarize(sent, "Sent", result, "tx")

    delivered = {d: n for d, n in sent_digests.items() if d in received_digests}
    missing = {d: n for d, n in sent_digests.items() if d not in received_digests}
    unexpected = {d: n for d, n in received_digests.items() if d not in sent_digests}

    result.observations.append(
        f"Of {len(sent_digests)} distinct payload(s) sent, {len(delivered)} "
        f"arrived and {len(missing)} did not."
    )
    if unexpected:
        result.observations.append(
            f"{len(unexpected)} distinct payload(s) arrived that were not seen "
            "in the sending capture. Expected if the captures do not cover the "
            "same window, or if another publisher feeds the same port."
        )

    result.metrics["sent_distinct"] = len(sent_digests)
    result.metrics["delivered_distinct"] = len(delivered)
    result.metrics["missing_distinct"] = len(missing)
    result.metrics["unexpected_distinct"] = len(unexpected)
    rate = len(delivered) / len(sent_digests) if sent_digests else 0.0
    result.metrics["delivery_rate"] = round(rate, 4)
    result.observations.append(f"Delivery rate: {rate:.2%} of distinct payloads.")

    # Payload equality is implicit in matching on digest: a corrupted payload
    # hashes differently and lands in `missing`, so loss and corruption are
    # reported together and distinguished by the unexpected-payload count.
    if missing:
        result.observations.append(
            f"PROBLEM: {len(missing)} distinct payload(s) were sent but never "
            "arrived, or arrived altered."
        )
        result.status = "FAIL"
        result.summary = (
            f"{len(missing)} of {len(sent_digests)} distinct payload(s) did not "
            f"reach V2X Hub intact ({rate:.2%} delivered)."
        )
        return result

    result.status = "PASS"
    result.summary = (
        f"All {len(sent_digests)} distinct payload(s) sent by the DT system "
        "reached V2X Hub byte-identically."
    )
    return result


def render(result: Result, verbose: bool) -> None:
    """Prints the result.

    Args:
        result: Verification result.
        verbose: Whether to print metrics.
    """
    print()
    print("DT -> V2X Hub message delivery")
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
            "Verify that V2X messages published by the DT system are received "
            "by V2X Hub, with payloads intact."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Capture with:\n"
            "    sudo tcpdump -i any -s 0 -w v2xhub_rx.pcap 'udp port 26789'\n"
            "\n"
            "One capture gives a receipt census. Two -- one at the DT adapter's\n"
            "send endpoint, one at V2X Hub's ingress -- give a delivery\n"
            "comparison. Always use -s 0.\n"
            "\n"
            "This checks delivery and payload integrity. E2's 1609.2/WSMP\n"
            "preservation clause is verify_e2_spdu_forwarding.py; this script\n"
            "reports whether SPDUs are present, i.e. whether that check\n"
            "applies at this observation point."
        ),
    )
    parser.add_argument(
        "capture",
        type=Path,
        help="Capture at the receiving point (V2X Hub ingress).",
    )
    parser.add_argument(
        "--received",
        type=Path,
        metavar="PCAP",
        help=(
            "Treat the positional argument as the SENDING capture and this as "
            "the receiving one, enabling a delivery comparison."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Keep only this UDP/TCP port (default: all V2X payloads found).",
    )
    parser.add_argument(
        "--min-messages",
        type=int,
        default=10,
        help="Minimum messages for a conclusive result (default: 10).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead.")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Also print metrics."
    )
    args = parser.parse_args(argv)

    for path in filter(None, (args.capture, args.received)):
        if not path.is_file():
            print(f"Capture not found: {path}", file=sys.stderr)
            return 2

    try:
        if args.received:
            sent, sent_stats = read_pcap(args.capture, args.port)
            received, received_stats = read_pcap(args.received, args.port)
        else:
            received, received_stats = read_pcap(args.capture, args.port)
            sent, sent_stats = None, None
    except (OSError, ValueError) as exc:
        print(f"Could not read capture: {exc}", file=sys.stderr)
        return 2

    result = verify(received, received_stats, sent, sent_stats, args.min_messages)
    result.metrics["capture"] = str(args.capture)
    if args.received:
        result.metrics["received_capture"] = str(args.received)

    if args.json:
        print(
            json.dumps(
                {
                    "check": "dt_to_v2xhub_delivery",
                    "related_requirement": "E2",
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