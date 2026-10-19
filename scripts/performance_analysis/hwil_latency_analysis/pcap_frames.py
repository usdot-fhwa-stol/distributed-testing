"""Read classic libpcap files and extract payloads and addresses from their frames."""

import argparse
import ipaddress
import struct
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

LINKTYPE_ETHERNET = 1
LINKTYPE_LINUX_SLL = 113

ETHERTYPE_IPV4 = 0x0800
ETHERTYPE_IPV6 = 0x86DD
ETHERTYPE_VLAN = 0x8100
ETHERTYPE_WSMP = 0x88DC

IPPROTO_UDP = 17
SLL_PACKET_OUTGOING = 4

# pcap magic -> (struct byte order, timestamp fraction divisor)
PCAP_MAGIC = {
    b"\xd4\xc3\xb2\xa1": ("<", 1e6),
    b"\xa1\xb2\xc3\xd4": (">", 1e6),
    b"\x4d\x3c\xb2\xa1": ("<", 1e9),
    b"\xa1\xb2\x3c\x4d": (">", 1e9),
}
PCAPNG_MAGIC = b"\x0a\x0d\x0d\x0a"

Address = str | ipaddress.IPv4Address | ipaddress.IPv6Address


@dataclass
class FrameInfo:
    """Payload and addressing of one captured frame.

    Attributes:
        payload: WSMP bytes (EtherType 0x88DC) or UDP payload; None for other frames.
        src: Source MAC (str) and/or IP addresses.
        dst: Destination MAC (str) and/or IP addresses.
        outgoing: Whether the capturing host sent the frame (Linux SLL only); None if unknown.
    """

    payload: bytes | None = None
    src: set[Address] = field(default_factory=set)
    dst: set[Address] = field(default_factory=set)
    outgoing: bool | None = None


def read_pcap(path: Path) -> Iterator[tuple[float, bytes, int]]:
    """Yield (timestamp in epoch seconds, frame bytes, linktype) for each record.

    Raises:
        ValueError: If the file is pcapng or not a pcap file.
    """
    data = path.read_bytes()
    magic = data[:4]
    if magic == PCAPNG_MAGIC:
        raise ValueError(f"{path} is pcapng; convert it with 'editcap -F pcap' first")
    if magic not in PCAP_MAGIC:
        raise ValueError(f"{path} is not a pcap file (magic {magic.hex()})")
    endian, divisor = PCAP_MAGIC[magic]
    linktype = struct.unpack(endian + "I", data[20:24])[0]

    offset = 24
    while offset + 16 <= len(data):
        ts_sec, ts_frac, cap_len, _ = struct.unpack(endian + "IIII", data[offset:offset + 16])
        offset += 16
        yield ts_sec + ts_frac / divisor, data[offset:offset + cap_len], linktype
        offset += cap_len


def _parse_ip(ethertype: int, l3: bytes, info: FrameInfo) -> None:
    """Add IP addresses to `info` and set its payload for UDP packets."""
    if ethertype == ETHERTYPE_IPV6 and len(l3) >= 48:
        info.src.add(ipaddress.IPv6Address(l3[8:24]))
        info.dst.add(ipaddress.IPv6Address(l3[24:40]))
        if l3[6] == IPPROTO_UDP:
            info.payload = l3[48:]
    elif ethertype == ETHERTYPE_IPV4 and len(l3) >= 20:
        info.src.add(ipaddress.IPv4Address(l3[12:16]))
        info.dst.add(ipaddress.IPv4Address(l3[16:20]))
        if l3[9] == IPPROTO_UDP:
            info.payload = l3[(l3[0] & 0x0F) * 4 + 8:]


def parse_frame(frame: bytes, linktype: int) -> FrameInfo:
    """Extract the payload and addresses of a Linux SLL or Ethernet frame."""
    info = FrameInfo()
    if linktype == LINKTYPE_LINUX_SLL and len(frame) >= 16:
        info.outgoing = struct.unpack(">H", frame[0:2])[0] == SLL_PACKET_OUTGOING
        ethertype = struct.unpack(">H", frame[14:16])[0]
        l3 = frame[16:]
    elif linktype == LINKTYPE_ETHERNET and len(frame) >= 14:
        info.dst.add(frame[0:6].hex(":"))
        info.src.add(frame[6:12].hex(":"))
        ethertype = struct.unpack(">H", frame[12:14])[0]
        l3 = frame[14:]
        if ethertype == ETHERTYPE_VLAN and len(l3) >= 4:
            ethertype = struct.unpack(">H", l3[2:4])[0]
            l3 = l3[4:]
    else:
        return info

    if ethertype == ETHERTYPE_WSMP:
        info.payload = l3
    else:
        _parse_ip(ethertype, l3, info)
    return info


def parse_address(text: str) -> Address:
    """Normalise an IPv4/IPv6 address or MAC address string for comparison with FrameInfo.

    Raises:
        argparse.ArgumentTypeError: If `text` is neither.
    """
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        pass
    octets = text.lower().replace("-", ":").split(":")
    if len(octets) != 6:
        raise argparse.ArgumentTypeError(f"not an IP or MAC address: {text}")
    try:
        return ":".join(f"{int(octet, 16):02x}" for octet in octets)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an IP or MAC address: {text}") from None
