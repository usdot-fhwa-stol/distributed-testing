"""Concise path history in the style of SAE J2945/1.

A breadcrumb is committed when the straight chord from the last committed
crumb to the current position would misrepresent the travelled path by more
than ``allowable_error_m`` (1 m in J2945/1), or when the chord would exceed
``max_segment_m``. History is trimmed to ``max_distance_m`` of travel and
``max_points`` crumbs. Output offsets are relative to the current position,
most recent first, as PathHistoryPoint expects.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Deque, List, Optional, Tuple

from ..j2735.bsm import PathHistoryPoint

Pt = Tuple[float, float, float, float]  # t, x, y, z (CARLA metres)


def _perp_dist(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 < 1e-9:
        return math.hypot(px - ax, py - ay)
    u = ((px - ax) * dx + (py - ay) * dy) / seg2
    u = max(0.0, min(1.0, u))
    return math.hypot(px - (ax + u * dx), py - (ay + u * dy))


class PathHistoryBuilder:
    def __init__(self, allowable_error_m: float = 1.0, max_segment_m: float = 210.0,
                 max_distance_m: float = 300.0, max_points: int = 15, min_step_m: float = 0.5):
        self.err = allowable_error_m
        self.max_seg = max_segment_m
        self.max_dist = max_distance_m
        self.max_points = max_points
        self.min_step = min_step_m
        self._crumbs: Deque[Pt] = deque()      # oldest .. newest committed
        self._raw: List[Pt] = []               # samples since last crumb

    def reset(self) -> None:
        self._crumbs.clear()
        self._raw.clear()

    def update(self, t: float, x: float, y: float, z: float) -> None:
        p = (t, x, y, z)
        if not self._crumbs:
            self._crumbs.append(p)
            return
        last_raw = self._raw[-1] if self._raw else self._crumbs[-1]
        if math.hypot(x - last_raw[1], y - last_raw[2]) < self.min_step:
            return
        self._raw.append(p)
        anchor = self._crumbs[-1]
        chord = math.hypot(x - anchor[1], y - anchor[2])
        worst = 0.0
        for q in self._raw[:-1]:
            worst = max(worst, _perp_dist(q[1], q[2], anchor[1], anchor[2], x, y))
        if (worst > self.err or chord > self.max_seg) and len(self._raw) >= 2:
            self._crumbs.append(self._raw[-2])
            self._raw = [self._raw[-1]]
        self._trim(x, y)

    def _trim(self, cx: float, cy: float) -> None:
        while len(self._crumbs) > self.max_points:
            self._crumbs.popleft()
        # distance travelled from current position back through the crumbs
        total = 0.0
        px, py = cx, cy
        keep = 0
        for c in reversed(self._crumbs):
            total += math.hypot(px - c[1], py - c[2])
            if total > self.max_dist:
                break
            keep += 1
            px, py = c[1], c[2]
        while len(self._crumbs) > max(keep, 1):
            self._crumbs.popleft()

    def crumbs_local(self) -> List[Pt]:
        """Committed crumbs newest-first (CARLA coordinates)."""
        return list(reversed(self._crumbs))

    def points(self, now_t: float, cur_lat: float, cur_lon: float, cur_elev: Optional[float],
               georef) -> List[PathHistoryPoint]:
        out: List[PathHistoryPoint] = []
        for (t, x, y, z) in self.crumbs_local():
            dt = now_t - t
            if dt <= 0:
                continue
            lat, lon, alt = georef.to_geo(x, y, z)
            out.append(PathHistoryPoint(
                lat_offset_deg=lat - cur_lat,
                lon_offset_deg=lon - cur_lon,
                elev_offset_m=None if cur_elev is None else alt - cur_elev,
                time_offset_s=dt,
            ))
        return out
