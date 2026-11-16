"""Inbound V2X pipeline: transport -> decode -> (simulated) radio -> delivery.

The channel model runs here, at the receiver, because only the receiver
knows both ends of the link (its own antenna position and the transmitter
position carried in the BSM). That keeps it valid whether the bytes arrived
over the in-process bus or over UDP from another process. Disable it for
messages that already crossed real RF (OBU forwarding).
"""

from __future__ import annotations

import heapq
import itertools
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..geo import CarlaGeoRef
from ..j2735.bsm import Bsm
from ..j2735.codec import Codec
from ..v2x.channel import Pc5Channel

log = logging.getLogger(__name__)


@dataclass
class RxMessage:
    bsm: Bsm
    rx_t: float                 # simulation (or wall) seconds at delivery
    source: str
    codec: str
    tx_xyz: Tuple[float, float, float]
    channel: Dict[str, Any] = field(default_factory=dict)
    size_bytes: int = 0
    tx_yaw_deg: Optional[float] = None   # CARLA yaw from the BSM heading (projection-aware)


class V2xReceiver:
    def __init__(self, endpoints: List[Any], codec: Codec, georef: CarlaGeoRef,
                 channel: Optional[Pc5Channel] = None, evidence=None):
        self.endpoints = endpoints
        self.codec = codec
        self.georef = georef
        self.channel = channel
        self.evidence = evidence
        self._pending: List[Tuple[float, int, RxMessage]] = []
        self._seq = itertools.count()
        self.stats = {"payloads": 0, "undecodable": 0, "non_bsm": 0, "no_position": 0,
                      "dropped_channel": 0, "delivered": 0}

    def poll(self, t_now: float, rx_xyz: Tuple[float, float, float]) -> List[RxMessage]:
        for ep in self.endpoints:
            for payload, source in ep.poll():
                self.stats["payloads"] += 1
                msg = self.codec.decode(payload)
                if msg is None:
                    self.stats["undecodable"] += 1
                    if self.evidence:
                        self.evidence.event("rx_undecodable", t_now, source=source, size=len(payload),
                                            head=payload[:16].hex())
                    continue
                if msg.bsm is None:
                    self.stats["non_bsm"] += 1
                    continue
                c = msg.bsm.core
                if c.lat_deg is None or c.lon_deg is None:
                    self.stats["no_position"] += 1
                    continue
                tx = self.georef.to_local(c.lat_deg, c.lon_deg, c.elev_m)
                delivered, latency, info = (True, 0.0, {})
                if self.channel is not None:
                    delivered, latency, info = self.channel.sample(tx, rx_xyz)
                if not delivered:
                    self.stats["dropped_channel"] += 1
                    if self.evidence:
                        self.evidence.event("rx_drop", t_now, id=c.temp_id.hex(), msgCnt=c.msg_cnt, **info)
                    continue
                yaw = None if c.heading_deg is None else self.georef.heading_to_yaw(c.heading_deg)
                rx = RxMessage(msg.bsm, t_now + latency, source, msg.codec, tx, info, len(payload), yaw)
                heapq.heappush(self._pending, (rx.rx_t, next(self._seq), rx))

        out: List[RxMessage] = []
        while self._pending and self._pending[0][0] <= t_now + 1e-9:
            out.append(heapq.heappop(self._pending)[2])
        self.stats["delivered"] += len(out)
        return out
