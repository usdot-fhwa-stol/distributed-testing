"""Emergency-vehicle response policy (state machine).

Modelled on California rules, configurable for other jurisdictions:

* CVC 21806 - on the immediate approach of an authorized emergency vehicle
  using siren and red lights, yield, drive to the right-hand edge of the
  road clear of any intersection, stop, and remain stopped until it has
  passed. Implemented as: CLEAR_JUNCTION (if inside one) -> YIELD_CHANGE_LANE
  (step right, one lane at a time, gap permitting) -> PULL_OVER (hug the
  right edge, comfortable stop) -> HOLD -> RESUME. If a junction is close
  ahead, stop short of it instead (STOP_BEFORE_JUNCTION).
* CVC 21809 - approaching a stationary emergency vehicle, tow truck or
  Caltrans vehicle displaying flashing lights: vacate the adjacent lane if
  safe, otherwise slow to a reasonable and prudent speed (MOVE_OVER /
  SLOW_PASS).
* Oncoming ERV on an undivided road triggers the same yield; on a divided
  road it is exempt by default (``divided_oncoming_exempt``).
* ERV ahead going our way: no overtaking, do not exceed the limit (FOLLOW).
* Crossing ERV at a junction we are about to enter: stop short and hold.

This is a research policy, not legal advice; the thresholds are parameters.
The policy is pure: it emits an Action, and the CARLA agent executes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Optional, Set

from .situation import EgoContext, Relation, Threat


class Mode(str, Enum):
    CRUISE = "CRUISE"
    ALERT = "ALERT"
    FOLLOW = "FOLLOW"
    CLEAR_JUNCTION = "CLEAR_JUNCTION"
    YIELD_CHANGE_LANE = "YIELD_CHANGE_LANE"
    PULL_OVER = "PULL_OVER"
    STOP_BEFORE_JUNCTION = "STOP_BEFORE_JUNCTION"
    HOLD = "HOLD"
    MOVE_OVER = "MOVE_OVER"
    SLOW_PASS = "SLOW_PASS"
    RESUME = "RESUME"


YIELD_FAMILY = {Mode.CLEAR_JUNCTION, Mode.YIELD_CHANGE_LANE, Mode.PULL_OVER,
                Mode.STOP_BEFORE_JUNCTION, Mode.HOLD}


@dataclass
class PolicyConfig:
    awareness_radius_m: float = 500.0
    yield_trigger_ttr_s: float = 12.0
    yield_trigger_range_m: float = 150.0
    oncoming_trigger_range_m: float = 200.0
    divided_oncoming_exempt: bool = True
    junction_keepout_m: float = 25.0        # stop short if a junction is this close
    crossing_trigger_ttr_s: float = 10.0
    crossing_stop_range_m: float = 60.0
    move_over_trigger_m: float = 250.0
    move_over_pass_clear_m: float = 25.0
    slow_pass_kmh: float = 40.0
    slow_pass_below_limit_kmh: float = 25.0  # cap = min(slow_pass_kmh, limit - this), floor 15
    slow_pass_start_m: float = 100.0         # begin slowing this far before the stationary ERV
    blocked_stop_gap_m: float = 12.0         # stop this far (centre to centre) behind an ERV blocking our lane
    borrow_opposing_lane: bool = True        # pass a lane-blocking stationary ERV through the opposing lane if clear
    max_borrow_offset_m: float = 4.5         # never move further left than this to get round it
    borrow_start_m: float = 45.0             # start moving out this far before the ERV
    alert_cap_to_limit: bool = True
    clear_distance_m: float = 15.0
    clear_delay_s: float = 3.0
    multi_vehicle_extra_hold_s: float = 6.0
    stale_hold_s: float = 5.0
    clear_receding_m: float = 5.0           # range must open this much past its minimum to count as "gone by"
    stalled_clear_s: float = 8.0            # ERV neither closing nor leaving (stopped short of us): wait this long
    min_hold_s: float = 1.0
    resume_s: float = 3.0
    stop_speed_mps: float = 0.2
    junction_clear_kmh: float = 15.0
    lane_change_timeout_s: float = 6.0
    pull_over_settle_s: float = 6.0         # max time spent straightening up at the edge before holding anyway
    max_stop_decel_mps2: float = 4.0        # beyond this, proceed through a junction then yield

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "PolicyConfig":
        d = d or {}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Action:
    mode: Mode
    speed_cap_mps: Optional[float] = None
    lane_change: Optional[str] = None       # "left" | "right"
    stop: bool = False
    stop_distance_m: Optional[float] = None # None -> comfortable stop wherever we are
    edge_offset: bool = False               # hug the right edge of the lane
    lateral_offset_m: Optional[float] = None # drive this far from lane centre (+ right); passing a stationary ERV
    no_discretionary_lane_change: bool = False
    blinker: Optional[str] = None           # "left" | "right" | "hazard"
    reason: str = ""
    threat_ids: List[int] = field(default_factory=list)


class ErvPolicy:
    def __init__(self, cfg: PolicyConfig, evidence=None):
        self.cfg = cfg
        self.evidence = evidence
        self.mode = Mode.CRUISE
        self.mode_since = 0.0
        self._latched: Set[int] = set()        # threats that put us into yield/move-over
        self._last_seen: Dict[int, float] = {}
        self._last_rel: Dict[int, Relation] = {}
        self._cleared_since: Optional[float] = None
        self._hold_min: Dict[int, float] = {}  # nearest approach of each latched threat while we hold
        self._idle_since: Dict[int, float] = {}
        self._multi_seen = False
        self._move_over_target: Optional[int] = None
        self._borrowing = False                # committed to passing through the opposing lane
        self._junction_entered = False

    # ------------------------------------------------------------------------
    def _set(self, t: float, mode: Mode, reason: str, threats: Iterable[Threat] = ()) -> None:
        if mode != self.mode:
            if self.evidence:
                self.evidence.event("mode", t, frm=self.mode.value, to=mode.value, reason=reason,
                                    threats=[{"track": x.track_id, "rel": x.relation.value,
                                              "range": round(x.range_m, 1), "ttr": x.time_to_reach_s}
                                             for x in threats])
            self.mode = mode
            self.mode_since = t
            if mode == Mode.HOLD:
                self._hold_min.clear()
                self._idle_since.clear()

    def _yield_demand(self, ego: EgoContext, th: Threat) -> bool:
        c = self.cfg
        if not th.active or th.stale:
            return False
        if th.relation == Relation.APPROACHING_FROM_BEHIND:
            return (th.time_to_reach_s is not None and th.time_to_reach_s < c.yield_trigger_ttr_s) \
                or th.range_m < c.yield_trigger_range_m
        if th.relation == Relation.ONCOMING:
            if c.divided_oncoming_exempt and not ego.undivided:
                return False
            return (th.time_to_reach_s is not None and th.time_to_reach_s < c.yield_trigger_ttr_s) \
                or th.range_m < c.oncoming_trigger_range_m
        return False

    def _crossing_demand(self, ego: EgoContext, th: Threat) -> bool:
        c = self.cfg
        return (th.active and not th.stale and th.relation == Relation.CROSSING
                and th.time_to_reach_s is not None and th.time_to_reach_s < c.crossing_trigger_ttr_s
                and ego.dist_to_junction_m is not None and ego.dist_to_junction_m < c.crossing_stop_range_m)

    def _move_over_demand(self, th: Threat) -> bool:
        return (th.move_over_relevant and not th.stale and th.relation == Relation.STATIONARY_AHEAD
                and th.along_m < self.cfg.move_over_trigger_m)

    def _slow_pass_cap(self, ego: EgoContext) -> float:
        limit_kmh = ego.speed_limit_mps * 3.6
        cap = min(self.cfg.slow_pass_kmh, limit_kmh - self.cfg.slow_pass_below_limit_kmh)
        return max(cap, 15.0) / 3.6

    def _latched_cleared(self, t: float, threats: Dict[int, Threat]) -> bool:
        """All latched threats have passed / gone dark / been silent long enough.

        "Unrelated" is not the same as "gone": on a curved road, or while the ego
        sits angled at the kerb, an ERV that is still on its way to us fails the
        straight-line carriageway test. So a latched threat is released only when
        it has demonstrably gone by (range opening again past its minimum), went
        dark, or has been neither closing nor leaving for ``stalled_clear_s``.
        """
        c = self.cfg
        near = max(c.yield_trigger_range_m, c.oncoming_trigger_range_m)
        for tid in list(self._latched):
            th = threats.get(tid)
            if th is None or th.stale:
                # gone quiet after it had already passed / turned away: normal, not lost comms
                if th is None and self._last_rel.get(tid) in (Relation.PASSED, Relation.UNRELATED):
                    continue
                if t - self._last_seen.get(tid, t) < c.stale_hold_s:
                    return False
                continue
            if not th.active:
                continue
            lo = self._hold_min.get(tid)
            if lo is None or th.range_m < lo:
                self._hold_min[tid] = lo = th.range_m
            receding = th.range_m - lo >= c.clear_receding_m
            if receding and th.range_m > c.clear_distance_m and th.closing_mps <= 0.5:
                # it came, it went: on a bend or past a junction the relation may read as
                # crossing or stationary-ahead, but the range has opened and is not closing
                self._idle_since.pop(tid, None)
                continue
            if th.relation == Relation.STATIONARY_AHEAD and th.along_m > 0.0:
                # it went by and stopped in front of us (arrived on scene): stop yielding after
                # a while; the move-over logic then deals with it as a stationary ERV
                if t - self._idle_since.setdefault(tid, t) < c.stalled_clear_s:
                    return False
                continue
            if th.relation in (Relation.PASSED, Relation.AHEAD_SAME_DIR):
                if th.stationary and th.along_m < 0.0 and not receding:
                    # stopped behind us without having gone by (however close): give it
                    # time to move off again, then go - waiting forever helps nobody
                    if t - self._idle_since.setdefault(tid, t) < c.stalled_clear_s:
                        return False
                    continue
                if th.range_m < c.clear_distance_m:
                    return False
                if th.relation == Relation.AHEAD_SAME_DIR and th.closing_mps > 0.5:
                    return False          # ERV ahead but slowing toward us
                self._idle_since.pop(tid, None)
                continue
            if th.relation == Relation.UNRELATED:
                if th.closing_mps > 0.5 and th.range_m < near:
                    self._idle_since.pop(tid, None)
                    return False          # still getting nearer (e.g. around a bend)
                if receding and th.range_m > c.clear_distance_m:
                    self._idle_since.pop(tid, None)
                    continue
                if t - self._idle_since.setdefault(tid, t) < c.stalled_clear_s:
                    return False
                continue
            self._idle_since.pop(tid, None)
            return False
        return True

    # ------------------------------------------------------------------------
    def step(self, t: float, ego: EgoContext, threats: List[Threat]) -> Action:
        c = self.cfg
        by_id = {th.track_id: th for th in threats}
        for th in threats:
            if not th.stale:
                self._last_seen[th.track_id] = t
                self._last_rel[th.track_id] = th.relation
            if th.multi:
                self._multi_seen = True

        yield_threats = [th for th in threats if self._yield_demand(ego, th)]
        crossing = [th for th in threats if self._crossing_demand(ego, th)]
        move_over = [th for th in threats if self._move_over_demand(th)]
        follow = [th for th in threats if th.active and not th.stale and th.relation == Relation.AHEAD_SAME_DIR
                  and th.range_m < c.awareness_radius_m]
        aware = [th for th in threats if th.active and not th.stale
                 and th.relation not in (Relation.UNRELATED, Relation.PASSED)]

        # ---- entering the yield family (highest priority) ----------------------
        if yield_threats or crossing:
            self._latched.update(th.track_id for th in yield_threats + crossing)
            self._cleared_since = None
            if self.mode not in YIELD_FAMILY:
                near_junction = ego.dist_to_junction_m is not None and ego.dist_to_junction_m < c.junction_keepout_m
                if ego.in_junction:
                    self._junction_entered = True
                    self._set(t, Mode.CLEAR_JUNCTION, "ERV demand while inside junction", yield_threats + crossing)
                elif crossing:
                    # a crossing ERV is the conflict: stop short even if braking is firm
                    self._set(t, Mode.STOP_BEFORE_JUNCTION, "crossing ERV at junction ahead", crossing)
                elif near_junction:
                    room = max(ego.dist_to_junction_m - 2.0, 0.1)
                    if ego.speed_mps ** 2 / (2 * room) <= c.max_stop_decel_mps2:
                        self._set(t, Mode.STOP_BEFORE_JUNCTION, "yield: stop short of junction", yield_threats)
                    else:
                        self._junction_entered = False
                        self._set(t, Mode.CLEAR_JUNCTION, "too close to stop: proceed through, then yield",
                                  yield_threats)
                elif ego.lanes_right > 0:
                    self._set(t, Mode.YIELD_CHANGE_LANE, "yield: move right", yield_threats)
                else:
                    self._set(t, Mode.PULL_OVER, "yield: pull to right edge", yield_threats)

        # ---- progress within the yield family ----------------------------------
        if self.mode in YIELD_FAMILY:
            return self._yield_step(t, ego, by_id)

        # ---- move-over ------------------------------------------------------------
        if move_over or self.mode in (Mode.MOVE_OVER, Mode.SLOW_PASS):
            act = self._move_over_step(t, ego, by_id, move_over)
            if act is not None:
                return act

        # ---- resume ----------------------------------------------------------------
        if self.mode == Mode.RESUME:
            if t - self.mode_since < c.resume_s:
                return Action(Mode.RESUME, speed_cap_mps=ego.speed_limit_mps, no_discretionary_lane_change=True,
                              blinker="left" if t - self.mode_since < 1.5 else None, reason="re-entering traffic")
            self._latched.clear()
            self._multi_seen = False

        if follow:
            self._set(t, Mode.FOLLOW, "ERV ahead, same direction", follow)
            return Action(Mode.FOLLOW, speed_cap_mps=ego.speed_limit_mps, no_discretionary_lane_change=True,
                          reason="do not overtake ERV", threat_ids=[x.track_id for x in follow])
        if aware:
            self._set(t, Mode.ALERT, "active ERV in range", aware)
            return Action(Mode.ALERT, speed_cap_mps=ego.speed_limit_mps if c.alert_cap_to_limit else None,
                          no_discretionary_lane_change=True, reason="monitoring",
                          threat_ids=[x.track_id for x in aware])
        self._set(t, Mode.CRUISE, "no relevant ERV")
        return Action(Mode.CRUISE)

    # ------------------------------------------------------------------------
    def _yield_step(self, t: float, ego: EgoContext, by_id: Dict[int, Threat]) -> Action:
        c = self.cfg
        ids = sorted(self._latched)
        stopped = ego.speed_mps < c.stop_speed_mps

        if self.mode == Mode.CLEAR_JUNCTION:
            if ego.in_junction:
                self._junction_entered = True
            approaching = (not self._junction_entered and ego.dist_to_junction_m is not None
                           and ego.dist_to_junction_m < c.junction_keepout_m)
            if not ego.in_junction and not approaching:
                dj = ego.dist_to_junction_m
                if self._junction_entered and dj is not None and dj < c.junction_keepout_m:
                    # another junction right behind the one we just left
                    if ego.speed_mps ** 2 / (2 * max(dj - 2.0, 0.1)) <= c.max_stop_decel_mps2:
                        self._set(t, Mode.STOP_BEFORE_JUNCTION, "cleared junction; stop short of the next one")
                    else:
                        self._junction_entered = False
                        return Action(Mode.CLEAR_JUNCTION,
                                      speed_cap_mps=max(c.junction_clear_kmh / 3.6,
                                                        min(ego.speed_mps, ego.speed_limit_mps)),
                                      no_discretionary_lane_change=True, blinker="right",
                                      reason="next junction too close to stop: proceed through", threat_ids=ids)
                else:
                    nxt = Mode.YIELD_CHANGE_LANE if ego.lanes_right > 0 else Mode.PULL_OVER
                    self._set(t, nxt, "cleared junction")
            else:
                cap = max(c.junction_clear_kmh / 3.6, min(ego.speed_mps, ego.speed_limit_mps))
                return Action(Mode.CLEAR_JUNCTION, speed_cap_mps=cap,
                              no_discretionary_lane_change=True, blinker="right",
                              reason="do not stop inside junction", threat_ids=ids)

        if self.mode == Mode.STOP_BEFORE_JUNCTION:
            if stopped:
                self._set(t, Mode.HOLD, "stopped short of junction")
            elif ego.in_junction:
                self._set(t, Mode.CLEAR_JUNCTION, "entered junction while stopping")
                return self._yield_step(t, ego, by_id)
            else:
                dist = None if ego.dist_to_junction_m is None else max(ego.dist_to_junction_m - 2.0, 0.0)
                return Action(Mode.STOP_BEFORE_JUNCTION, stop=True, stop_distance_m=dist, edge_offset=True,
                              no_discretionary_lane_change=True, blinker="right",
                              reason="stop clear of intersection", threat_ids=ids)

        if self.mode == Mode.YIELD_CHANGE_LANE:
            if ego.lanes_right == 0:
                self._set(t, Mode.PULL_OVER, "in rightmost lane")
            elif t - self.mode_since > c.lane_change_timeout_s:
                self._set(t, Mode.PULL_OVER, "no gap to the right; stopping in lane")
            else:
                return Action(Mode.YIELD_CHANGE_LANE, lane_change="right",
                              speed_cap_mps=min(ego.speed_limit_mps, max(ego.speed_mps, 5.0)),
                              no_discretionary_lane_change=True, blinker="right",
                              reason="vacate lanes toward right edge", threat_ids=ids)

        if self.mode == Mode.PULL_OVER and not stopped:
            # the pull-over must end clear of any intersection: stop short of a junction
            # that is close ahead, and keep going if we have rolled into one
            dj = ego.dist_to_junction_m
            if ego.in_junction:
                self._junction_entered = True
                self._set(t, Mode.CLEAR_JUNCTION, "entered junction while pulling over")
                return self._yield_step(t, ego, by_id)
            if dj is not None and dj < 12.0:
                self._set(t, Mode.STOP_BEFORE_JUNCTION, "pull-over would end in junction: stop short")
                return self._yield_step(t, ego, by_id)

        if self.mode == Mode.PULL_OVER:
            if stopped and (ego.settled or t - self.mode_since >= c.pull_over_settle_s):
                self._set(t, Mode.HOLD, "stopped at right edge" if ego.settled else "stopped (edge not reached)")
            else:
                return Action(Mode.PULL_OVER, stop=True, edge_offset=True, no_discretionary_lane_change=True,
                              blinker="right", reason="pull to right edge and stop", threat_ids=ids)

        # HOLD
        if self._latched_cleared(t, by_id) and t - self.mode_since >= c.min_hold_s:
            if self._cleared_since is None:
                self._cleared_since = t
            wait = c.clear_delay_s + (c.multi_vehicle_extra_hold_s if self._multi_seen else 0.0)
            if t - self._cleared_since >= wait:
                self._set(t, Mode.RESUME, f"ERV(s) clear for {wait:.1f}s")
                return Action(Mode.RESUME, speed_cap_mps=ego.speed_limit_mps, no_discretionary_lane_change=True,
                              blinker="left", reason="re-entering traffic")
        else:
            self._cleared_since = None
        return Action(Mode.HOLD, stop=True, stop_distance_m=0.0, edge_offset=True,
                      no_discretionary_lane_change=True, blinker="right",
                      reason="remain stopped until ERV passes", threat_ids=ids)

    # ------------------------------------------------------------------------
    def _move_over_step(self, t: float, ego: EgoContext, by_id: Dict[int, Threat],
                        demands: List[Threat]) -> Optional[Action]:
        c = self.cfg
        if demands:
            target = min(demands, key=lambda x: x.along_m)
            self._move_over_target = target.track_id
        else:
            target = by_id.get(self._move_over_target) if self._move_over_target is not None else None

        # The ERV we were treating as a stationary scene is driving again (it was waiting, or it
        # has left the scene): this is no longer a move-over. Hand back to the normal logic, which
        # follows it without overtaking. Exception: we are already alongside it in the other lane.
        if target is not None and not target.stale and not target.stationary \
                and not (self._borrowing and target.along_m < 12.0):
            self._move_over_target = None
            self._borrowing = False
            if self.evidence:
                self.evidence.event("move_over_dropped", t, track=target.track_id, reason="ERV is moving",
                                    erv_speed=target.erv_speed_mps, range=target.range_m)
            return None

        if target is None or target.along_m < -c.move_over_pass_clear_m or target.stale \
                or not target.move_over_relevant:
            self._move_over_target = None
            self._borrowing = False
            self._set(t, Mode.RESUME, "passed stationary ERV")
            return Action(Mode.RESUME, speed_cap_mps=ego.speed_limit_mps, reason="passed")

        off = target.lane_offset
        direction = None
        if off is not None:
            if off >= 0 and abs(off) <= 1 and ego.lanes_left > 0:
                direction = "left"
            elif off < 0 and abs(off) <= 1 and ego.lanes_right > 0:
                direction = "right"

        if direction is not None and target.along_m > 15.0:
            self._set(t, Mode.MOVE_OVER, "vacate lane adjacent to stationary ERV", [target])
            return Action(Mode.MOVE_OVER, lane_change=direction, speed_cap_mps=ego.speed_limit_mps,
                          no_discretionary_lane_change=True, blinker=direction,
                          reason=f"move {direction}, ERV lane offset {off}", threat_ids=[target.track_id])

        # No lane to change into. If the apparatus leaves too little room in our lane, go round
        # it: inside our own lane when that is enough, otherwise through the opposing lane when
        # the road is undivided and that lane is clear (CVC 21809: slow, and give it room).
        need = ego.pass_offset_m
        if direction is None and need is not None and need < -0.05:
            in_lane_limit = -max(ego.lane_width_m / 2.0 - ego.half_width_m - 0.2, 0.0)
            borrow = need < in_lane_limit
            allowed = (not borrow) or self._borrowing or (
                c.borrow_opposing_lane and ego.undivided and ego.lanes_left == 0
                and ego.opposing_clear and need >= -c.max_borrow_offset_m)
            if allowed:
                cap = self._slow_pass_cap(ego) if target.along_m <= c.slow_pass_start_m else ego.speed_limit_mps
                moving_out = target.along_m <= c.borrow_start_m
                if borrow and moving_out:
                    self._borrowing = True
                approach = target.along_m > 10.0
                mode = Mode.MOVE_OVER if (borrow and approach and moving_out) else Mode.SLOW_PASS
                self._set(t, mode, ("move out through the opposing lane to pass stationary ERV" if borrow
                                    else "give stationary ERV room within the lane")
                          if mode == Mode.MOVE_OVER or not borrow else "passing stationary ERV in the opposing lane",
                          [target])
                return Action(mode, speed_cap_mps=cap, lateral_offset_m=need if moving_out else None,
                              no_discretionary_lane_change=True,
                              blinker=("left" if borrow and moving_out and target.along_m > -2.0 else None),
                              reason=f"pass stationary ERV with {need:+.1f} m lateral offset",
                              threat_ids=[target.track_id])

        # The apparatus stands in our own lane and we cannot go round it (divided road, oncoming
        # traffic, or no room): come to a controlled stop behind it and wait.
        if need is not None:
            in_our_lane = need < -0.05
        else:
            in_our_lane = (off == 0 if off is not None else abs(target.lateral_m) < 0.5 * ego.lane_width_m) \
                and abs(target.lateral_m) < ego.half_width_m + 1.2
        # only for an ERV still in front of us: once it is behind, 'in our lane' is just where we came from
        if in_our_lane and direction is None and 0.0 < target.along_m <= c.slow_pass_start_m:
            self._set(t, Mode.SLOW_PASS, "lane blocked by stationary ERV", [target])
            return Action(Mode.SLOW_PASS, stop=True, stop_distance_m=max(target.along_m - c.blocked_stop_gap_m, 0.0),
                          speed_cap_mps=self._slow_pass_cap(ego), no_discretionary_lane_change=True,
                          blinker="hazard" if ego.speed_mps < c.stop_speed_mps else None,
                          reason="stop behind stationary ERV blocking the lane", threat_ids=[target.track_id])

        cap = self._slow_pass_cap(ego)
        if off is not None and abs(off) >= 2:
            cap = min(ego.speed_limit_mps, cap + 15.0 / 3.6)   # moved over: modest slow-down
        if target.along_m > c.slow_pass_start_m:
            cap = ego.speed_limit_mps                          # not at the scene yet
        self._set(t, Mode.SLOW_PASS, "cannot vacate adjacent lane" if (off is not None and abs(off) <= 1)
                  else "passing stationary ERV", [target])
        return Action(Mode.SLOW_PASS, speed_cap_mps=cap, no_discretionary_lane_change=True,
                      reason="slow to reasonable and prudent speed", threat_ids=[target.track_id])
