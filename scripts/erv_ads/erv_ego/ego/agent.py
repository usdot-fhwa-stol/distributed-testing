"""ErvAwareAgent: CARLA BasicAgent + V2X emergency-vehicle response.

Per tick:
  1. pull V2X payloads -> decode -> channel model -> deliver
  2. update the ERV track table
  3. build EgoContext from the map (lane counts, junction distance along the
     planned route, divided/undivided, shoulder) and assess each track
  4. policy -> Action
  5. execute: speed cap, gap-checked lane change, edge offset, controlled stop,
     blinkers; restore the route on resume
  6. optionally broadcast our own BSM (J2945/1-style, Part II-0)
  7. evidence: trace row at 10 Hz, metrics

The ego respects traffic lights and stop signs (BasicAgent's logic) and its
own vehicle detection, so it will still stop behind an ERV blocking its lane.
"""

from __future__ import annotations

import logging
import math
from typing import List, Optional, Tuple

import carla

from .. import carla_compat as cc
from ..evidence import Evidence, Metrics
from ..geo import CarlaGeoRef
from .policy import Action, ErvPolicy, Mode
from .receiver import V2xReceiver
from .situation import EgoContext, Threat, assess
from .tracker import ErvTracker

log = logging.getLogger(__name__)

YIELD_MODES = {Mode.CLEAR_JUNCTION, Mode.YIELD_CHANGE_LANE, Mode.PULL_OVER, Mode.STOP_BEFORE_JUNCTION,
               Mode.HOLD}
ACTION_MODES = YIELD_MODES | {Mode.MOVE_OVER, Mode.SLOW_PASS}
WP_LANE_TYPES = carla.LaneType.Driving | carla.LaneType.Shoulder | carla.LaneType.Parking


class ErvAwareAgent:
    def __init__(self, vehicle, world, carla_map, grp, receiver: V2xReceiver, tracker: ErvTracker,
                 policy: ErvPolicy, georef: CarlaGeoRef, cfg: dict,
                 evidence: Optional[Evidence] = None, metrics: Optional[Metrics] = None,
                 bsm_tx=None):
        BasicAgent, _ = cc.import_agents()
        from agents.navigation.local_planner import RoadOption
        self.RoadOption = RoadOption

        self.vehicle = vehicle
        self.world = world
        self.map = carla_map
        self.receiver = receiver
        self.tracker = tracker
        self.policy = policy
        self.georef = georef
        self.cfg = cfg
        self.evidence = evidence
        self.metrics = metrics or Metrics()
        self.bsm_tx = bsm_tx                         # (BsmGenerator, endpoint, codec) or None

        self.cruise_kmh = float(cfg.get("cruise_kmh", 40.0))
        self.respect_limits = bool(cfg.get("respect_speed_limits", True))
        self.comfort_decel = float(cfg.get("comfort_decel_mps2", 2.5))
        self.full_brake_decel = float(cfg.get("full_brake_decel_mps2", 8.0))
        self.edge_margin = float(cfg.get("edge_margin_m", 0.3))
        self.use_shoulder = bool(cfg.get("use_shoulder", True))
        self.settle_kmh = float(cfg.get("settle_kmh", 8.0))
        self.pass_clearance = float(cfg.get("pass_clearance_m", 1.0))
        self.trace_period = 1.0 / float(cfg.get("trace_hz", 10.0))
        self.bsm_period = 1.0 / float(cfg.get("bsm_rate_hz", 10.0))
        self.awareness = float(policy.cfg.awareness_radius_m)

        self.base = BasicAgent(vehicle, target_speed=self.cruise_kmh, opt_dict={
            "ignore_traffic_lights": False,
            "ignore_stop_signs": False,
            "max_brake": 0.9,
        }, map_inst=carla_map, grp_inst=grp)
        try:
            self.base.follow_speed_limits(False)
        except AttributeError:
            pass

        bb = vehicle.bounding_box
        self.half_w = bb.extent.y
        self.half_l = bb.extent.x
        self.destination: Optional[carla.Location] = None
        self._lc: Optional[dict] = None
        self._last_lc_end = -1e9
        self._offset = 0.0
        self._lights_cmd: Optional[frozenset] = None
        self._last_trace = -1e9
        self._last_bsm = -1e9
        self._last_t: Optional[float] = None
        self._route_suspended = False
        self.last_action: Optional[Action] = None
        self.last_threats: List[Threat] = []
        self._hints: dict = {}                       # track_id -> (t, road hint)
        self._speed_cmd_kmh: Optional[float] = None
        self._base_hazard = False
        self._prev_speed = 0.0
        self._still_pos: dict = {}                   # track_id -> (n, mean x, mean y) while it stands still
        self._pass_hold: dict = {}                   # track_id -> pass offset we have committed to
        self._hazard_until = -1e9

    # ------------------------------------------------------------------------
    def set_destination(self, loc: carla.Location) -> None:
        self.destination = loc
        self.base.set_destination(loc)

    def done(self) -> bool:
        return self.base.done() and self.last_action is not None and self.last_action.mode == Mode.CRUISE

    # ------------------------------------------------------------------------
    # road context
    # ------------------------------------------------------------------------
    def _junction_distance(self, ego_wp) -> Optional[float]:
        if ego_wp.is_junction:
            return 0.0
        try:
            plan = self.base.get_local_planner().get_plan()
        except Exception:
            plan = None
        if plan:
            d = 0.0
            prev = self.vehicle.get_location()
            for wp, _ in list(plan)[:80]:
                loc = wp.transform.location
                d += loc.distance(prev)
                prev = loc
                if wp.is_junction:
                    return d
                if d > 150.0:
                    return None
            return None
        d, _ = cc.distance_to_next_junction(ego_wp)
        return d

    def _ego_context(self) -> Tuple[EgoContext, object]:
        tf = self.vehicle.get_transform()
        v = self.vehicle.get_velocity()
        wp = self.map.get_waypoint(tf.location)
        left, right = cc.count_same_dir_lanes(wp)
        limit_kmh = self.vehicle.get_speed_limit() or 50.0
        ctx = EgoContext(
            x=tf.location.x, y=tf.location.y, yaw_deg=tf.rotation.yaw,
            speed_mps=math.hypot(v.x, v.y), speed_limit_mps=limit_kmh / 3.6,
            lane_width_m=wp.lane_width or 3.5, half_width_m=self.half_w,
            lanes_left=left, lanes_right=right, shoulder_right_m=cc.shoulder_width_right(wp),
            undivided=cc.is_undivided(wp), in_junction=wp.is_junction,
            dist_to_junction_m=self._junction_distance(wp),
        )
        # pull-over is finished when the car is parallel to the lane and at its right edge,
        # not merely when it has stopped (it may still be angled from the lane change)
        wtf = wp.transform
        r = wtf.get_right_vector()
        lat = (tf.location.x - wtf.location.x) * r.x + (tf.location.y - wtf.location.y) * r.y
        skew = abs((tf.rotation.yaw - wtf.rotation.yaw + 180.0) % 360.0 - 180.0)
        ctx.settled = self._lc is None and skew < 6.0 and lat >= self._edge_offset_target(ctx, True) - 0.4
        return ctx, wp

    def _lane_offset(self, ego_wp, x: float, y: float, z: float) -> Optional[int]:
        erv_wp = self.map.get_waypoint(carla.Location(x, y, z), project_to_road=True, lane_type=WP_LANE_TYPES)
        if erv_wp is None or ego_wp is None:
            return None
        if erv_wp.road_id == ego_wp.road_id and erv_wp.section_id == ego_wp.section_id \
                and erv_wp.lane_id * ego_wp.lane_id > 0:
            return abs(erv_wp.lane_id) - abs(ego_wp.lane_id)
        return None

    def _road_hint(self, t: float, ego_wp, ego_loc, tr):
        """Lane-graph relation of a track to us, refreshed at 5 Hz."""
        cached = self._hints.get(tr.track_id)
        if cached is not None and t - cached[0] < 0.2:
            return cached[1]
        try:
            plan = self.base.get_local_planner().get_plan()
        except Exception:
            plan = None
        try:
            hint = cc.road_relation(self.map, ego_wp, ego_loc, carla.Location(tr.x, tr.y, tr.z), plan=plan,
                                    max_dist=min(self.awareness, 300.0))
        except Exception as exc:                     # never let a map query stop the vehicle logic
            log.debug("road_relation failed: %s", exc)
            hint = None
        self._hints[tr.track_id] = (t, hint)
        return hint

    def _route_lane(self, ego_wp):
        """The lane we are following (planner target), which stays put while we drive offset from it."""
        try:
            wp = self.base.get_local_planner().target_waypoint
        except AttributeError:
            wp = None
        return wp or ego_wp

    def _pass_context(self, ego_wp, ego_loc):
        """(lateral offset that clears the nearest stationary ERV ahead, opposing lane clear?).

        The ERV's position and size come from its BSM; its left edge is taken a
        little wider for position error. Offsets are from our route lane's centre,
        + right, so a negative value means moving left. Other traffic is read from
        the world, like the lane-change gap check.
        """
        lane = self._route_lane(ego_wp).transform
        f, r, c = lane.get_forward_vector(), lane.get_right_vector(), lane.location
        lw = ego_wp.lane_width or 3.5
        try:
            plan = [w for w, _ in list(self.base.get_local_planner().get_plan())[:90]]
        except Exception:
            plan = []
        best = None
        for tr in self.tracker.all():
            if tr.stale or not tr.stationary or not tr.move_over_relevant:
                continue
            # A standing ERV's reported position wanders with its GNSS error (a metre from one second
            # to the next). It is not moving, so average it; steering by single samples pulls us
            # toward it whenever a sample lands on the far side.
            n, mx, my = self._still_pos.get(tr.track_id, (0, tr.x, tr.y))
            if math.hypot(tr.x - mx, tr.y - my) > 3.0:      # it has really moved: start again
                n, mx, my = 0, tr.x, tr.y
            n = min(n + 1, 400)
            mx += (tr.x - mx) / n
            my += (tr.y - my) / n
            self._still_pos[tr.track_id] = (n, mx, my)
            px, py = mx, my
            # Along our planned path: the route waypoint nearest the ERV gives both how far ahead it
            # is and its offset from OUR lane centre at ITS position. On a bend or through a junction
            # the lane frame at the ego is rotated against the one at the ERV and misjudges both.
            along = lat = None
            d, prev, near = 0.0, ego_loc, None
            for w in plan:
                wl = w.transform.location
                d += wl.distance(prev)
                prev = wl
                off = math.hypot(px - wl.x, py - wl.y)
                if near is None or off < near[0]:
                    near = (off, d, w)
                if d > 160.0:
                    break
            if near is not None and near[0] < 2.0 * lw and near[2] is not plan[0]:
                wt = near[2].transform
                wf, wr, wc = wt.get_forward_vector(), wt.get_right_vector(), wt.location
                along = near[1] + (px - wc.x) * wf.x + (py - wc.y) * wf.y
                lat = (px - wc.x) * wr.x + (py - wc.y) * wr.y
            else:                                           # alongside / behind us, or no plan: our own frame
                along = (px - ego_loc.x) * f.x + (py - ego_loc.y) * f.y
                lat = (px - c.x) * r.x + (py - c.y) * r.y
            if along < -(self.half_l + 8.0) or along > 150.0:
                continue
            if abs(lat) > 2.0 * lw:
                continue
            # a size that cannot be a road vehicle (some senders fill it in the wrong unit) is ignored
            width = tr.bsm.core.width_m if (tr.bsm.core.width_m or 0.0) >= 1.2 else 2.6
            length = tr.bsm.core.length_m if (tr.bsm.core.length_m or 0.0) >= 3.0 else 8.0
            sigma = min(tr.bsm.core.semi_major_m or 0.5, 1.5)        # what the sender says its position is good to
            left_edge = lat - width / 2.0 - max(0.3, 0.5 * sigma)
            need = min(left_edge - (self.half_w + self.pass_clearance), 0.0)
            # Once we are close, never give ground back: the offset only grows until the ERV is
            # fully behind us (its tail past ours), then it is dropped altogether.
            if along <= -(self.half_l + length / 2.0 + 2.0):
                self._pass_hold.pop(tr.track_id, None)
                continue
            held = self._pass_hold.get(tr.track_id)
            if held is not None:
                need = max(min(need, held), -self.policy.cfg.max_borrow_offset_m)
            if along < 50.0:
                self._pass_hold[tr.track_id] = need
            if best is None or along < best[0]:
                best = (along, need, tr)
        if best is None:
            return None, True
        along_erv = best[0]
        length = best[2].bsm.core.length_m if (best[2].bsm.core.length_m or 0.0) >= 3.0 else 8.0
        span = max(along_erv, 0.0) + length + 30.0            # road we need free in the other lane
        clear = True
        for other in self.world.get_actors().filter("vehicle.*"):
            if other.id == self.vehicle.id:
                continue
            ol = other.get_location()
            lat = (ol.x - c.x) * r.x + (ol.y - c.y) * r.y
            if not (-(1.5 * lw + 1.0) < lat < -(0.5 * lw - 0.3)):
                continue                                      # not in the lane to our left
            along = (ol.x - ego_loc.x) * f.x + (ol.y - ego_loc.y) * f.y
            ov = other.get_velocity()
            toward = -(ov.x * f.x + ov.y * f.y)               # its speed toward us
            if -10.0 < along < span + max(toward, 0.0) * 8.0:
                clear = False
                break
        return best[1], clear

    # ------------------------------------------------------------------------
    # lane change with gap check
    # ------------------------------------------------------------------------
    def _gap_ok(self, target_wp, speed: float) -> Tuple[bool, str]:
        tf = self.vehicle.get_transform()
        loc, fwd, right = tf.location, tf.get_forward_vector(), tf.get_right_vector()
        center = target_wp.transform.location
        half_lane = target_wp.lane_width / 2.0
        for other in self.world.get_actors().filter("vehicle.*"):
            if other.id == self.vehicle.id:
                continue
            ol = other.get_location()
            along = (ol.x - loc.x) * fwd.x + (ol.y - loc.y) * fwd.y
            if abs(along) > 80.0:
                continue
            lat_t = (ol.x - center.x) * right.x + (ol.y - center.y) * right.y
            ow = other.bounding_box.extent.y
            if abs(lat_t) > half_lane + ow - 0.3:
                continue
            ovl = other.get_velocity()
            o_along_speed = ovl.x * fwd.x + ovl.y * fwd.y
            ol_half = other.bounding_box.extent.x
            if along >= 0:
                need = max(6.0, 0.8 * speed + 2.0 * (speed - o_along_speed))
                if along - self.half_l - ol_half < need:
                    return False, f"front gap to {other.type_id}"
            else:
                closing = o_along_speed - speed
                need = max(8.0, 3.0 * closing + 5.0)
                if -along - self.half_l - ol_half < need:
                    return False, f"rear gap to {other.type_id}"
        return True, "ok"

    def _lane_change_path(self, wp, direction: str, speed: float):
        RO = self.RoadOption
        step = 2.0
        plan = [(wp, RO.LANEFOLLOW)]
        cur = wp
        d = 0.0
        while d < max(0.5 * speed, 2.0):
            cur, got = cc.walk_straight(cur, step, True, step)
            if got <= 0.0:
                return []
            plan.append((cur, RO.LANEFOLLOW))
            d += step
        side = cur.get_right_lane() if direction == "right" else cur.get_left_lane()
        if side is None or side.lane_type != carla.LaneType.Driving or side.lane_id * wp.lane_id <= 0:
            return []
        nxt = side.next(max(2.5 * speed, 10.0))
        if not nxt:
            return []
        side = nxt[0]
        plan.append((side, RO.CHANGELANERIGHT if direction == "right" else RO.CHANGELANELEFT))
        d = 0.0
        while d < max(4.0 * speed, 40.0):
            side, got = cc.walk_straight(side, step, True, step)
            if got <= 0.0:
                break
            plan.append((side, RO.LANEFOLLOW))
            d += step
        return plan

    def _start_lane_change(self, t: float, direction: str, ego_wp, speed: float) -> None:
        if self._lc is not None or t - self._last_lc_end < 2.0 or ego_wp.is_junction:
            return
        target = ego_wp.get_right_lane() if direction == "right" else ego_wp.get_left_lane()
        if target is None or target.lane_type != carla.LaneType.Driving or target.lane_id * ego_wp.lane_id <= 0:
            return
        ok, why = self._gap_ok(target, speed)
        if not ok:
            if self.evidence:
                self.evidence.event("lane_change_wait", t, direction=direction, reason=why)
            return
        path = self._lane_change_path(ego_wp, direction, speed)
        if not path:
            return
        self.base.set_global_plan(path, stop_waypoint_creation=False, clean_queue=True)
        self._route_suspended = True
        self._lc = {"dir": direction, "road": target.road_id, "lane": target.lane_id, "t0": t,
                    "from_lane": ego_wp.lane_id}
        self.metrics.lane_changes += 1
        if self.evidence:
            self.evidence.event("lane_change_start", t, direction=direction, from_lane=ego_wp.lane_id,
                                to_lane=target.lane_id)

    def _update_lane_change(self, t: float, ego_wp) -> None:
        if self._lc is None:
            return
        reached = ego_wp.lane_id == self._lc["lane"] or (
            ego_wp.road_id != self._lc["road"] and ego_wp.lane_id != self._lc["from_lane"])
        if reached or t - self._lc["t0"] > 8.0:
            if not reached:
                self.metrics.lane_change_aborts += 1
            if self.evidence:
                self.evidence.event("lane_change_end", t, reached=reached, lane=ego_wp.lane_id)
            self._lc = None
            self._last_lc_end = t

    def _follow_current_lane(self, ego_wp, length_m: float = 150.0) -> None:
        RO = self.RoadOption
        plan, cur, d = [(ego_wp, RO.LANEFOLLOW)], ego_wp, 0.0
        while d < length_m:
            # straight on at junctions: next()[0] is an arbitrary branch and would turn us off the road
            cur, got = cc.walk_straight(cur, 2.0, True, 2.0)
            if got <= 0.0:
                break
            plan.append((cur, RO.LANEFOLLOW))
            d += 2.0
        self.base.set_global_plan(plan, stop_waypoint_creation=False, clean_queue=True)
        self._route_suspended = True

    def _restore_route(self) -> None:
        if self._route_suspended and self.destination is not None:
            self.base.set_destination(self.destination)
        self._route_suspended = False

    # ------------------------------------------------------------------------
    # actuation helpers
    # ------------------------------------------------------------------------
    def _set_blinker(self, blinker: Optional[str], braking: bool) -> None:
        names = {"position", "low_beam"}
        if blinker == "left":
            names.add("left_blinker")
        elif blinker == "right":
            names.add("right_blinker")
        elif blinker == "hazard":
            names.add("hazard")
        if braking:
            names.add("brake")
        names = frozenset(names)
        if names != self._lights_cmd:
            cc.set_lights(self.vehicle, names)
            self._lights_cmd = names

    def _edge_offset_target(self, ctx: EgoContext, edge: bool) -> float:
        if not edge:
            return 0.0
        off = ctx.lane_width_m / 2.0 - self.half_w - self.edge_margin
        if self.use_shoulder and ctx.lanes_right == 0 and ctx.shoulder_right_m >= 1.5:
            off = ctx.lane_width_m / 2.0 + min(ctx.shoulder_right_m, 2 * self.half_w + 0.6) \
                - self.half_w - self.edge_margin
        return max(off, 0.0)

    # ------------------------------------------------------------------------
    # main step
    # ------------------------------------------------------------------------
    def run_step(self, t: float) -> carla.VehicleControl:
        dt = 0.05 if self._last_t is None else max(t - self._last_t, 1e-3)
        self._last_t = t
        ctx, ego_wp = self._ego_context()
        ego_loc = self.vehicle.get_location()

        # 1-2: V2X in, tracks
        for msg in self.receiver.poll(t, (ego_loc.x, ego_loc.y, ego_loc.z)):
            tr = self.tracker.ingest(msg)
            if tr is not None and tr.active and self.metrics.first_active_rx_t is None:
                self.metrics.first_active_rx_t = t
                if self.evidence:
                    self.evidence.event("first_active_erv_rx", t, track=tr.track_id, **tr.bsm.summary())
        self.tracker.update(t)

        # 3: assess
        threats = []
        for tr in self.tracker.all():
            near = math.hypot(tr.x - ctx.x, tr.y - ctx.y) <= self.awareness
            off = self._lane_offset(ego_wp, tr.x, tr.y, tr.z) if near and tr.move_over_relevant else None
            hint = self._road_hint(t, ego_wp, ego_loc, tr) if near else None
            threats.append(assess(ctx, tr, lane_offset=off, awareness_radius_m=self.awareness, road_hint=hint))
        self.last_threats = threats

        ctx.pass_offset_m, ctx.opposing_clear = self._pass_context(ego_wp, ego_loc)

        # 4: decide
        prev_mode = self.policy.mode
        action = self.policy.step(t, ctx, threats)
        self.last_action = action
        self._record_metrics(t, dt, ctx, action, prev_mode, threats)

        # 5: execute
        self._update_lane_change(t, ego_wp)
        if action.lane_change:
            self._start_lane_change(t, action.lane_change, ego_wp, ctx.speed_mps)

        if action.mode in (Mode.PULL_OVER, Mode.HOLD, Mode.STOP_BEFORE_JUNCTION) and self._lc is None \
                and not self._route_suspended:
            self._follow_current_lane(ego_wp)
        if action.mode in (Mode.CRUISE, Mode.RESUME) and self._lc is None:
            self._restore_route()

        target = self._edge_offset_target(ctx, action.edge_offset)
        if action.lateral_offset_m is not None:
            target = action.lateral_offset_m
        self._offset += max(-0.08, min(0.08, target - self._offset))
        cc.set_planner_offset(self.base, self._offset)

        # still angled / short of the edge: keep rolling slowly instead of stopping skewed
        settling = action.mode == Mode.PULL_OVER and action.stop and not ctx.settled
        speed_kmh = self.cruise_kmh
        if settling:
            speed_kmh = min(speed_kmh, self.settle_kmh)
        if self.respect_limits:
            speed_kmh = min(speed_kmh, ctx.speed_limit_mps * 3.6)
        if action.speed_cap_mps is not None:
            speed_kmh = min(speed_kmh, action.speed_cap_mps * 3.6)
        # a lower cap is approached at the comfort rate, not with a brake step
        if self._speed_cmd_kmh is not None and speed_kmh < self._speed_cmd_kmh:
            floor = max(ctx.speed_mps * 3.6, speed_kmh)
            ramp = min(self._speed_cmd_kmh, floor + 5.0) - self.comfort_decel * 3.6 * dt
            speed_kmh = max(speed_kmh, ramp)
        self._speed_cmd_kmh = speed_kmh
        self.base.set_target_speed(max(speed_kmh, 0.0))

        control = self.base.run_step()
        # BasicAgent's own emergency stop (red light, vehicle ahead): not part of the ERV response
        if control.throttle == 0.0 and control.brake >= 0.85:
            self._hazard_until = t + 0.5
        self._base_hazard = t < self._hazard_until
        if action.stop and not (settling and ctx.speed_mps <= self.settle_kmh / 3.6 + 0.3):
            v = ctx.speed_mps
            if v < self.policy.cfg.stop_speed_mps:
                control.throttle, control.brake = 0.0, 1.0
            else:
                if action.stop_distance_m is not None:
                    decel = v * v / (2.0 * max(action.stop_distance_m, 0.3))
                else:
                    decel = self.comfort_decel
                control.throttle = 0.0
                control.brake = max(control.brake, min(1.0, max(decel / self.full_brake_decel, 0.12)))
        self._set_blinker(action.blinker, control.brake > 0.1)

        # 6: own BSM
        if self.bsm_tx is not None and t - self._last_bsm >= self.bsm_period - 1e-6:
            gen, endpoint, codec = self.bsm_tx
            state = cc.vehicle_state(self.vehicle)
            bsm = gen.build(state, t)
            self.tracker.own_ids.add(bsm.core.temp_id)
            endpoint.send(codec.encode_bsm(bsm))
            self._last_bsm = t

        # 7: trace
        if self.evidence and t - self._last_trace >= self.trace_period - 1e-6:
            self._last_trace = t
            self._trace(t, ctx, ego_wp, action, threats)
        return control

    # ------------------------------------------------------------------------
    def _record_metrics(self, t, dt, ctx: EgoContext, action: Action, prev_mode: Mode, threats) -> None:
        m = self.metrics
        acc = self.vehicle.get_acceleration()
        fwd = self.vehicle.get_transform().get_forward_vector()
        m.on_accel(acc.x * fwd.x + acc.y * fwd.y, dt,
                   responding=action.mode in ACTION_MODES and not self._base_hazard)
        if action.mode.value not in m.modes_visited:
            m.modes_visited.append(action.mode.value)
        if action.mode in ACTION_MODES and m.first_action_t is None:
            m.first_action_t = t
            m.first_action_mode = action.mode.value
            rel = [th for th in threats if th.track_id in action.threat_ids] or \
                  [th for th in threats if th.active]
            if rel:
                m.range_at_first_action_m = min(th.range_m for th in rel)
        if action.mode == Mode.HOLD and prev_mode != Mode.HOLD and m.stopped_t is None:
            m.stopped_t = t
        if action.mode == Mode.RESUME and prev_mode != Mode.RESUME and m.stopped_t is not None and m.resume_t is None:
            m.resume_t = t
        came_to_stop = ctx.speed_mps < 0.2 <= self._prev_speed
        self._prev_speed = ctx.speed_mps
        if ctx.in_junction and came_to_stop and action.mode in YIELD_MODES:
            m.stopped_in_junction = True
        for th in threats:
            if th.active and not th.stale:
                m.on_erv_geometry(th.range_m, th.lateral_m, th.along_m, self.half_l + 4.0)

    def _trace(self, t, ctx: EgoContext, ego_wp, action: Action, threats: List[Threat]) -> None:
        acc = self.vehicle.get_acceleration()
        fwd = self.vehicle.get_transform().get_forward_vector()
        rel = [th for th in threats if th.active] or threats
        th = min(rel, key=lambda x: x.range_m) if rel else None
        self.evidence.trace({
            "t": t, "mode": action.mode.value, "ego_x": ctx.x, "ego_y": ctx.y, "ego_yaw": ctx.yaw_deg,
            "ego_speed": ctx.speed_mps, "ego_accel": acc.x * fwd.x + acc.y * fwd.y,
            "ego_lane": ego_wp.lane_id, "speed_cap": action.speed_cap_mps, "lane_change": action.lane_change,
            "stop": action.stop,
            "erv_track": th.track_id if th else None, "erv_rel": th.relation.value if th else None,
            "erv_range": th.range_m if th else None, "erv_along": th.along_m if th else None,
            "erv_lateral": th.lateral_m if th else None, "erv_ttr": th.time_to_reach_s if th else None,
            "erv_speed": th.erv_speed_mps if th else None,
        })
