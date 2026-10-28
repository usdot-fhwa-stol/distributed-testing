"""Byte transports. They move encoded MessageFrames and nothing else; the
channel model and decoding live in the receiving pipeline.

* InProcessBus: deterministic, single-process runs (scenario runner).
* UdpSender / UdpReceiver: multi-process and real-hardware paths, e.g.
    - ERV broadcaster process -> ego node process in a shared cohort scene
    - Ettifos / Commsignia OBU "forward received messages to UDP" -> ego
    - V2X Hub / CDASim / a TENA gateway that emits UPER MessageFrames
"""

from __future__ import annotations

import socket
import struct
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple


class InProcessBus:
    """Broadcast medium: every subscriber except the sender gets each payload."""

    def __init__(self):
        self._subs: Dict[str, Deque[Tuple[bytes, str]]] = {}

    def subscribe(self, node_id: str) -> "InProcessEndpoint":
        self._subs.setdefault(node_id, deque())
        return InProcessEndpoint(self, node_id)

    def _publish(self, sender: str, payload: bytes) -> None:
        for node_id, q in self._subs.items():
            if node_id != sender:
                q.append((payload, sender))

    def _drain(self, node_id: str) -> List[Tuple[bytes, str]]:
        q = self._subs[node_id]
        out = list(q)
        q.clear()
        return out


class InProcessEndpoint:
    def __init__(self, bus: InProcessBus, node_id: str):
        self.bus = bus
        self.node_id = node_id

    def send(self, payload: bytes) -> None:
        self.bus._publish(self.node_id, payload)

    def poll(self) -> List[Tuple[bytes, str]]:
        return self.bus._drain(self.node_id)

    def close(self) -> None:
        pass


class UdpSender:
    def __init__(self, host: str, port: int, broadcast: bool = False, multicast_ttl: int = 1):
        self.addr = (host, int(port))
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if broadcast:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        first_octet = int(host.split(".")[0]) if host[0].isdigit() else 0
        if 224 <= first_octet <= 239:
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, multicast_ttl)

    def send(self, payload: bytes) -> None:
        self.sock.sendto(payload, self.addr)

    def poll(self) -> List[Tuple[bytes, str]]:
        return []

    def close(self) -> None:
        self.sock.close()


class UdpReceiver:
    def __init__(self, bind_host: str, port: int, multicast_group: Optional[str] = None,
                 bufsize: int = 8192):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        self.sock.bind((bind_host, int(port)))
        if multicast_group:
            mreq = struct.pack("4s4s", socket.inet_aton(multicast_group), socket.inet_aton("0.0.0.0"))
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self.sock.setblocking(False)
        self.bufsize = bufsize

    def send(self, payload: bytes) -> None:
        raise RuntimeError("UdpReceiver is receive-only")

    def poll(self) -> List[Tuple[bytes, str]]:
        out = []
        while True:
            try:
                data, addr = self.sock.recvfrom(self.bufsize)
            except (BlockingIOError, InterruptedError):
                break
            out.append((data, f"{addr[0]}:{addr[1]}"))
        return out

    def close(self) -> None:
        self.sock.close()
