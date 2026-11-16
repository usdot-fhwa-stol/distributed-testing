"""Scenario geometry on any CARLA map (Town10HD, Mine, or your own RFS /
San Ramon / GoMentum builds). Each builder returns a ScenarioSetup with ego
and ERV spawn transforms and destinations derived from the road network, so
nothing is hard-coded to one town.

Distances are walked along the lane taking the straightest branch at every
junction, and are shortened to what the map offers (small maps such as
Town10HD have ~100 m blocks; a digital twin of a campus has less). The ERV is
routed *through the ego's start position*, so it follows the ego instead of
taking the shortest path to its own destination.

Any pose can be pinned from the config, which is how a site-specific staging
(surveyed start positions on a digital twin) is expressed:

    scenario:
      ego_spawn: [x, y, z, yaw]     # CARLA world frame
      erv_spawn: [x, y, z, yaw]
      ego_dest:  [x, y, z]
      erv_dest:  [x, y, z]
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import List, Optional

import carla

from . import carla_compat as cc

log = logging.getLogger(__name__)


@dataclass
class ScenarioSetup:
    name: str
    ego_tf: carla.Transform
    ego_dest: carla.Location
    erv_tf: carla.Transform
    erv_dest: Optional[carla.Location]
    erv_stationary: bool = False
    erv_start_delay_s: float = 0.0
    note: str = ""
    erv_via: Optional[carla.Location] = None     # ERV route passes here (the ego's start) on its way to erv_dest


def _lift(tf: carla.Transform, dz: float = 0.6) -> carla.Transform:
    return carla.Transform(carla.Location(tf.location.x, tf.location.y, tf.location.z + dz), tf.rotation)


def _yaw_diff(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _advance(wp, dist: float, step: float = 2.0):
    return cc.walk_straight(wp, dist, True, step)[0]


def _dest(wp, dist: float, step: float = 4.0) -> carla.Location:
    """A destination up to ``dist`` metres down the road. On a small map the walk
    comes back round the block, so stop at the point farthest from the start."""
    start = wp.transform.location
    cur, d, best, best_r = wp, 0.0, wp, 0.0
    while d < dist:
        nxt, got = cc.walk_straight(cur, step, True, step)
        if got <= 0.0:
            break
        cur = nxt
        d += step
        r = cur.transform.location.distance(start)
        if r > best_r and not cur.is_junction:
            best, best_r = cur, r
        elif r < best_r - 40.0:
            break
    return best.transform.location


def _retreat(wp, dist: float, step: float = 2.0):
    return cc.walk_straight(wp, dist, False, step)[0]


def _run(wp, dist: float, forward: bool = True, step: float = 4.0, max_bend: float = 25.0):
    """Metres the lane continues (straight through junctions) before it bends
    more than ``max_bend`` from its starting direction or ends."""
    cur, d, yaw0 = wp, 0.0, wp.transform.rotation.yaw
    while d < dist:
        nxt, got = cc.walk_straight(cur, step, forward, step)
        if got <= 0.0 or _yaw_diff(nxt.transform.rotation.yaw, yaw0) > max_bend:
            break
        cur = nxt
        d += step
    return d


def _candidates(cmap, rng: random.Random) -> List:
    tfs = list(cmap.get_spawn_points())
    if not tfs:
        # generated / digital-twin maps often ship without spawn points
        tfs = [w.transform for w in cmap.generate_waypoints(15.0)]
    rng.shuffle(tfs)
    out = []
    for tf in tfs:
        wp = cmap.get_waypoint(tf.location)
        if wp is None or wp.is_junction or wp.lane_type != carla.LaneType.Driving:
            continue
        out.append(wp)
    return out


def _score(wp, prefer_multilane: bool, need_opposite: bool = False, need_junction: bool = False,
           behind_m: float = 0.0, ahead_m: float = 200.0):
    """Higher is better: straight road ahead (and behind, when the ERV starts
    there), a start that is not on top of a junction, optionally several lanes."""
    if need_opposite and not cc.is_undivided(wp):
        return -1e9
    if need_junction:
        d, _ = cc.distance_to_next_junction(wp, horizon_m=160.0)
        if d is None or d < 30.0:
            return -1e9
        return 200.0 - abs(d - 90.0)
    left, right = cc.count_same_dir_lanes(wp)
    score = min(_run(wp, ahead_m, True), ahead_m)
    if behind_m > 0.0:
        score += 1.5 * min(_run(wp, behind_m, False), behind_m)
    d_j, _ = cc.distance_to_next_junction(wp, horizon_m=40.0)
    if d_j is not None and d_j < 30.0:
        score -= 60.0                                # room to react before the first junction
    if prefer_multilane and (left + right) >= 1:
        score += 80.0
    return score


def _ranked(cmap, rng, n: int = 12, **kw) -> List:
    """The ``n`` best-scoring start waypoints, best first."""
    cands = _candidates(cmap, rng)
    if not cands:
        raise RuntimeError("map has no usable driving-lane waypoints")
    scored = sorted(((_score(w, **kw), i, w) for i, w in enumerate(cands)), key=lambda x: (-x[0], x[1]))
    return [w for s, _, w in scored[:n] if s > -1e8]


def _best(cmap, rng, **kw):
    ranked = _ranked(cmap, rng, 1, **kw)
    if not ranked:
        raise RuntimeError("no start position on this map satisfies the scenario's requirements")
    return ranked[0]


def approach_from_behind(cmap, sc: dict, rng: random.Random) -> ScenarioSetup:
    offset = float(sc.get("erv_offset_m", 140))
    # The ERV must be able to drive from its start to the ego: walking a lane backwards
    # does not guarantee that (digital-twin road graphs have one-way links), so check it
    # on the lane graph and shorten the offset / try the next start until it holds.
    ego_wp = erv_wp = None
    got = 0.0
    for wp in _ranked(cmap, rng, 12, prefer_multilane=sc.get("prefer_multilane", True),
                      behind_m=offset, ahead_m=200.0):
        # put the ego in the leftmost lane on multi-lane roads so the yield includes lane changes
        cand = cc.leftmost_same_dir(wp)
        for frac in (1.0, 0.7, 0.5, 0.35):
            back, d = cc.walk_straight(cand, offset * frac, forward=False)
            if d < 25.0:
                break
            rel = cc.road_relation(cmap, cand, cand.transform.location, back.transform.location,
                                   max_behind=d + 60.0, max_junctions=8)
            if rel is not None and rel[0] == "behind":
                ego_wp, erv_wp, got = cand, back, d
                break
        if ego_wp is not None:
            break
    if ego_wp is None:
        raise RuntimeError("no start with a drivable road behind it found for approach_from_behind")
    route = float(sc.get("ego_route_m", 450))
    dest = _dest(ego_wp, route)
    erv_dest = _dest(ego_wp, route + 60.0)
    return ScenarioSetup("approach_from_behind", _lift(ego_wp.transform), dest, _lift(erv_wp.transform), erv_dest,
                         erv_start_delay_s=float(sc.get("erv_start_delay_s", 6)),
                         note=f"ego road {ego_wp.road_id} lane {ego_wp.lane_id}; ERV {got:.0f} m behind "
                              f"on road {erv_wp.road_id}",
                         erv_via=ego_wp.transform.location)


def stationary_ahead(cmap, sc: dict, rng: random.Random) -> ScenarioSetup:
    want = float(sc.get("erv_offset_m", 140)) + 60.0
    wp = _best(cmap, rng, prefer_multilane=sc.get("prefer_multilane", True), ahead_m=want + 40.0)
    ego_wp = cc.rightmost_same_dir(wp)
    # keep the scene on the straight the ego starts on when the map is small
    room = _run(ego_wp, want + 40.0)
    dist = want if room >= want else max(room - 15.0, 40.0)
    ahead = _advance(ego_wp, dist)
    if ahead.is_junction:                            # never park the apparatus inside a junction
        ahead = _advance(ahead, 30.0)
    erv_wp = cc.rightmost_same_dir(ahead)
    # park the apparatus against the right edge of the lane (or on the shoulder)
    tf = erv_wp.transform
    right = tf.get_right_vector()
    shoulder = cc.shoulder_width_right(erv_wp)
    shift = (erv_wp.lane_width / 2.0 + shoulder / 2.0 - 0.3) if shoulder >= 2.5 else 0.6
    loc = carla.Location(tf.location.x + right.x * shift, tf.location.y + right.y * shift, tf.location.z)
    erv_tf = carla.Transform(loc, tf.rotation)
    dest = _dest(ego_wp, max(float(sc.get("ego_route_m", 450)), dist + 80.0))
    return ScenarioSetup("stationary_ahead", _lift(ego_wp.transform), dest, _lift(erv_tf), None,
                         erv_stationary=True,
                         note=f"ERV parked {dist:.0f} m ahead, {shift:.1f} m right of lane centre")


def oncoming(cmap, sc: dict, rng: random.Random) -> ScenarioSetup:
    want = float(sc.get("erv_offset_m", 140)) + 80.0
    wp = _best(cmap, rng, prefer_multilane=False, need_opposite=True, ahead_m=want + 40.0)
    ego_wp = cc.rightmost_same_dir(wp)
    opp, dist = None, want
    # walk back toward the ego until there is an opposing lane beside us (not in a junction)
    while dist >= 40.0:
        ahead = _advance(ego_wp, dist)
        cand = cc.leftmost_same_dir(ahead).get_left_lane()
        if not ahead.is_junction and cand is not None and cand.lane_type == carla.LaneType.Driving \
                and cand.lane_id * ahead.lane_id < 0:
            opp = cand
            break
        dist -= 10.0
    if opp is None:
        raise RuntimeError("no adjacent opposing lane found for oncoming scenario")
    erv_dest = _dest(opp, dist + 200.0)
    dest = _dest(ego_wp, max(float(sc.get("ego_route_m", 450)), dist + 80.0))
    return ScenarioSetup("oncoming", _lift(ego_wp.transform), dest, _lift(opp.transform), erv_dest,
                         erv_start_delay_s=float(sc.get("erv_start_delay_s", 6)) * 0.5,
                         note=f"ERV {dist:.0f} m ahead in the opposing lane",
                         erv_via=cc.leftmost_same_dir(ego_wp).get_left_lane().transform.location
                         if cc.is_undivided(ego_wp) else None)


def crossing(cmap, sc: dict, rng: random.Random) -> ScenarioSetup:
    best = None
    for ego_wp in _ranked(cmap, rng, 25, prefer_multilane=False, need_junction=True):
        d_j, jwp = cc.distance_to_next_junction(ego_wp, horizon_m=160.0)
        if jwp is None:
            continue
        junction = jwp.get_junction()
        if junction is None:
            continue
        ego_yaw = ego_wp.transform.rotation.yaw
        for start, end in junction.get_waypoints(carla.LaneType.Driving):
            dyaw = _yaw_diff(start.transform.rotation.yaw, ego_yaw)
            if 60.0 <= dyaw <= 120.0:
                exit_dyaw = _yaw_diff(end.transform.rotation.yaw, start.transform.rotation.yaw)
                if exit_dyaw < 20.0:                 # ERV goes straight across
                    best = (start, end)
                    break
        if best is not None:
            break
    if best is None:
        raise RuntimeError("no junction with a perpendicular through-movement found for crossing scenario")
    start, end = best
    # time the ERV so both would arrive at about the same moment
    ratio = (float(sc.get("erv_speed_ratio", 1.4)))
    erv_wp = _retreat(start, max(d_j * ratio, 40.0))
    erv_dest = _dest(end, 150.0)
    dest = _dest(ego_wp, d_j + 160.0)
    return ScenarioSetup("crossing", _lift(ego_wp.transform), dest, _lift(erv_wp.transform), erv_dest,
                         erv_start_delay_s=0.0, note=f"junction {junction.id} at {d_j:.0f} m",
                         erv_via=end.transform.location)


BUILDERS = {
    "approach_from_behind": approach_from_behind,
    "stationary_ahead": stationary_ahead,
    "oncoming": oncoming,
    "crossing": crossing,
}


def _pose(v) -> Optional[carla.Transform]:
    if not v:
        return None
    x, y, z, yaw = [float(a) for a in (v.split(",") if isinstance(v, str) else v)]
    return carla.Transform(carla.Location(x, y, z), carla.Rotation(yaw=yaw))


def _point(v) -> Optional[carla.Location]:
    if not v:
        return None
    x, y, z = [float(a) for a in (v.split(",") if isinstance(v, str) else v)][:3]
    return carla.Location(x, y, z)


def build(cmap, sc: dict) -> ScenarioSetup:
    rng = random.Random(sc.get("seed"))
    pinned = {k: sc.get(k) for k in ("ego_spawn", "erv_spawn", "ego_dest", "erv_dest") if sc.get(k)}
    name = sc["name"]
    if "ego_spawn" in pinned and "erv_spawn" in pinned and "ego_dest" in pinned:
        # fully staged: no need to search the map
        setup = ScenarioSetup(name, _pose(pinned["ego_spawn"]), _point(pinned["ego_dest"]),
                              _pose(pinned["erv_spawn"]), _point(pinned.get("erv_dest")),
                              erv_stationary=bool(sc.get("erv_stationary", name == "stationary_ahead")),
                              erv_start_delay_s=0.0 if name in ("stationary_ahead", "crossing")
                              else float(sc.get("erv_start_delay_s", 6)),
                              note=sc.get("note") or "staged from config")
        via = sc.get("erv_via")
        if via == "ego" or (via is None and name == "approach_from_behind"):
            setup.erv_via = setup.ego_tf.location
        elif via and via != "none":
            setup.erv_via = _point(via)
        if setup.erv_dest is None and not setup.erv_stationary:
            setup.erv_dest = setup.ego_dest
        return setup
    if name not in BUILDERS:
        raise ValueError(f"scenario '{name}' needs ego_spawn, erv_spawn and ego_dest in the config "
                         f"(built-in scenarios: {', '.join(BUILDERS)})")
    setup = BUILDERS[name](cmap, sc, rng)
    if "ego_spawn" in pinned:
        setup.ego_tf = _pose(pinned["ego_spawn"])
    if "erv_spawn" in pinned:
        setup.erv_tf = _pose(pinned["erv_spawn"])
    if "ego_dest" in pinned:
        setup.ego_dest = _point(pinned["ego_dest"])
    if "erv_dest" in pinned:
        setup.erv_dest = _point(pinned["erv_dest"])
    if pinned:
        setup.note += f" (pinned from config: {', '.join(sorted(pinned))})"
    return setup
