"""Append-only run evidence.

events.jsonl  every receive/drop/reject, track lifecycle, mode transition,
              lane change attempt, collision - one JSON object per line
trace.csv     10 Hz kinematics of ego and each ERV plus the active action
metrics.json  summary computed at the end of the run (see Metrics)
config.json   the exact configuration used
"""

from __future__ import annotations

import csv
import json
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _clean(v: Any) -> Any:
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else round(v, 4)
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set, frozenset)):
        return [_clean(x) for x in v]
    if hasattr(v, "value") and not isinstance(v, (int, str)):
        return v.value
    return v


class Evidence:
    TRACE_FIELDS = ["t", "mode", "ego_x", "ego_y", "ego_yaw", "ego_speed", "ego_accel", "ego_lane",
                    "speed_cap", "lane_change", "stop", "erv_track", "erv_rel", "erv_range", "erv_along",
                    "erv_lateral", "erv_ttr", "erv_speed"]

    def __init__(self, out_dir: str, run_name: Optional[str] = None):
        name = run_name or time.strftime("%Y%m%d-%H%M%S")
        self.dir = os.path.join(out_dir, name)
        os.makedirs(self.dir, exist_ok=True)
        self._events = open(os.path.join(self.dir, "events.jsonl"), "w", buffering=1)
        self._trace_f = open(os.path.join(self.dir, "trace.csv"), "w", newline="")
        self._trace = csv.DictWriter(self._trace_f, fieldnames=self.TRACE_FIELDS)
        self._trace.writeheader()
        self.counts: Dict[str, int] = {}

    def event(self, kind: str, t: float, **kw) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1
        rec = {"t": round(t, 3), "kind": kind}
        rec.update(_clean(kw))
        self._events.write(json.dumps(rec) + "\n")

    def trace(self, row: Dict[str, Any]) -> None:
        self._trace.writerow({k: _clean(row.get(k)) for k in self.TRACE_FIELDS})

    def write_json(self, name: str, obj: Any) -> str:
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            json.dump(_clean(obj), f, indent=2)
        return path

    def close(self) -> None:
        self._events.close()
        self._trace_f.close()


@dataclass
class Metrics:
    """Yield/move-over performance measures, accumulated during the run."""
    first_active_rx_t: Optional[float] = None
    first_action_t: Optional[float] = None
    first_action_mode: Optional[str] = None
    range_at_first_action_m: Optional[float] = None
    stopped_t: Optional[float] = None
    resume_t: Optional[float] = None
    stopped_in_junction: bool = False
    min_range_m: Optional[float] = None
    min_lateral_clearance_m: Optional[float] = None
    max_decel_mps2: float = 0.0             # whole run, incl. red lights / obstacle braking
    max_decel_response_mps2: float = 0.0    # while responding to an ERV (yield / move-over modes)
    max_jerk_mps3: float = 0.0
    collisions: List[Dict[str, Any]] = field(default_factory=list)
    lane_changes: int = 0
    lane_change_aborts: int = 0
    modes_visited: List[str] = field(default_factory=list)
    _prev_accel: Optional[float] = None

    def on_accel(self, a_long: float, dt: float, responding: bool = True) -> None:
        if a_long < 0:
            self.max_decel_mps2 = max(self.max_decel_mps2, -a_long)
            if responding:
                self.max_decel_response_mps2 = max(self.max_decel_response_mps2, -a_long)
        if self._prev_accel is not None and dt > 0:
            self.max_jerk_mps3 = max(self.max_jerk_mps3, abs(a_long - self._prev_accel) / dt)
        self._prev_accel = a_long

    def on_erv_geometry(self, rng: float, lateral: float, along: float, half_lengths: float) -> None:
        self.min_range_m = rng if self.min_range_m is None else min(self.min_range_m, rng)
        if abs(along) < half_lengths:
            lat = abs(lateral)
            self.min_lateral_clearance_m = lat if self.min_lateral_clearance_m is None else \
                min(self.min_lateral_clearance_m, lat)

    def summary(self, criteria: Dict[str, float]) -> Dict[str, Any]:
        out = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        if self.first_active_rx_t is not None and self.first_action_t is not None:
            out["reaction_s"] = self.first_action_t - self.first_active_rx_t
        if self.stopped_t is not None and self.resume_t is not None:
            out["hold_s"] = self.resume_t - self.stopped_t
        checks = {
            "no_collision": not self.collisions,
        }
        if criteria.get("require_action", True):       # false for tests where doing nothing is the right answer
            checks["acted_on_erv"] = self.first_action_t is not None
        checks.update({
            "not_stopped_in_junction": not self.stopped_in_junction,
            "max_decel_ok": self.max_decel_response_mps2 <= criteria.get("max_decel_mps2", 6.0),
        })
        if criteria.get("min_range_at_action_m") and self.range_at_first_action_m is not None:
            checks["early_enough"] = self.range_at_first_action_m >= criteria["min_range_at_action_m"]
        out["checks"] = checks
        out["pass"] = all(checks.values())
        return out
