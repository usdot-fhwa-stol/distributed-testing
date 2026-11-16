"""Build J2735 BSMs from live vehicle state, the way an OBU would.

Behaviours modelled:
* msgCnt increments modulo 128; secMark from the shared clock.
* 4-octet TemporaryID with optional rotation (J2945/1 rotates roughly every
  5 minutes; many agencies leave ERV IDs fixed). On rotation msgCnt restarts
  at a random value and path history is cleared, as J2945/1 requires, so the
  receiving tracker has to re-associate the vehicle by kinematics.
* GNSS error as a slowly wandering bias plus white noise, reflected in the
  PositionalAccuracy ellipse.
* Part II content selected by a profile:
    stol_sample  Part II-1 vehicleAlerts (sirenUse, lightsUse, multi) +
                 Part II-2 classDetails keyType 68 / role emergency.
                 No Part II-0, no responseType (matches the Leidos STOL sample
                 the Audi team reviewed).
    full         Part II-0 path history/prediction/lights/events,
                 Part II-1 with responseType, Part II-2 class by vehicle kind.
    basic        Ordinary vehicle (Part II-0 only); used for the ego's own BSM.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from typing import Dict, FrozenSet, Optional

from ..clock import Clock
from ..geo import CarlaGeoRef
from ..j2735.bsm import (Bsm, BsmCore, EmergencyDetails, SpecialVehicleExt,
                         SupplementalVehicleExt, VehicleSafetyExt)
from ..vehicle_state import VehicleState
from .path_history import PathHistoryBuilder

STEERING_RATIO = 16.0

# BasicVehicleClass / BasicVehicleRole per apparatus kind
KIND_CLASS: Dict[str, int] = {
    "firetruck": 63,   # emergency-Fire-Heavy-Vehicle
    "engine": 63,
    "ambulance": 65,   # emergency-Fire-Ambulance-Vehicle
    "police": 66,      # emergency-Police-Light-Vehicle
    "responder": 68,   # emergency-Other-Responder
}
KIND_ROLE: Dict[str, str] = {
    "firetruck": "fire", "engine": "fire", "ambulance": "ambulance",
    "police": "police", "responder": "emergency",
}


@dataclass
class BsmProfile:
    name: str
    part2_safety: bool = False
    part2_special: bool = False
    part2_supplemental: bool = False
    include_response_type: bool = False
    multi: str = "unavailable"              # MultiVehicleResponse
    key_type: Optional[int] = None          # None -> by kind
    classification: Optional[int] = None    # None -> omitted
    role: Optional[str] = None              # None -> by kind


PROFILES: Dict[str, BsmProfile] = {
    "stol_sample": BsmProfile("stol_sample", part2_special=True, part2_supplemental=True,
                              include_response_type=False, multi="unavailable",
                              key_type=68, role="emergency"),
    "full": BsmProfile("full", part2_safety=True, part2_special=True, part2_supplemental=True,
                       include_response_type=True, multi="singleVehicle"),
    "basic": BsmProfile("basic", part2_safety=True),
}


def profile_from_config(name: str, overrides: Optional[dict] = None) -> BsmProfile:
    base = PROFILES[name]
    if not overrides:
        return base
    valid = {k: v for k, v in overrides.items() if k in BsmProfile.__dataclass_fields__ and k != "name"}
    return replace(base, **valid)


class _GnssError:
    """Bias that random-walks toward zero (Gauss-Markov) plus white noise."""

    def __init__(self, sigma_m: float, tau_s: float, rng: random.Random):
        self.sigma = sigma_m
        self.tau = tau_s
        self.rng = rng
        self.bx = 0.0
        self.by = 0.0

    def sample(self, dt: float):
        if self.sigma <= 0:
            return 0.0, 0.0
        a = math.exp(-dt / self.tau) if self.tau > 0 else 0.0
        q = self.sigma * math.sqrt(max(1 - a * a, 0.0))
        self.bx = a * self.bx + self.rng.gauss(0, q)
        self.by = a * self.by + self.rng.gauss(0, q)
        w = 0.15 * self.sigma
        return self.bx + self.rng.gauss(0, w), self.by + self.rng.gauss(0, w)


class BsmGenerator:
    def __init__(self, georef: CarlaGeoRef, clock: Clock, profile: BsmProfile,
                 kind: str = "firetruck", temp_id: Optional[bytes] = None,
                 id_rotation_s: float = 0.0, gnss_sigma_m: float = 0.0, gnss_tau_s: float = 30.0,
                 seed: Optional[int] = None):
        self.georef = georef
        self.clock = clock
        self.profile = profile
        self.kind = kind
        self.rng = random.Random(seed)
        self.temp_id = temp_id or bytes(self.rng.getrandbits(8) for _ in range(4))
        self.id_rotation_s = id_rotation_s
        self.msg_cnt = self.rng.randrange(128)
        self.ph = PathHistoryBuilder()
        self.gnss = _GnssError(gnss_sigma_m, gnss_tau_s, self.rng)
        self.gnss_sigma = gnss_sigma_m
        self._id_since: Optional[float] = None
        self._last_t: Optional[float] = None
        self._yaw_rate_ema = 0.0
        self._prev_lights: FrozenSet[str] = frozenset()

    # ------------------------------------------------------------------------
    def _maybe_rotate_id(self, t: float) -> None:
        if self._id_since is None:
            self._id_since = t
            return
        if self.id_rotation_s > 0 and t - self._id_since >= self.id_rotation_s:
            self.temp_id = bytes(self.rng.getrandbits(8) for _ in range(4))
            self.msg_cnt = self.rng.randrange(128)
            self.ph.reset()
            self._id_since = t

    def _alerts(self, s: VehicleState) -> EmergencyDetails:
        lightbar = "lightbar" in s.lights
        caution = "caution" in s.lights
        if lightbar:
            lights_use = "inUse"
        elif caution:
            lights_use = "yellowCautionLights"
        else:
            lights_use = "notInUse"
        response = None
        if self.profile.include_response_type:
            if not (lightbar or s.siren):
                response = "notInUseOrNotEquipped"
            elif s.speed_mps < 0.3:
                response = "stationary"
            else:
                response = "emergency"
        return EmergencyDetails(siren_use="inUse" if s.siren else "notInUse", lights_use=lights_use,
                                multi=self.profile.multi, ssp_rights=0, response_type=response)

    def _events(self, s: VehicleState) -> FrozenSet[str]:
        ev = set()
        if "hazard" in s.lights:
            ev.add("eventHazardLights")
        if s.accel_long_mps2 < -4.0:
            ev.add("eventHardBraking")         # J2945/1 hard-braking threshold ~0.4 g
        if s.lights != self._prev_lights:
            ev.add("eventLightsChanged")
        return frozenset(ev)

    @staticmethod
    def _exterior_lights(s: VehicleState) -> FrozenSet[str]:
        m = {"low_beam": "lowBeamHeadlightsOn", "high_beam": "highBeamHeadlightsOn",
             "left_blinker": "leftTurnSignalOn", "right_blinker": "rightTurnSignalOn",
             "hazard": "hazardSignalOn", "fog": "fogLightOn", "position": "parkingLightsOn"}
        return frozenset(v for k, v in m.items() if k in s.lights)

    # ------------------------------------------------------------------------
    def build(self, s: VehicleState, t_sim: float) -> Bsm:
        dt = 0.1 if self._last_t is None else max(t_sim - self._last_t, 1e-3)
        self._last_t = t_sim
        self._maybe_rotate_id(t_sim)

        ex, ey = self.gnss.sample(dt)
        lat, lon, alt = self.georef.to_geo(s.x + ex, s.y + ey, s.z)
        self.ph.update(t_sim, s.x, s.y, s.z)

        if s.reverse:
            transmission = "reverseGears"
        elif s.hand_brake and s.speed_mps < 0.1:
            transmission = "park"
        else:
            transmission = "forwardGears"

        braking = s.brake > 0.05
        core = BsmCore(
            msg_cnt=self.msg_cnt,
            temp_id=self.temp_id,
            sec_mark_ms=self.clock.sec_mark(),
            lat_deg=lat, lon_deg=lon, elev_m=alt,
            semi_major_m=max(self.gnss_sigma, 0.1) if self.gnss_sigma > 0 else 0.5,
            semi_minor_m=max(self.gnss_sigma, 0.1) if self.gnss_sigma > 0 else 0.5,
            orientation_deg=0.0,
            transmission=transmission,
            speed_mps=s.speed_mps,
            heading_deg=self.georef.yaw_to_heading(s.yaw_deg),
            steering_wheel_deg=s.steer_norm * s.max_road_wheel_deg * STEERING_RATIO,
            accel_long_mps2=s.accel_long_mps2,
            accel_lat_mps2=s.accel_lat_mps2,
            accel_vert_g=s.accel_vert_g,
            yaw_rate_dps=s.yaw_rate_dps,
            wheel_brakes=frozenset({"leftFront", "leftRear", "rightFront", "rightRear"}) if braking else frozenset(),
            traction="off", abs="engaged" if (s.brake > 0.8 and s.speed_mps > 3.0) else "off",
            scs="off", brake_boost="off", aux_brakes="unavailable",
            width_m=s.width_m, length_m=s.length_m,
        )
        self.msg_cnt = (self.msg_cnt + 1) % 128

        bsm = Bsm(core=core)
        p = self.profile
        if p.part2_safety:
            self._yaw_rate_ema = 0.8 * self._yaw_rate_ema + 0.2 * s.yaw_rate_dps
            if s.speed_mps < 1.0:
                radius, conf = None, 0.0
            else:
                yr = self._yaw_rate_ema
                radius = None if abs(yr) < 0.5 else s.speed_mps / math.radians(yr)
                if radius is not None and abs(radius) > 3276.6:
                    radius = None
                instability = abs(s.yaw_rate_dps - yr) / max(abs(yr), 2.0)
                conf = 100.0 * max(0.0, min(1.0, 1.0 - instability))
            bsm.safety_ext = VehicleSafetyExt(
                events=self._events(s),
                path_history=self.ph.points(t_sim, lat, lon, alt, self.georef) or None,
                path_prediction_radius_m=radius,
                path_prediction_confidence_pct=conf,
                lights=self._exterior_lights(s),
            )
        if p.part2_special:
            bsm.special_ext = SpecialVehicleExt(vehicle_alerts=self._alerts(s))
        if p.part2_supplemental:
            key = p.key_type if p.key_type is not None else KIND_CLASS.get(self.kind, 68)
            role = p.role if p.role is not None else KIND_ROLE.get(self.kind, "emergency")
            bsm.supplemental_ext = SupplementalVehicleExt(classification=p.classification, key_type=key, role=role)
        self._prev_lights = s.lights
        return bsm
