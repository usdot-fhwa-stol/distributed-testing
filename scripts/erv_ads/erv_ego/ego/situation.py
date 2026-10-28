"""Where is each emergency vehicle relative to the ego, and how soon does it
matter?

Pure geometry plus road context the CARLA wrapper supplies (lane counts,
junction distance, whether the road is undivided, and - when the map can
resolve it - the ERV's lane relative to ours). No CARLA import, so the
classification is unit-tested directly.

Frames: CARLA world, x/y metres, yaw degrees (left-handed, z up). In the ego
frame ``along`` is + ahead and ``lateral`` is + to the right.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from ..geo import angle_diff
from .tracker import ErvTrack


class Relation(str, Enum):
    APPROACHING_FROM_BEHIND = "approaching_from_behind"
    ONCOMING = "oncoming"
    CROSSING = "crossing"
    STATIONARY_AHEAD = "stationary_ahead"
    AHEAD_SAME_DIR = "ahead_same_dir"     # ERV ahead going our way: do not overtake
    PASSED = "passed"                     # ERV has gone by / is moving away
    UNRELATED = "unrelated"


@dataclass
class EgoContext:
    x: float
    y: float
    yaw_deg: float
    speed_mps: float
    speed_limit_mps: float = 13.9
    lane_width_m: float = 3.5
    half_width_m: float = 1.0
    lanes_left: int = 0                 # same-direction driving lanes to the left
    lanes_right: int = 0                # same-direction driving lanes to the right
    shoulder_right_m: float = 0.0
    undivided: bool = True              # opposing traffic directly left of our leftmost lane
    in_junction: bool = False
    dist_to_junction_m: Optional[float] = None
    settled: bool = True                # parallel to the lane and at the right edge (pull-over finished)
    # Passing a stationary ERV: lateral offset from our lane centre (+ right, so negative = move left)
    # that clears it with margin, or None when there is no stationary ERV close to our path.
    pass_offset_m: Optional[float] = None
    opposing_clear: bool = True         # no traffic in the lane to our left over the length of the pass


@dataclass
class Threat:
    track_id: int
    relation: Relation
    range_m: float
    along_m: float
    lateral_m: float
    heading_diff_deg: float
    erv_speed_mps: float
    closing_mps: float
    time_to_reach_s: Optional[float]
    lane_offset: Optional[int]          # ERV lane minus ego lane (+ = ERV to our right)
    stationary: bool
    active: bool                        # siren and/or emergency lightbar
    move_over_relevant: bool            # active, or tow/DOT with caution lights
    multi: bool
    stale: bool
    erv_x: float = 0.0
    erv_y: float = 0.0


def _ray_intersection(px, py, pyaw, qx, qy, qyaw):
    """Distances along each ray to their intersection, or None if parallel."""
    dx1, dy1 = math.cos(math.radians(pyaw)), math.sin(math.radians(pyaw))
    dx2, dy2 = math.cos(math.radians(qyaw)), math.sin(math.radians(qyaw))
    den = dx1 * dy2 - dy1 * dx2
    if abs(den) < 1e-6:
        return None
    rx, ry = qx - px, qy - py
    t = (rx * dy2 - ry * dx2) / den
    u = (rx * dy1 - ry * dx1) / den
    return t, u


def assess(ego: EgoContext, tr: ErvTrack, lane_offset: Optional[int] = None,
           awareness_radius_m: float = 500.0, crossing_horizon_m: float = 250.0,
           road_hint: Optional[Tuple[str, float]] = None) -> Threat:
    """Classify one track. ``road_hint`` is the lane-graph relation the CARLA
    wrapper found - ("behind" | "ahead" | "oncoming", path distance) - and is
    used where straight-line geometry gives no answer (curved roads, ego stopped
    at an angle): it never overrides a definite geometric classification."""
    yaw = math.radians(ego.yaw_deg)
    fx, fy = math.cos(yaw), math.sin(yaw)
    rx, ry = -fy, fx                               # right vector in CARLA's frame
    dx, dy = tr.x - ego.x, tr.y - ego.y
    rng = math.hypot(dx, dy)
    along = dx * fx + dy * fy
    lateral = dx * rx + dy * ry
    hd = angle_diff(tr.yaw_deg, ego.yaw_deg)

    eyaw = math.radians(tr.yaw_deg)
    vx = tr.speed_mps * math.cos(eyaw) - ego.speed_mps * fx
    vy = tr.speed_mps * math.sin(eyaw) - ego.speed_mps * fy
    closing = -(vx * dx + vy * dy) / rng if rng > 1e-3 else 0.0

    # carriageway extent in the ego frame (+ right)
    lw = ego.lane_width_m
    right_edge = (ego.lanes_right + 0.5) * lw + max(ego.shoulder_right_m, 0.5) + 1.0
    left_edge = -(ego.lanes_left + 0.5) * lw - 1.0
    on_our_carriageway = left_edge <= lateral <= right_edge
    opposing_edge = left_edge - 3.5 * lw           # up to ~3 opposing lanes

    if lane_offset is None and hd < 45.0 and on_our_carriageway:
        lane_offset = int(round(lateral / lw))

    rel = Relation.UNRELATED
    ttr: Optional[float] = None
    stationary = tr.stationary

    if rng > awareness_radius_m:
        rel = Relation.UNRELATED
    elif stationary:
        if on_our_carriageway and along > -5.0:
            rel = Relation.STATIONARY_AHEAD
            ttr = max(along, 0.0) / max(ego.speed_mps, 0.1)
        elif on_our_carriageway:
            rel = Relation.PASSED
    elif hd < 45.0:
        if not on_our_carriageway:
            rel = Relation.UNRELATED
        elif along < 0:
            if closing > 0.5:
                rel = Relation.APPROACHING_FROM_BEHIND
                ttr = -along / max(closing, 0.1)
            else:
                rel = Relation.UNRELATED
        else:
            rel = Relation.AHEAD_SAME_DIR if closing > -0.5 else Relation.PASSED
    elif hd > 135.0:
        if along > 0 and closing > 0.5 and opposing_edge <= lateral <= right_edge:
            rel = Relation.ONCOMING
            ttr = along / max(closing, 0.1)
        elif along <= 0 and opposing_edge <= lateral <= right_edge:
            rel = Relation.PASSED
    else:
        hit = _ray_intersection(ego.x, ego.y, ego.yaw_deg, tr.x, tr.y, tr.yaw_deg)
        if hit is not None:
            t_ego, t_erv = hit
            if 0.0 < t_ego < crossing_horizon_m and 0.0 < t_erv < crossing_horizon_m:
                rel = Relation.CROSSING
                ttr = t_erv / max(tr.speed_mps, 0.5)
            elif t_erv <= 0.0 and t_ego > -10.0:
                rel = Relation.PASSED                   # ERV already beyond the conflict point

    weak = rel == Relation.UNRELATED or (rel == Relation.CROSSING and ego.dist_to_junction_m is None)
    if road_hint is not None and weak and rng <= awareness_radius_m:
        kind, dist = road_hint
        if kind == "behind" and not stationary:
            path_closing = tr.speed_mps - ego.speed_mps
            if path_closing > 0.5:
                rel, closing, along = Relation.APPROACHING_FROM_BEHIND, path_closing, -dist
                ttr = dist / path_closing
            else:
                rel, ttr = Relation.UNRELATED, None
        elif kind == "oncoming" and not stationary:
            path_closing = tr.speed_mps + ego.speed_mps
            if path_closing > 0.5:
                rel, closing, along = Relation.ONCOMING, path_closing, dist
                ttr = dist / path_closing
        elif kind == "ahead":
            along = dist
            if stationary:
                rel, ttr = Relation.STATIONARY_AHEAD, dist / max(ego.speed_mps, 0.1)
            else:
                closing = ego.speed_mps - tr.speed_mps
                rel, ttr = (Relation.AHEAD_SAME_DIR if closing > -0.5 else Relation.PASSED), None

    return Threat(
        track_id=tr.track_id, relation=rel, range_m=rng, along_m=along, lateral_m=lateral,
        heading_diff_deg=hd, erv_speed_mps=tr.speed_mps, closing_mps=closing, time_to_reach_s=ttr,
        lane_offset=lane_offset, stationary=stationary, active=tr.active,
        move_over_relevant=tr.move_over_relevant, multi=tr.multi, stale=tr.stale,
        erv_x=tr.x, erv_y=tr.y,
    )
