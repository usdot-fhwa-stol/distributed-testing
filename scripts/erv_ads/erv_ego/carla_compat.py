"""Everything that touches the CARLA Python API lives here or in the two
CARLA-facing classes (ego.agent.ErvAwareAgent, erv.driver.ErvDriver).

Written against the 0.10.x (UE5) API and defensive about the handful of
calls whose availability differs between 0.9.15 and 0.10.0.
"""

from __future__ import annotations

import fnmatch
import logging
import math
import os
import sys
from typing import Callable, FrozenSet, Iterable, Optional, Tuple

import carla

from .vehicle_state import VehicleState

log = logging.getLogger(__name__)

G = 9.80665


# ----------------------------------------------------------------------------
# CARLA PythonAPI agents (BasicAgent / LocalPlanner / GlobalRoutePlanner)
# ----------------------------------------------------------------------------

def import_agents():
    """Import CARLA's agents package from the installed PythonAPI.

    0.10 ships it under <CARLA_ROOT>/PythonAPI/carla/agents but does not
    install it with the wheel, so we add that folder to sys.path if needed.
    """
    try:
        import agents.navigation.basic_agent  # noqa: F401
    except ImportError:
        root = os.environ.get("CARLA_ROOT")
        if not root:
            raise ImportError("CARLA 'agents' package not importable. Set CARLA_ROOT to your "
                              "CARLA 0.10 install (folder containing PythonAPI/).")
        sys.path.insert(0, os.path.join(root, "PythonAPI", "carla"))
    from agents.navigation.basic_agent import BasicAgent
    from agents.navigation.global_route_planner import GlobalRoutePlanner
    return BasicAgent, GlobalRoutePlanner


def set_planner_offset(agent, offset_m: float) -> None:
    """Lateral offset from lane centre (+ = right) on BasicAgent's planner."""
    lp = getattr(agent, "_local_planner", None) or agent.get_local_planner()
    # BasicAgent builds its obstacle-check corridor from its own _offset, which
    # LocalPlanner.set_offset does not update: keep both in step so the agent looks
    # for vehicles where it is actually going to drive.
    if hasattr(agent, "_offset"):
        agent._offset = offset_m
    if hasattr(lp, "set_offset"):
        lp.set_offset(offset_m)
        return
    ctrl = getattr(lp, "_vehicle_controller", None)
    if ctrl is not None and hasattr(ctrl, "set_offset"):
        ctrl.set_offset(offset_m)
        return
    log.warning("This CARLA agents version has no lateral offset support; edge offset ignored")


# ----------------------------------------------------------------------------
# blueprints / actors
# ----------------------------------------------------------------------------

def find_blueprint(library, patterns: Iterable[str]):
    """First blueprint whose id matches any glob pattern (in order)."""
    bps = list(library.filter("vehicle.*"))
    for pat in patterns:
        for bp in bps:
            if fnmatch.fnmatch(bp.id, pat):
                return bp
    raise LookupError(f"No vehicle blueprint matches {list(patterns)}; available: {[b.id for b in bps]}")


ERV_BLUEPRINT_PATTERNS = {
    "firetruck": ["*firetruck*", "*fire*"],
    "engine": ["*firetruck*", "*fire*"],
    "ambulance": ["*ambulance*"],
    "police": ["*charger*police*", "*police*"],
    "responder": ["*police*", "*ambulance*"],
}


def find_actor_by_role(world, role_name: str):
    for a in world.get_actors().filter("vehicle.*"):
        if a.attributes.get("role_name") == role_name:
            return a
    return None


# ----------------------------------------------------------------------------
# lights
# ----------------------------------------------------------------------------

_LIGHT_NAMES = [
    ("Position", "position"), ("LowBeam", "low_beam"), ("HighBeam", "high_beam"),
    ("Brake", "brake"), ("RightBlinker", "right_blinker"), ("LeftBlinker", "left_blinker"),
    ("Reverse", "reverse"), ("Fog", "fog"), ("Special1", "lightbar"), ("Special2", "caution"),
]


def light_names(state) -> FrozenSet[str]:
    v = int(state)
    out = set()
    for attr, name in _LIGHT_NAMES:
        flag = getattr(carla.VehicleLightState, attr, None)
        if flag is not None and v & int(flag):
            out.add(name)
    if "left_blinker" in out and "right_blinker" in out:
        out.add("hazard")
    return frozenset(out)


def make_light_state(names: Iterable[str]):
    v = 0
    rev = {name: attr for attr, name in _LIGHT_NAMES}
    for n in names:
        if n == "hazard":
            v |= int(carla.VehicleLightState.LeftBlinker) | int(carla.VehicleLightState.RightBlinker)
            continue
        attr = rev.get(n)
        if attr and hasattr(carla.VehicleLightState, attr):
            v |= int(getattr(carla.VehicleLightState, attr))
    return carla.VehicleLightState(v)


def set_lights(actor, names: Iterable[str]) -> None:
    try:
        actor.set_light_state(make_light_state(names))
    except Exception as exc:  # lights unsupported on some meshes
        log.debug("set_light_state failed: %s", exc)


# ----------------------------------------------------------------------------
# state extraction
# ----------------------------------------------------------------------------

def _dot(a, b) -> float:
    return a.x * b.x + a.y * b.y + a.z * b.z


def max_road_wheel_deg(actor) -> float:
    try:
        pc = actor.get_physics_control()
        wheels = getattr(pc, "wheels", None)
        if wheels:
            return float(max(w.max_steer_angle for w in wheels)) or 70.0
    except Exception:
        pass
    return 70.0


def vehicle_state(actor, siren: bool = False, max_wheel_deg: Optional[float] = None) -> VehicleState:
    tf = actor.get_transform()
    vel = actor.get_velocity()
    acc = actor.get_acceleration()
    ang = actor.get_angular_velocity()
    fwd = tf.get_forward_vector()
    right = tf.get_right_vector()
    up = tf.get_up_vector()
    ctrl = actor.get_control()
    bb = actor.bounding_box
    try:
        lights = light_names(actor.get_light_state())
    except Exception:
        lights = frozenset()
    speed = math.sqrt(vel.x ** 2 + vel.y ** 2 + vel.z ** 2)
    return VehicleState(
        x=tf.location.x, y=tf.location.y, z=tf.location.z, yaw_deg=tf.rotation.yaw,
        speed_mps=speed,
        accel_long_mps2=_dot(acc, fwd), accel_lat_mps2=_dot(acc, right),
        accel_vert_g=_dot(acc, up) / G,
        yaw_rate_dps=ang.z,
        steer_norm=ctrl.steer, max_road_wheel_deg=max_wheel_deg or 70.0,
        brake=ctrl.brake, reverse=bool(ctrl.reverse), hand_brake=bool(ctrl.hand_brake),
        width_m=2 * bb.extent.y, length_m=2 * bb.extent.x, height_m=2 * bb.extent.z,
        lights=lights, siren=siren,
    )


# ----------------------------------------------------------------------------
# LOS raycast for the channel model
# ----------------------------------------------------------------------------

_BLOCKING = ("build", "wall", "vegetation", "terrain", "bridge", "fence", "rock", "static")


def make_raycast_los(world, antenna_height_m: float = 1.8) -> Callable:
    """Return los(tx_xyz, rx_xyz) -> bool using world.cast_ray.

    Vehicles do not block (C-V2X diffracts around them well enough at these
    ranges); buildings, terrain, vegetation, walls and bridges do.
    """
    if not hasattr(world, "cast_ray"):
        log.warning("world.cast_ray unavailable in this CARLA build; channel assumes LOS")
        return lambda tx, rx: True

    def los(tx, rx) -> bool:
        a = carla.Location(tx[0], tx[1], tx[2] + antenna_height_m)
        b = carla.Location(rx[0], rx[1], rx[2] + antenna_height_m)
        for lp in world.cast_ray(a, b):
            label = str(lp.label).lower()
            if any(k in label for k in _BLOCKING):
                return False
        return True

    return los


# ----------------------------------------------------------------------------
# misc
# ----------------------------------------------------------------------------

def server_version(client) -> str:
    try:
        return client.get_server_version()
    except Exception:
        return "unknown"


def ground_location(world_map, loc):
    wp = world_map.get_waypoint(loc, project_to_road=True)
    return wp.transform.location if wp else loc


def lane_index_from_right(wp) -> int:
    """0 = rightmost driving lane in this direction."""
    idx = 0
    cur = wp.get_right_lane()
    while cur is not None and cur.lane_type == carla.LaneType.Driving and (cur.lane_id * wp.lane_id) > 0:
        idx += 1
        cur = cur.get_right_lane()
    return idx


def count_same_dir_lanes(wp) -> Tuple[int, int]:
    """(driving lanes to the left, driving lanes to the right) in the same direction."""
    right = lane_index_from_right(wp)
    left = 0
    cur = wp.get_left_lane()
    while cur is not None and cur.lane_type == carla.LaneType.Driving and (cur.lane_id * wp.lane_id) > 0:
        left += 1
        cur = cur.get_left_lane()
    return left, right


def leftmost_same_dir(wp):
    cur = wp
    nxt = cur.get_left_lane()
    while nxt is not None and nxt.lane_type == carla.LaneType.Driving and (nxt.lane_id * wp.lane_id) > 0:
        cur = nxt
        nxt = cur.get_left_lane()
    return cur


def rightmost_same_dir(wp):
    cur = wp
    nxt = cur.get_right_lane()
    while nxt is not None and nxt.lane_type == carla.LaneType.Driving and (nxt.lane_id * wp.lane_id) > 0:
        cur = nxt
        nxt = cur.get_right_lane()
    return cur


def is_undivided(wp) -> bool:
    """True if an opposite-direction driving lane sits directly left of the
    leftmost same-direction lane (no median / separate carriageway).

    Junction lanes have no neighbours in OpenDRIVE, so inside a junction the
    answer is taken from the road that leads into it (digital twins flag long
    stretches with driveways as junctions)."""
    if wp.is_junction:
        for forward in (False, True):
            cur, d = wp, 0.0
            while cur.is_junction and d < 80.0:
                nxt, got = walk_straight(cur, 4.0, forward, 4.0)
                if got <= 0.0:
                    break
                cur, d = nxt, d + got
            if not cur.is_junction:
                wp = cur
                break
    left = leftmost_same_dir(wp).get_left_lane()
    return left is not None and left.lane_type == carla.LaneType.Driving and (left.lane_id * wp.lane_id) < 0


def shoulder_width_right(wp) -> float:
    r = rightmost_same_dir(wp).get_right_lane()
    if r is not None and r.lane_type in (carla.LaneType.Shoulder, carla.LaneType.Parking):
        return float(r.lane_width)
    return 0.0


def walk_straight(wp, dist: float, forward: bool = True, step: float = 2.0):
    """Follow the lane for ``dist`` metres, taking the straightest branch at
    every junction (``next()[0]`` is an arbitrary branch, often a turn).
    Returns (waypoint reached, distance actually covered)."""
    cur, d = wp, 0.0
    while d < dist:
        nxt = cur.next(step) if forward else cur.previous(step)
        if not nxt:
            break
        if len(nxt) > 1:
            # branches leave a junction entry tangent to each other, so compare
            # the heading each one has once it is through the junction
            yaw = cur.transform.rotation.yaw
            nxt.sort(key=lambda n: abs((_exit_yaw(n, forward) - yaw + 180.0) % 360.0 - 180.0))
        cur = nxt[0]
        d += step
    return cur, d


def _exit_yaw(wp, forward: bool = True, horizon_m: float = 60.0, step: float = 2.0) -> float:
    """Heading of the lane once it has left the junction ``wp`` is in."""
    cur, d = wp, 0.0
    while cur.is_junction and d < horizon_m:
        nxt = cur.next(step) if forward else cur.previous(step)
        if not nxt:
            break
        cur = nxt[0]
        d += step
    return cur.transform.rotation.yaw


def _fwd_proj(wp, loc) -> float:
    """Signed distance of ``loc`` ahead of waypoint ``wp`` along its lane direction."""
    f = wp.transform.get_forward_vector()
    o = wp.transform.location
    return (loc.x - o.x) * f.x + (loc.y - o.y) * f.y


def road_relation(world_map, ego_wp, ego_loc, erv_loc, plan=None, max_dist: float = 300.0,
                  max_behind: float = 250.0, max_junctions: int = 2, step: float = 4.0):
    """Where is the ERV relative to us *along the road network*?

    Returns ("ahead" | "oncoming" | "behind", path distance in metres) or None.
    Straight-line geometry cannot tell an ERV coming up behind us round a bend
    from one on another street; the lane graph can.

    * ahead / oncoming: the ERV sits on a road our own path (the planner's
      queue if given, else straight ahead) runs along within ``max_dist`` -
      in our direction, or in the opposing lanes.
    * behind: some forward path from the ERV's lane reaches our position within
      ``max_behind`` and at most ``max_junctions`` junctions (so an ERV that
      has already gone by is not found again by driving round the block).
    """
    if ego_wp is None:
        return None
    erv_wp = world_map.get_waypoint(erv_loc, project_to_road=True)
    if erv_wp is None or erv_wp.transform.location.distance(erv_loc) > 8.0:
        return None                                     # not on the road network
    lw = ego_wp.lane_width or 3.5
    reach = 3.0 * lw + 2.0                              # same road, any lane of either direction

    # 1. along our own path
    if plan:
        path = [w for w, _ in list(plan)[:200]]
    else:
        path, cur, d = [], ego_wp, 0.0
        while d < max_dist:
            cur, got = walk_straight(cur, step, True, step)
            if got <= 0.0:
                break
            path.append(cur)
            d += step
    best, d, prev = None, 0.0, ego_loc
    for w in path:
        loc = w.transform.location
        d += loc.distance(prev)
        prev = loc
        if d > max_dist:
            break
        if w.road_id != erv_wp.road_id:
            continue
        off = loc.distance(erv_loc)
        if off < reach and (best is None or off < best[0]):
            best = (off, d, w)
    if best is not None:
        _, d, w = best
        d += _fwd_proj(w, erv_loc)
        if d > 2.0:
            return ("ahead" if w.lane_id * erv_wp.lane_id > 0 else "oncoming", d)

    # 2. along the ERV's possible paths (breadth first)
    reach_same = 2.5 * lw + 2.0
    frontier = [(erv_wp, 0.0, 0)]
    seen = set()
    while frontier:
        nxt_frontier = []
        for w, d, nj in frontier:
            loc = w.transform.location
            if w.road_id == ego_wp.road_id and w.lane_id * ego_wp.lane_id > 0 \
                    and loc.distance(ego_loc) < reach_same:
                ahead = _fwd_proj(w, ego_loc)
                if ahead > -step:
                    total = d + max(ahead, 0.0)
                    return ("behind", total) if total > 2.0 else None
            if d >= max_behind:
                continue
            for n in w.next(step):
                nl = n.transform.location
                key = (n.road_id, n.lane_id, round(nl.x / 2.0), round(nl.y / 2.0))
                if key in seen:
                    continue
                seen.add(key)
                nj2 = nj + (1 if n.is_junction and not w.is_junction else 0)
                if nj2 > max_junctions:
                    continue
                nxt_frontier.append((n, d + step, nj2))
        frontier = nxt_frontier
    return None


def distance_to_next_junction(wp, horizon_m: float = 120.0, step_m: float = 2.0):
    """(distance, first junction waypoint) along the lane, or (None, None)."""
    if wp.is_junction:
        return 0.0, wp
    d = 0.0
    cur = wp
    while d < horizon_m:
        nxt = cur.next(step_m)
        if not nxt:
            return None, None
        cur = nxt[0]
        d += step_m
        if cur.is_junction:
            return d, cur
    return None, None
