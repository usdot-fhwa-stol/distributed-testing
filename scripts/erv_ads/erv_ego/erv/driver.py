"""Emergency vehicle driver for CARLA scenarios (Code 3 response).

Built on CARLA's BasicAgent with the behaviours an apparatus driver shows:
* runs above the speed limit (configurable factor, capped),
* proceeds through red lights and stop signs but slows to a clearing speed
  inside junctions,
* does not rely on BasicAgent's lane-based vehicle detection (which would
  stop behind a vehicle that has pulled to the edge of the same lane); it
  uses its own swept-corridor check and offsets left to pass a stopped or
  yielding vehicle when the opposing side is clear,
* keeps lightbar (CARLA Special1) and low beams on; siren is a flag carried
  into the BSM because CARLA does not simulate audio.
"""

from __future__ import annotations

import logging
import math

import carla

from .. import carla_compat as cc

log = logging.getLogger(__name__)


class ErvDriver:
    def __init__(self, actor, world, carla_map, grp, cfg: dict):
        BasicAgent, _ = cc.import_agents()
        self.actor = actor
        self.world = world
        self.map = carla_map
        self.grp = grp
        self.cfg = cfg
        self.speed_factor = float(cfg.get("speed_factor", 1.3))
        self.max_kmh = float(cfg.get("max_kmh", 75.0))
        self.junction_kmh = float(cfg.get("junction_kmh", 30.0))
        self.max_pass_offset = float(cfg.get("max_pass_offset_m", 3.8))
        self.code3 = bool(cfg.get("code3", True))
        self.stationary = bool(cfg.get("stationary", False))
        self.agent = BasicAgent(actor, target_speed=self.max_kmh, opt_dict={
            "ignore_traffic_lights": True,
            "ignore_stop_signs": True,
            "ignore_vehicles": True,
            "max_brake": 1.0,
        }, map_inst=carla_map, grp_inst=grp)
        try:
            self.agent.follow_speed_limits(False)
        except AttributeError:
            pass
        self._offset = 0.0
        self._passing = None                 # actor id of the vehicle we are pulling out to pass
        self._seen = {}
        self._my_lat = 0.0
        bb = actor.bounding_box
        self.half_w = bb.extent.y
        self.half_l = bb.extent.x
        self.set_code3(self.code3)

    # ------------------------------------------------------------------------
    def set_code3(self, on: bool) -> None:
        self.code3 = on
        lights = {"position", "low_beam"}
        if on:
            lights.add("lightbar")
        if self.stationary:
            lights.add("hazard")
        cc.set_lights(self.actor, lights)

    @property
    def siren_on(self) -> bool:
        return self.code3 and not self.stationary

    def set_destination(self, loc: carla.Location, via: carla.Location = None) -> None:
        """Route to ``loc``. With ``via`` the route is forced through that point
        first (the shortest path to the destination need not pass the ego)."""
        if via is None:
            self.agent.set_destination(loc)
            return
        start = self.map.get_waypoint(self.actor.get_location()).transform.location
        mid = self.map.get_waypoint(via).transform.location
        try:
            plan = list(self.grp.trace_route(start, mid))
            tail = list(self.grp.trace_route(mid, loc))
            plan += tail[1:] if plan else tail
        except Exception as exc:                 # e.g. networkx.NetworkXNoPath on a broken road graph
            log.warning("ERV via-route not found (%s); falling back to the direct route", exc)
            plan = []
        if len(plan) < 2:
            self.agent.set_destination(loc)
            return
        self.agent.set_global_plan(plan, stop_waypoint_creation=True, clean_queue=True)

    def done(self) -> bool:
        return self.agent.done()

    # ------------------------------------------------------------------------
    def _target_speed_kmh(self, wp) -> float:
        limit = self.actor.get_speed_limit() or 50.0
        v = min(limit * self.speed_factor, self.max_kmh)
        if wp is not None and wp.is_junction:
            v = min(v, self.junction_kmh)
        return min(v, self._curve_speed_kmh())

    def _curve_speed_kmh(self, lat_accel: float = 2.2, horizon_m: float = 22.0) -> float:
        """Speed the route ahead can be driven at: an apparatus that takes a tight junction turn at its
        junction speed runs wide, and on a roads-only world running wide means leaving the ground."""
        try:
            plan = [w for w, _ in list(self.agent.get_local_planner().get_plan())[:40]]
        except Exception:
            return 1e9
        if len(plan) < 3:
            return 1e9
        tightest, d = 1e9, 0.0
        for a, b in zip(plan, plan[1:]):
            seg = a.transform.location.distance(b.transform.location)
            if seg < 0.5:
                continue
            d += seg
            if d > horizon_m:
                break
            turn = abs((b.transform.rotation.yaw - a.transform.rotation.yaw + 180.0) % 360.0 - 180.0)
            if turn > 0.5:
                tightest = min(tightest, seg / math.radians(turn))          # radius of this piece
        if tightest > 500.0:
            return 1e9
        return max(3.6 * math.sqrt(lat_accel * tightest), 10.0)

    def _corridor(self, speed: float):
        """Return (blocking vehicle or None, oncoming_clear).

        Works in the lane's frame at our position. A blocker is
        (distance to its nearest point, its left edge from our lane centre, its
        speed, actor id, distance to its farthest point). Every vehicle near us
        is also remembered in ``self._seen`` so a pass can be held until the
        passed vehicle is behind.
        """
        tf = self.actor.get_transform()
        loc = tf.location
        # Reference lane = the route lane we are following, not the nearest lane: once we
        # have pulled out to pass, the nearest lane is the opposing one and its frame is reversed.
        lane_wp = None
        try:
            lane_wp = self.agent.get_local_planner().target_waypoint
        except AttributeError:
            pass
        if lane_wp is None:
            lane_wp = self.map.get_waypoint(loc)
        ltf = lane_wp.transform if lane_wp else tf
        fwd, right, lane_c = ltf.get_forward_vector(), ltf.get_right_vector(), ltf.location
        self._my_lat = (loc.x - lane_c.x) * right.x + (loc.y - lane_c.y) * right.y
        lookahead = 10.0 + speed * 3.0
        blocker = None
        oncoming_clear = True
        self._seen = {}
        for other in self.world.get_actors().filter("vehicle.*"):
            if other.id == self.actor.id:
                continue
            ol = other.get_location()
            dx, dy = ol.x - loc.x, ol.y - loc.y
            along = dx * fwd.x + dy * fwd.y
            if along < -15.0 or along > lookahead + 40.0:
                continue
            # the other vehicle's footprint: a car stopped at an angle sticks out
            # further than its centre and half-width suggest
            otf = other.get_transform()
            of, orr, ext = otf.get_forward_vector(), otf.get_right_vector(), other.bounding_box.extent
            lats, alongs = [], []
            for sx in (-1.0, 1.0):
                for sy in (-1.0, 1.0):
                    cx = ol.x + sx * ext.x * of.x + sy * ext.y * orr.x
                    cy = ol.y + sx * ext.x * of.y + sy * ext.y * orr.y
                    lats.append((cx - lane_c.x) * right.x + (cy - lane_c.y) * right.y)
                    alongs.append((cx - loc.x) * fwd.x + (cy - loc.y) * fwd.y)
            if max(alongs) < -(self.half_l + 3.0):
                continue                                # well behind us
            near = max(min(alongs), 0.0)
            ov = other.get_velocity()
            o_speed = math.hypot(ov.x, ov.y)
            heading_dot = (ov.x * fwd.x + ov.y * fwd.y) / max(o_speed, 1e-3)
            lat_c = (ol.x - lane_c.x) * right.x + (ol.y - lane_c.y) * right.y
            # oncoming traffic in the lane to our left, which we would borrow
            if o_speed > 0.5 and heading_dot < -0.5 and -5.5 < lat_c < -1.0 and along > 0.0:
                oncoming_clear = False
            bf = tf.get_forward_vector()
            body_far = max((ol.x + sx * ext.x * of.x + sy * ext.y * orr.x - loc.x) * bf.x
                           + (ol.y + sx * ext.x * of.y + sy * ext.y * orr.y - loc.y) * bf.y
                           for sx in (-1.0, 1.0) for sy in (-1.0, 1.0))
            info = (near, min(lats), o_speed, other.id, max(alongs), body_far)
            self._seen[other.id] = info
            if near > lookahead or max(alongs) < self.half_l:
                continue                                # too far, or already alongside
            # our path sweeps from where we are to where the planner is steering us
            # (route lane + offset): during a lane change those are a lane apart
            lo = min(self._my_lat, self._offset) - self.half_w - 0.4
            hi = max(self._my_lat, self._offset) + self.half_w + 0.4
            if min(lats) < hi and max(lats) > lo:
                if blocker is None or near < blocker[0]:
                    blocker = info
        return blocker, oncoming_clear

    def stop(self) -> None:
        """Arrive on scene: brake to a halt, then stand with hazards (and lightbar if still Code 3)."""
        self._stopping = True

    def go(self) -> None:
        """Leave the scene and carry on along the route."""
        self._stopping = False
        if self.stationary:
            self.stationary = False
            self.set_code3(self.code3)

    def run_step(self) -> carla.VehicleControl:
        if getattr(self, "_stopping", False) and not self.stationary:
            v = self.actor.get_velocity()
            if math.hypot(v.x, v.y) > 0.4:
                return carla.VehicleControl(throttle=0.0, brake=0.45)
            self.stationary = True
            self.set_code3(self.code3)
        if self.stationary:
            return carla.VehicleControl(throttle=0.0, brake=1.0, hand_brake=True)

        v = self.actor.get_velocity()
        speed = math.hypot(v.x, v.y)
        wp = self.map.get_waypoint(self.actor.get_location())
        target_kmh = self._target_speed_kmh(wp)

        blocker, oncoming_clear = self._corridor(speed)
        # Once we have pulled out to pass a vehicle it no longer overlaps our path, so
        # keep the pass latched until that vehicle is behind us (otherwise we swing back
        # in front of it and never get far enough over).
        latched = False
        if blocker is None and self._passing is not None:
            info = self._seen.get(self._passing)
            # hold the offset only while some part of it is still ahead of our own tail
            if info is not None and info[5] > -(self.half_l + 1.0) and info[2] < 3.0:
                blocker, latched = info, True
            else:
                self._passing = None
        desired_offset = 0.0
        brake_for = None
        if blocker is not None:
            along, left_edge, o_speed, oid = blocker[:4]
            if latched:
                # already past its nose and out of its way: hold the offset until it is behind us.
                # Its footprint in a turning lane frame is meaningless, so never brake for it here.
                desired_offset = self._offset
            elif o_speed < 3.0 or o_speed < 0.5 * speed:
                # vehicle is stopped/yielding: pass it on the left if there is room
                need = left_edge - (self.half_w + 1.0)       # negative -> left of lane centre
                if need < 0 and abs(need) <= self.max_pass_offset and oncoming_clear:
                    desired_offset = need
                    self._passing = oid
                    # not over far enough yet and nearly there: creep (moving sideways needs
                    # forward motion, so never stop dead here)
                    if self._my_lat - need > 0.5 and 0.0 < along < self.half_l + 5.0 + speed * 1.2:
                        target_kmh = min(target_kmh, 7.0)
                        if along < self.half_l + 1.0:
                            brake_for = along
                else:
                    brake_for = along
            else:
                brake_for = along

        # smooth the offset so the swerve looks like a driver, not a step
        self._offset += max(-0.15, min(0.15, desired_offset - self._offset))
        cc.set_planner_offset(self.agent, self._offset)
        self.agent.set_target_speed(target_kmh)

        control = self.agent.run_step()
        if brake_for is not None:
            gap = max(brake_for - self.half_l - 3.0, 0.5)
            decel = speed * speed / (2 * gap)
            if decel > 1.0 or gap < 3.0:
                control.throttle = 0.0
                control.brake = max(control.brake, min(1.0, decel / 8.0 + (0.5 if gap < 3.0 else 0.0)))
        return control
