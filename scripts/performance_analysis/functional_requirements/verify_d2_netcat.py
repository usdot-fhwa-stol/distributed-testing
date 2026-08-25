#!/usr/bin/env python3
"""D2 - Netcat support.

    Requirement:  The DUT shall support the use of Netcat for NMEA related data
                  exchange.
    Criteria:     DUT uses Netcat for NMEA data exchange.
    System:       DUT (OBU)

WHAT THIS VERIFIES
------------------
A listener was bound on the NMEA port, accepted an inbound TCP connection, and 
received data on it. 

The script checks the TCP handshake in a pcap file from running tcpdump on the OBU. 
A SYN-ACK sent from the listener port verifies that the connection was accepted,
and payload bytes that follow verify the connection carry data.

This script does not inspect the payload contents -- that is D4's job. It only
establishes that the netcat data path existed and carried traffic.

INPUT
-----
A libpcap capture of the NMEA port, collected on the DUT:

    tcpdump -i any -w d2_nmea.pcap tcp port X


EXIT CODES
----------
    0  PASS     requirement met
    1  FAIL     requirement not met
    2  NO_DATA  capture unreadable or contains nothing on the port
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# libpcap file magics -> (struct byte-order, timestamps are nanoseconds)
PCAP_MAGICS = {
    b"\xd4\xc3\xb2\xa1": ("<", False),
    b"\xa1\xb2\xc3\xd4": (">", False),
    b"\x4d\x3c\xb2\xa1": ("<", True),
    b"\xa1\xb2\x3c\x4d": (">", True),
}

# Link-layer types. Captures from these OBUs have arrived both as plain
# Ethernet and as Linux cooked captures (`tcpdump -i any`), so both must be
# handled or an entire capture silently yields nothing.
LINKTYPE_ETHERNET = 1
LINKTYPE_RAW = 101
LINKTYPE_LINUX_SLL = 113
LINKTYPE_LINUX_SLL2 = 276

ETHERTYPE_IPV4 = b"\x08\x00"
ETHERTYPE_IPV6 = b"\x86\xDD"
ETHERTYPE_VLAN = b"\x81\x00"

IPPROTO_TCP = 6

TCP_FIN, TCP_SYN, TCP_RST, TCP_PSH, TCP_ACK = 0x01, 0x02, 0x04, 0x08, 0x10

DEFAULT_PORT = 5000


# Parsing


@dataclass
class Segment:
    """One captured TCP segment.

    Attributes:
        timestamp: Capture time, UTC.
        src_addr: Source IP address, hex string.
        src_port: Source TCP port.
        dst_addr: Destination IP address, hex string.
        dst_port: Destination TCP port.
        flags: TCP flag bits.
        payload_len: Number of payload bytes carried.
    """

    timestamp: datetime
    src_addr: str
    src_port: int
    dst_addr: str
    dst_port: int
    flags: int
    payload_len: int

    @property
    def is_syn_only(self) -> bool:
        """True for a connection-opening SYN with no ACK."""
        return bool(self.flags & TCP_SYN) and not (self.flags & TCP_ACK)

    @property
    def is_syn_ack(self) -> bool:
        """True for a SYN+ACK, which only a listener sends."""
        return bool(self.flags & TCP_SYN) and bool(self.flags & TCP_ACK)


def read_frames(path: Path) -> tuple[int, list[tuple[datetime, bytes]]]:
    """Reads a classic libpcap file into timestamped frames.

    A truncated final record is tolerated so a capture cut short still yields
    everything before the cut.

    Args:
        path: Capture file.

    Returns:
        Tuple of (link-layer type, list of (timestamp, frame bytes)).

    Raises:
        ValueError: If the file is not a classic libpcap capture.
    """
    blob = path.read_bytes()
    if len(blob) < 24 or blob[:4] not in PCAP_MAGICS:
        if blob[:4] == b"\x0a\x0d\x0d\x0a":
            raise ValueError(
                f"{path.name} is pcapng, not classic pcap. Convert it with "
                "`editcap -F pcap in.pcapng out.pcap`."
            )
        raise ValueError(f"{path.name} is not a libpcap capture")

    endian, nanoseconds = PCAP_MAGICS[blob[:4]]
    divisor = 1e9 if nanoseconds else 1e6
    link_type = struct.unpack(endian + "I", blob[20:24])[0]

    frames: list[tuple[datetime, bytes]] = []
    offset = 24
    while offset + 16 <= len(blob):
        seconds, fraction, captured, _orig = struct.unpack(
            endian + "IIII", blob[offset : offset + 16]
        )
        offset += 16
        if offset + captured > len(blob):
            break
        when = datetime.fromtimestamp(seconds + fraction / divisor, tz=timezone.utc)
        frames.append((when, blob[offset : offset + captured]))
        offset += captured
    return link_type, frames


def network_layer(link_type: int, frame: bytes) -> tuple[bytes, int] | None:
    """Finds the network header inside a link-layer frame.

    Args:
        link_type: libpcap link-layer type.
        frame: Frame bytes.

    Returns:
        Tuple of (EtherType, offset of network header), or None if unsupported.
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

    # Step over 802.1Q VLAN tags.
    while ethertype == ETHERTYPE_VLAN and len(frame) >= offset + 4:
        ethertype, offset = frame[offset + 2 : offset + 4], offset + 4
    return ethertype, offset


def tcp_segments(
    link_type: int, frames: list[tuple[datetime, bytes]], port: int
) -> list[Segment]:
    """Extracts TCP segments involving a given port.

    Args:
        link_type: libpcap link-layer type.
        frames: Timestamped frames.
        port: Keep segments whose source or destination port matches.

    Returns:
        Segments in capture order.
    """
    segments: list[Segment] = []
    for when, frame in frames:
        located = network_layer(link_type, frame)
        if located is None:
            continue
        ethertype, offset = located

        if ethertype == ETHERTYPE_IPV4:
            if len(frame) < offset + 20:
                continue
            header_len = (frame[offset] & 0x0F) * 4
            if frame[offset + 9] != IPPROTO_TCP:
                continue
            total_len = struct.unpack(">H", frame[offset + 2 : offset + 4])[0]
            src = frame[offset + 12 : offset + 16].hex()
            dst = frame[offset + 16 : offset + 20].hex()
            tcp_at = offset + header_len
            ip_payload_len = total_len - header_len
        elif ethertype == ETHERTYPE_IPV6:
            if len(frame) < offset + 40:
                continue
            if frame[offset + 6] != IPPROTO_TCP:
                continue
            payload_len = struct.unpack(">H", frame[offset + 4 : offset + 6])[0]
            src = frame[offset + 8 : offset + 24].hex()
            dst = frame[offset + 24 : offset + 40].hex()
            tcp_at = offset + 40
            ip_payload_len = payload_len
        else:
            continue

        if len(frame) < tcp_at + 20:
            continue
        src_port, dst_port = struct.unpack(">HH", frame[tcp_at : tcp_at + 4])
        if port not in (src_port, dst_port):
            continue
        data_offset = (frame[tcp_at + 12] >> 4) * 4
        flags = frame[tcp_at + 13]
        # Derive payload length from the IP header rather than the captured
        # frame length
        segments.append(
            Segment(
                timestamp=when,
                src_addr=src,
                src_port=src_port,
                dst_addr=dst,
                dst_port=dst_port,
                flags=flags,
                payload_len=max(0, ip_payload_len - data_offset),
            )
        )
    return segments


# Result


@dataclass
class Result:
    """Outcome of the D2 check.

    Attributes:
        status: PASS, FAIL or NO_DATA.
        summary: One-line explanation.
        observations: What the check found.
        metrics: Machine-readable measurements.
    """

    status: str = "NO_DATA"
    summary: str = ""
    observations: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def verify(path: Path, port: int) -> Result:
    """Checks a capture for an accepted TCP connection carrying data.

    Args:
        path: Capture file.
        port: TCP port the netcat listener is bound to.

    Returns:
        The verification result.
    """
    result = Result()
    result.metrics["capture"] = str(path)
    result.metrics["port"] = port

    try:
        link_type, frames = read_frames(path)
    except (OSError, ValueError) as exc:
        result.observations.append(str(exc))
        result.summary = "Capture could not be read."
        return result

    result.observations.append(
        f"Read {len(frames)} frame(s), link type {link_type}."
    )
    result.metrics["frames"] = len(frames)

    segments = tcp_segments(link_type, frames, port)
    if not segments:
        result.observations.append(
            f"No TCP segments involving port {port} were found."
        )
        result.observations.append(
            "Check the capture filter and the port. If the listener uses a "
            "different port, pass --port."
        )
        result.summary = f"Capture contains no TCP traffic on port {port}."
        return result

    result.metrics["segments"] = len(segments)

    # A SYN-ACK sourced from the listener port is the accept event.
    syn_acks = [s for s in segments if s.is_syn_ack and s.src_port == port]
    syns = [s for s in segments if s.is_syn_only and s.dst_port == port]
    inbound_bytes = sum(s.payload_len for s in segments if s.dst_port == port)
    outbound_bytes = sum(s.payload_len for s in segments if s.src_port == port)
    resets = [s for s in segments if s.flags & TCP_RST]

    clients = sorted({(s.src_addr, s.src_port) for s in syns})

    result.observations.append(
        f"{len(syns)} inbound SYN(s) to port {port}; "
        f"{len(syn_acks)} SYN-ACK(s) from it."
    )
    result.observations.append(
        f"{inbound_bytes} byte(s) delivered to the listener, "
        f"{outbound_bytes} byte(s) sent from it."
    )
    if clients:
        result.observations.append(
            f"{len(clients)} distinct client endpoint(s) connected."
        )
    if resets:
        result.observations.append(
            f"{len(resets)} RST segment(s) observed; reported for context."
        )

    result.metrics["syn_count"] = len(syns)
    result.metrics["syn_ack_count"] = len(syn_acks)
    result.metrics["inbound_bytes"] = inbound_bytes
    result.metrics["outbound_bytes"] = outbound_bytes
    result.metrics["client_endpoints"] = len(clients)
    result.metrics["resets"] = len(resets)

    if segments:
        span = (segments[-1].timestamp - segments[0].timestamp).total_seconds()
        result.metrics["span_seconds"] = round(span, 3)
        result.observations.append(f"Traffic spans {span:.1f} s.")

    # Verdict
    if syn_acks and inbound_bytes:
        result.status = "PASS"
        result.summary = (
            f"Listener on port {port} accepted {len(syn_acks)} TCP "
            f"connection(s) and received {inbound_bytes} byte(s)."
        )
    elif inbound_bytes:
        result.status = "PASS"
        result.summary = (
            f"{inbound_bytes} byte(s) were delivered to a listener on port "
            f"{port}. No handshake was captured"
        )
    elif syn_acks:
        result.status = "FAIL"
        result.summary = (
            f"A connection was accepted on port {port} but carried no data."
        )
    elif syns:
        result.status = "FAIL"
        result.summary = (
            f"{len(syns)} connection attempt(s) to port {port} were never "
            "accepted; nothing is listening."
        )
    else:
        result.summary = (
            f"Traffic on port {port} exists but shows neither a handshake nor "
            "any payload."
        )
    return result


def render(result: Result, verbose: bool) -> None:
    """Prints the result.

    Args:
        result: Verification result.
        verbose: Whether to print metrics as well as observations.
    """
    print()
    print("D2 - Netcat support")
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
        description="Verify D2: the DUT uses Netcat for NMEA data exchange.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Collect the capture on the DUT with:\n"
            "    tcpdump -i any -w d2_nmea.pcap tcp port 5000"
        ),
    )
    parser.add_argument("pcap", type=Path, help="tcpdump capture of the NMEA port.")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"TCP port the netcat listener is bound to (default: {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit the result as JSON instead."
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Also print metrics."
    )
    args = parser.parse_args(argv)

    if not args.pcap.is_file():
        print(f"Capture not found: {args.pcap}", file=sys.stderr)
        return 2

    result = verify(args.pcap, args.port)

    if args.json:
        print(
            json.dumps(
                {
                    "requirement": "D2",
                    "title": "Netcat support",
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
