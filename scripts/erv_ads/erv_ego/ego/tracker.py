"""Remote-vehicle track table built from received BSMs.

What a production OBU application has to cope with, and this handles:
* TemporaryID rotation: an unknown ID is re-associated to an existing track
  when its position matches that track's dead-reckoned position and heading
  (the generator resets msgCnt and path history on rotation, so those cannot
  be used).
* Freshness: messages whose secMark is older than ``max_age_ms`` (or from the
  future beyond clock tolerance) are rejected - stale/replayed data must not
  drive vehicle motion.
* Plausibility: position jumps implying impossible speed are rejected.
* Loss accounting from msgCnt gaps (per track), for the evidence log.
* Staleness: no update for ``stale_s`` marks a track stale; ``drop_s``
  removes it.
"""

from __future__ import annotations

import itertools
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

from ..clock import Clock, sec_mark_age_ms
from ..geo import angle_diff, heading_to_yaw
from ..j2735.bsm import Bsm
from .receiver import RxMessage


@dataclass
class ErvTrack:
    track_id: int
    temp_id: bytes
    bsm: Bsm
    first_rx_t: float
    last_rx_t: float
    x: float
    y: float
    z: float
    yaw_deg: float           # CARLA yaw derived from J2735 heading
    speed_mps: float
    msgs: int = 1
    lost: int = 0
    id_changes: int = 0
    last_age_ms: Optional[int] = None
    stale: bool = False
    first_active_t: Optional[float] = None
    trail: Deque[Tuple[float, float, float]] = field(default_factory=lambda: deque(maxlen=50))

    @property
    def active(self) -> bool:
        return self.bsm.is_active_erv

    @property
    def move_over_relevant(self) -> bool:
        return self.bsm.is_active_erv or (self.bsm.is_move_over_vehicle and self.bsm.caution_lights_on)

    @property
    def stationary(self) -> bool:
        return self.bsm.declared_stationary or self.speed_mps < 0.5

    @property
    def multi(self) -> bool:
        return self.bsm.multi_vehicle

    def predict(self, t: float) -> Tuple[float, float]:
        dt = max(t - self.last_rx_t, 0.0)
        yaw = math.radians(self.yaw_deg)
        return self.x + self.speed_mps * dt * math.cos(yaw), self.y + self.speed_mps * dt * math.sin(yaw)


class ErvTracker:
    def __init__(self, clock: Clock, max_age_ms: int = 1000, future_tolerance_ms: int = 200,
                 stale_s: float = 1.0, drop_s: float = 3.0, gate_m: float = 10.0,
                 gate_heading_deg: float = 30.0, max_speed_mps: float = 70.0, evidence=None):
        self.clock = clock
        self.max_age_ms = max_age_ms
        self.future_tol = future_tolerance_ms
        self.stale_s = stale_s
        self.drop_s = drop_s
        self.gate_m = gate_m
        self.gate_heading = gate_heading_deg
        self.max_speed = max_speed_mps
        self.evidence = evidence
        self.tracks: Dict[int, ErvTrack] = {}
        self._by_id: Dict[bytes, int] = {}
        self._ids = itertools.count(1)
        self.rejected: Dict[str, int] = {"stale": 0, "future": 0, "implausible": 0, "no_heading": 0}
        # temp IDs of our own transmissions (UDP loopback / broadcast echo)
        self.own_ids: set = set()

    # ------------------------------------------------------------------------
    def _associate(self, bsm: Bsm, x: float, y: float, yaw: float, t: float) -> Optional[int]:
        best, best_d = None, None
        for tid, tr in self.tracks.items():
            if tr.temp_id == bsm.core.temp_id:
                continue
            px, py = tr.predict(t)
            d = math.hypot(px - x, py - y)
            gate = self.gate_m + 0.5 * tr.speed_mps * max(t - tr.last_rx_t, 0.0)
            if d < gate and angle_diff(tr.yaw_deg, yaw) < self.gate_heading and (best_d is None or d < best_d):
                # an ID can only migrate if the old ID went quiet
                if t - tr.last_rx_t > 0.05:
                    best, best_d = tid, d
        return best

    def ingest(self, msg: RxMessage) -> Optional[ErvTrack]:
        bsm = msg.bsm
        c = bsm.core
        if c.temp_id in self.own_ids:
            return None
        if c.sec_mark_ms is not None:
            age = sec_mark_age_ms(self.clock.sec_mark(), c.sec_mark_ms)
            if age > self.max_age_ms:
                self.rejected["stale"] += 1
                self._ev("reject_stale", msg.rx_t, id=c.temp_id.hex(), age_ms=age)
                return None
            if age < -self.future_tol:
                self.rejected["future"] += 1
                self._ev("reject_future", msg.rx_t, id=c.temp_id.hex(), age_ms=age)
                return None
        else:
            age = None
        if c.heading_deg is None:
            self.rejected["no_heading"] += 1
            return None
        x, y, z = msg.tx_xyz
        yaw = msg.tx_yaw_deg if msg.tx_yaw_deg is not None else heading_to_yaw(c.heading_deg)
        speed = c.speed_mps or 0.0
        t = msg.rx_t

        tid = self._by_id.get(c.temp_id)
        if tid is None:
            tid = self._associate(bsm, x, y, yaw, t)
            if tid is not None:
                old = self.tracks[tid]
                self._by_id.pop(old.temp_id, None)
                old.temp_id = c.temp_id
                old.id_changes += 1
                self._by_id[c.temp_id] = tid
                self._ev("track_id_change", t, track=tid, new_id=c.temp_id.hex())

        if tid is None:
            tid = next(self._ids)
            tr = ErvTrack(tid, c.temp_id, bsm, t, t, x, y, z, yaw, speed, last_age_ms=age)
            tr.trail.append((t, x, y))
            if tr.active:
                tr.first_active_t = t
            self.tracks[tid] = tr
            self._by_id[c.temp_id] = tid
            self._ev("track_new", t, track=tid, **bsm.summary())
            return tr

        tr = self.tracks[tid]
        dt = t - tr.last_rx_t
        if dt > 1e-3:
            jump = math.hypot(x - tr.x, y - tr.y) / dt
            if jump > max(self.max_speed, 3 * max(speed, tr.speed_mps) + 10.0):
                self.rejected["implausible"] += 1
                self._ev("reject_implausible", t, track=tid, implied_mps=jump)
                return None
        if tr.temp_id == c.temp_id:
            gap = (c.msg_cnt - tr.bsm.core.msg_cnt) % 128
            if 1 < gap <= 20:
                tr.lost += gap - 1
        was_active = tr.active
        tr.bsm = bsm
        tr.last_rx_t = t
        tr.x, tr.y, tr.z, tr.yaw_deg, tr.speed_mps = x, y, z, yaw, speed
        tr.msgs += 1
        tr.last_age_ms = age
        tr.trail.append((t, x, y))
        if tr.stale:
            tr.stale = False
            self._ev("track_recovered", t, track=tid)
        if tr.active and tr.first_active_t is None:
            tr.first_active_t = t
        if was_active != tr.active:
            self._ev("track_active_change", t, track=tid, active=tr.active, **bsm.summary())
        return tr

    def update(self, t_now: float) -> None:
        for tid in list(self.tracks):
            tr = self.tracks[tid]
            idle = t_now - tr.last_rx_t
            if idle > self.drop_s:
                self._ev("track_drop", t_now, track=tid, msgs=tr.msgs, lost=tr.lost)
                self._by_id.pop(tr.temp_id, None)
                del self.tracks[tid]
            elif idle > self.stale_s and not tr.stale:
                tr.stale = True
                self._ev("track_stale", t_now, track=tid)

    def all(self) -> List[ErvTrack]:
        return list(self.tracks.values())

    def _ev(self, kind: str, t: float, **kw) -> None:
        if self.evidence:
            self.evidence.event(kind, t, **kw)
