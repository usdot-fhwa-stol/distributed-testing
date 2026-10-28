"""BasicSafetyMessage data model.

Internally everything is SI (degrees, metres, m/s, seconds). ``to_asn1_dict``
produces the exact Python value structure asn1tools expects for the J2735
types (ENUMERATED -> identifier string, BIT STRING -> (bytes, nbits),
OCTET STRING -> bytes). Part II values are left as nested dicts; the codec
turns them into open-type bytes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from . import constants as C


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def _clamp(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else hi if v > hi else v


def bits_to_asn1(names: Optional[FrozenSet[str]], table: List[str], nbits: int) -> Tuple[bytes, int]:
    """Named-bit set -> asn1tools BIT STRING value (bit 0 is the MSB of byte 0)."""
    value = 0
    nbytes = (nbits + 7) // 8
    for name in names or ():
        idx = table.index(name)
        value |= 1 << (nbytes * 8 - 1 - idx)
    return value.to_bytes(nbytes, "big"), nbits


def asn1_to_bits(value: Any, table: List[str]) -> FrozenSet[str]:
    if value is None:
        return frozenset()
    data, nbits = value
    out = set()
    for idx in range(min(nbits, len(table))):
        byte = data[idx // 8]
        if byte & (0x80 >> (idx % 8)):
            out.add(table[idx])
    return frozenset(out)


def wrap_heading_deg(h: float) -> float:
    h = math.fmod(h, 360.0)
    return h + 360.0 if h < 0 else h


# ----------------------------------------------------------------------------
# Core data
# ----------------------------------------------------------------------------

@dataclass
class BsmCore:
    msg_cnt: int
    temp_id: bytes
    sec_mark_ms: Optional[int]
    lat_deg: Optional[float]
    lon_deg: Optional[float]
    elev_m: Optional[float] = None
    semi_major_m: Optional[float] = None
    semi_minor_m: Optional[float] = None
    orientation_deg: Optional[float] = None
    transmission: str = "unavailable"
    speed_mps: Optional[float] = None
    heading_deg: Optional[float] = None
    steering_wheel_deg: Optional[float] = None
    accel_long_mps2: Optional[float] = None
    accel_lat_mps2: Optional[float] = None
    accel_vert_g: Optional[float] = None
    yaw_rate_dps: float = 0.0
    wheel_brakes: FrozenSet[str] = frozenset({"unavailable"})
    traction: str = "unavailable"
    abs: str = "unavailable"
    scs: str = "unavailable"
    brake_boost: str = "unavailable"
    aux_brakes: str = "unavailable"
    width_m: Optional[float] = None
    length_m: Optional[float] = None

    # -- encode ---------------------------------------------------------------
    def to_asn1_dict(self) -> Dict[str, Any]:
        if len(self.temp_id) != 4:
            raise ValueError("TemporaryID must be exactly 4 octets")

        def opt(v, lsb, lo, hi, unavailable):
            if v is None:
                return unavailable
            return _clamp(int(round(v / lsb)), lo, hi)

        lat = opt(self.lat_deg, C.LATLON_LSB_DEG, C.LAT_MIN, C.LAT_MAX, C.LAT_UNAVAILABLE)
        lon = opt(self.lon_deg, C.LATLON_LSB_DEG, C.LON_MIN, C.LON_MAX, C.LON_UNAVAILABLE)
        if self.heading_deg is None:
            heading = C.HEADING_UNAVAILABLE
        else:
            heading = int(round(wrap_heading_deg(self.heading_deg) / C.HEADING_LSB_DEG)) % 28800
        if self.orientation_deg is None:
            orientation = C.ORIENTATION_UNAVAILABLE
        else:
            orientation = int(round(wrap_heading_deg(self.orientation_deg) / C.ORIENTATION_LSB_DEG)) % 65535
        speed = C.SPEED_UNAVAILABLE if self.speed_mps is None else _clamp(
            int(round(max(self.speed_mps, 0.0) / C.SPEED_LSB_MPS)), 0, C.SPEED_MAX)

        return {
            "msgCnt": self.msg_cnt % C.MSG_CNT_MODULO,
            "id": bytes(self.temp_id),
            "secMark": C.SEC_MARK_UNAVAILABLE if self.sec_mark_ms is None else int(self.sec_mark_ms),
            "lat": lat,
            "long": lon,
            "elev": opt(self.elev_m, C.ELEV_LSB_M, C.ELEV_MIN, C.ELEV_MAX, C.ELEV_UNAVAILABLE),
            "accuracy": {
                "semiMajor": opt(self.semi_major_m, C.SEMI_AXIS_LSB_M, 0, C.SEMI_AXIS_MAX, C.SEMI_AXIS_UNAVAILABLE),
                "semiMinor": opt(self.semi_minor_m, C.SEMI_AXIS_LSB_M, 0, C.SEMI_AXIS_MAX, C.SEMI_AXIS_UNAVAILABLE),
                "orientation": orientation,
            },
            "transmission": self.transmission,
            "speed": speed,
            "heading": heading,
            "angle": opt(self.steering_wheel_deg, C.STEER_WHEEL_LSB_DEG, C.STEER_WHEEL_MIN,
                         C.STEER_WHEEL_MAX, C.STEER_WHEEL_UNAVAILABLE),
            "accelSet": {
                "long": opt(self.accel_long_mps2, C.ACCEL_LSB_MPS2, C.ACCEL_MIN, C.ACCEL_MAX, C.ACCEL_UNAVAILABLE),
                "lat": opt(self.accel_lat_mps2, C.ACCEL_LSB_MPS2, C.ACCEL_MIN, C.ACCEL_MAX, C.ACCEL_UNAVAILABLE),
                "vert": opt(self.accel_vert_g, C.VERT_ACCEL_LSB_G, C.VERT_ACCEL_MIN, C.VERT_ACCEL_MAX,
                            C.VERT_ACCEL_UNAVAILABLE),
                "yaw": _clamp(int(round(self.yaw_rate_dps / C.YAW_RATE_LSB_DPS)), C.YAW_RATE_MIN, C.YAW_RATE_MAX),
            },
            "brakes": {
                "wheelBrakes": bits_to_asn1(self.wheel_brakes, C.WHEEL_BRAKE_BITS, 5),
                "traction": self.traction,
                "abs": self.abs,
                "scs": self.scs,
                "brakeBoost": self.brake_boost,
                "auxBrakes": self.aux_brakes,
            },
            "size": {
                "width": 0 if self.width_m is None else _clamp(int(round(self.width_m * 100)), 0, C.VEHICLE_WIDTH_MAX_CM),
                "length": 0 if self.length_m is None else _clamp(int(round(self.length_m * 100)), 0, C.VEHICLE_LENGTH_MAX_CM),
            },
        }

    # -- decode ---------------------------------------------------------------
    @classmethod
    def from_asn1_dict(cls, d: Dict[str, Any]) -> "BsmCore":
        def opt(raw, lsb, unavailable):
            return None if raw is None or raw == unavailable else raw * lsb

        acc = d.get("accuracy") or {}
        accel = d.get("accelSet") or {}
        brakes = d.get("brakes") or {}
        size = d.get("size") or {}
        width_cm, length_cm = size.get("width"), size.get("length")
        orientation = acc.get("orientation")
        sec_mark = d.get("secMark")
        return cls(
            msg_cnt=int(d["msgCnt"]),
            temp_id=bytes(d["id"]),
            sec_mark_ms=None if sec_mark in (None, C.SEC_MARK_UNAVAILABLE) else int(sec_mark),
            lat_deg=opt(d.get("lat"), C.LATLON_LSB_DEG, C.LAT_UNAVAILABLE),
            lon_deg=opt(d.get("long"), C.LATLON_LSB_DEG, C.LON_UNAVAILABLE),
            elev_m=opt(d.get("elev"), C.ELEV_LSB_M, C.ELEV_UNAVAILABLE),
            semi_major_m=opt(acc.get("semiMajor"), C.SEMI_AXIS_LSB_M, C.SEMI_AXIS_UNAVAILABLE),
            semi_minor_m=opt(acc.get("semiMinor"), C.SEMI_AXIS_LSB_M, C.SEMI_AXIS_UNAVAILABLE),
            orientation_deg=opt(orientation, C.ORIENTATION_LSB_DEG, C.ORIENTATION_UNAVAILABLE),
            transmission=d.get("transmission", "unavailable"),
            speed_mps=opt(d.get("speed"), C.SPEED_LSB_MPS, C.SPEED_UNAVAILABLE),
            heading_deg=opt(d.get("heading"), C.HEADING_LSB_DEG, C.HEADING_UNAVAILABLE),
            steering_wheel_deg=opt(d.get("angle"), C.STEER_WHEEL_LSB_DEG, C.STEER_WHEEL_UNAVAILABLE),
            accel_long_mps2=opt(accel.get("long"), C.ACCEL_LSB_MPS2, C.ACCEL_UNAVAILABLE),
            accel_lat_mps2=opt(accel.get("lat"), C.ACCEL_LSB_MPS2, C.ACCEL_UNAVAILABLE),
            accel_vert_g=opt(accel.get("vert"), C.VERT_ACCEL_LSB_G, C.VERT_ACCEL_UNAVAILABLE),
            yaw_rate_dps=(accel.get("yaw") or 0) * C.YAW_RATE_LSB_DPS,
            wheel_brakes=asn1_to_bits(brakes.get("wheelBrakes"), C.WHEEL_BRAKE_BITS),
            traction=brakes.get("traction", "unavailable"),
            abs=brakes.get("abs", "unavailable"),
            scs=brakes.get("scs", "unavailable"),
            brake_boost=brakes.get("brakeBoost", "unavailable"),
            aux_brakes=brakes.get("auxBrakes", "unavailable"),
            width_m=None if not width_cm else width_cm / 100.0,
            length_m=None if not length_cm else length_cm / 100.0,
        )


# ----------------------------------------------------------------------------
# Part II-0 VehicleSafetyExtensions
# ----------------------------------------------------------------------------

@dataclass
class PathHistoryPoint:
    """One breadcrumb, expressed as an offset from the BSM's current position."""
    lat_offset_deg: float
    lon_offset_deg: float
    elev_offset_m: Optional[float]
    time_offset_s: float

    def to_asn1_dict(self) -> Dict[str, Any]:
        def ll(v):
            return _clamp(int(round(v / C.LATLON_LSB_DEG)), C.OFFSET_LL_B18_MIN, C.OFFSET_LL_B18_MAX)

        if self.elev_offset_m is None:
            elev = C.VERT_OFFSET_B12_UNAVAILABLE
        else:
            elev = _clamp(int(round(self.elev_offset_m / C.ELEV_LSB_M)), C.VERT_OFFSET_B12_MIN, C.VERT_OFFSET_B12_MAX)
        t = int(round(self.time_offset_s / C.TIME_OFFSET_LSB_S))
        t = C.TIME_OFFSET_UNAVAILABLE if t > C.TIME_OFFSET_MAX else max(t, C.TIME_OFFSET_MIN)
        return {"latOffset": ll(self.lat_offset_deg), "lonOffset": ll(self.lon_offset_deg),
                "elevationOffset": elev, "timeOffset": t}

    @classmethod
    def from_asn1_dict(cls, d: Dict[str, Any]) -> "PathHistoryPoint":
        elev = d.get("elevationOffset")
        t = d.get("timeOffset", C.TIME_OFFSET_UNAVAILABLE)
        return cls(
            lat_offset_deg=d["latOffset"] * C.LATLON_LSB_DEG,
            lon_offset_deg=d["lonOffset"] * C.LATLON_LSB_DEG,
            elev_offset_m=None if elev in (None, C.VERT_OFFSET_B12_UNAVAILABLE) else elev * C.ELEV_LSB_M,
            time_offset_s=t * C.TIME_OFFSET_LSB_S,
        )


@dataclass
class VehicleSafetyExt:
    events: Optional[FrozenSet[str]] = None
    path_history: Optional[List[PathHistoryPoint]] = None
    # radius None means "straight" (RadiusOfCurvature 32767). Sign: right turn
    # positive, matching the J2735 yaw-rate convention used in accelSet.yaw.
    path_prediction_radius_m: Optional[float] = None
    path_prediction_confidence_pct: Optional[float] = None
    lights: Optional[FrozenSet[str]] = None

    def to_asn1_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if self.events is not None:
            out["events"] = bits_to_asn1(self.events, C.VEHICLE_EVENT_BITS, 13)
        if self.path_history:
            pts = self.path_history[: C.PATH_HISTORY_MAX_POINTS]
            out["pathHistory"] = {"crumbData": [p.to_asn1_dict() for p in pts]}
        if self.path_prediction_confidence_pct is not None:
            if self.path_prediction_radius_m is None:
                radius = C.RADIUS_STRAIGHT
            else:
                radius = _clamp(int(round(self.path_prediction_radius_m / C.RADIUS_LSB_M)), C.RADIUS_MIN, C.RADIUS_MAX)
            conf = _clamp(int(round(self.path_prediction_confidence_pct / C.CONFIDENCE_LSB_PCT)), 0, C.CONFIDENCE_MAX)
            out["pathPrediction"] = {"radiusOfCurve": radius, "confidence": conf}
        if self.lights is not None:
            out["lights"] = bits_to_asn1(self.lights, C.EXTERIOR_LIGHT_BITS, 9)
        return out

    @classmethod
    def from_asn1_dict(cls, d: Dict[str, Any]) -> "VehicleSafetyExt":
        ph = d.get("pathHistory")
        pp = d.get("pathPrediction")
        radius = None
        conf = None
        if pp:
            r = pp.get("radiusOfCurve", C.RADIUS_STRAIGHT)
            radius = None if r == C.RADIUS_STRAIGHT else r * C.RADIUS_LSB_M
            conf = pp.get("confidence", 0) * C.CONFIDENCE_LSB_PCT
        return cls(
            events=asn1_to_bits(d["events"], C.VEHICLE_EVENT_BITS) if "events" in d else None,
            path_history=[PathHistoryPoint.from_asn1_dict(p) for p in ph.get("crumbData", [])] if ph else None,
            path_prediction_radius_m=radius,
            path_prediction_confidence_pct=conf,
            lights=asn1_to_bits(d["lights"], C.EXTERIOR_LIGHT_BITS) if "lights" in d else None,
        )


# ----------------------------------------------------------------------------
# Part II-1 SpecialVehicleExtensions / EmergencyDetails
# ----------------------------------------------------------------------------

@dataclass
class EmergencyDetails:
    siren_use: str = "unavailable"
    lights_use: str = "unavailable"
    multi: str = "unavailable"
    ssp_rights: int = 0
    response_type: Optional[str] = None

    def to_asn1_dict(self) -> Dict[str, Any]:
        out = {"sspRights": self.ssp_rights, "sirenUse": self.siren_use,
               "lightsUse": self.lights_use, "multi": self.multi}
        if self.response_type is not None:
            out["responseType"] = self.response_type
        return out

    @classmethod
    def from_asn1_dict(cls, d: Dict[str, Any]) -> "EmergencyDetails":
        return cls(siren_use=d.get("sirenUse", "unavailable"), lights_use=d.get("lightsUse", "unavailable"),
                   multi=d.get("multi", "unavailable"), ssp_rights=d.get("sspRights", 0),
                   response_type=d.get("responseType"))


@dataclass
class SpecialVehicleExt:
    vehicle_alerts: Optional[EmergencyDetails] = None

    def to_asn1_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if self.vehicle_alerts is not None:
            out["vehicleAlerts"] = self.vehicle_alerts.to_asn1_dict()
        return out

    @classmethod
    def from_asn1_dict(cls, d: Dict[str, Any]) -> "SpecialVehicleExt":
        va = d.get("vehicleAlerts")
        return cls(vehicle_alerts=EmergencyDetails.from_asn1_dict(va) if va else None)


# ----------------------------------------------------------------------------
# Part II-2 SupplementalVehicleExtensions
# ----------------------------------------------------------------------------

@dataclass
class SupplementalVehicleExt:
    classification: Optional[int] = None    # BasicVehicleClass
    key_type: Optional[int] = None           # classDetails.keyType (BasicVehicleClass)
    role: Optional[str] = None               # classDetails.role (BasicVehicleRole)

    def to_asn1_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if self.classification is not None:
            out["classification"] = int(self.classification)
        details: Dict[str, Any] = {}
        if self.key_type is not None:
            details["keyType"] = int(self.key_type)
        if self.role is not None:
            details["role"] = self.role
        if details:
            out["classDetails"] = details
        return out

    @classmethod
    def from_asn1_dict(cls, d: Dict[str, Any]) -> "SupplementalVehicleExt":
        details = d.get("classDetails") or {}
        return cls(classification=d.get("classification"), key_type=details.get("keyType"),
                   role=details.get("role"))


# ----------------------------------------------------------------------------
# BasicSafetyMessage
# ----------------------------------------------------------------------------

@dataclass
class Bsm:
    core: BsmCore
    safety_ext: Optional[VehicleSafetyExt] = None
    special_ext: Optional[SpecialVehicleExt] = None
    supplemental_ext: Optional[SupplementalVehicleExt] = None
    # Part II entries with IDs this model does not interpret, kept raw.
    unknown_part2: List[Tuple[int, Any]] = field(default_factory=list)

    # -- semantic accessors used by the tracker/policy -------------------------
    @property
    def alerts(self) -> Optional[EmergencyDetails]:
        return self.special_ext.vehicle_alerts if self.special_ext else None

    @property
    def role(self) -> Optional[str]:
        return self.supplemental_ext.role if self.supplemental_ext else None

    @property
    def vehicle_class(self) -> Optional[int]:
        if not self.supplemental_ext:
            return None
        if self.supplemental_ext.key_type is not None:
            return self.supplemental_ext.key_type
        return self.supplemental_ext.classification

    @property
    def siren_on(self) -> bool:
        return bool(self.alerts and self.alerts.siren_use == "inUse")

    @property
    def lightbar_on(self) -> bool:
        return bool(self.alerts and self.alerts.lights_use == "inUse")

    @property
    def caution_lights_on(self) -> bool:
        return bool(self.alerts and self.alerts.lights_use in C.CAUTION_LIGHTBAR)

    @property
    def is_emergency_vehicle(self) -> bool:
        return (self.role in C.ERV_ROLES) or C.is_emergency_class(self.vehicle_class)

    @property
    def is_move_over_vehicle(self) -> bool:
        return self.is_emergency_vehicle or self.role in C.MOVE_OVER_ROLES

    @property
    def is_active_erv(self) -> bool:
        """Authorized emergency vehicle with siren and/or emergency lightbar in use."""
        return self.is_emergency_vehicle and (self.siren_on or self.lightbar_on)

    @property
    def multi_vehicle(self) -> bool:
        return bool(self.alerts and self.alerts.multi == "multiVehicle")

    @property
    def declared_stationary(self) -> bool:
        return bool(self.alerts and self.alerts.response_type == "stationary")

    # -- asn1 ---------------------------------------------------------------------
    def to_asn1_dict(self) -> Dict[str, Any]:
        """BasicSafetyMessage value; partII-Value entries are nested dicts."""
        out: Dict[str, Any] = {"coreData": self.core.to_asn1_dict()}
        part2 = []
        if self.safety_ext is not None:
            part2.append({"partII-Id": C.PARTII_VEHICLE_SAFETY, "partII-Value": self.safety_ext.to_asn1_dict()})
        if self.special_ext is not None:
            part2.append({"partII-Id": C.PARTII_SPECIAL_VEHICLE, "partII-Value": self.special_ext.to_asn1_dict()})
        if self.supplemental_ext is not None:
            part2.append({"partII-Id": C.PARTII_SUPPLEMENTAL, "partII-Value": self.supplemental_ext.to_asn1_dict()})
        for pid, raw in self.unknown_part2:
            part2.append({"partII-Id": pid, "partII-Value": raw})
        if part2:
            if len(part2) > 8:
                raise ValueError("BSM partII is SIZE(1..8)")
            out["partII"] = part2
        return out

    @classmethod
    def from_asn1_dict(cls, d: Dict[str, Any]) -> "Bsm":
        bsm = cls(core=BsmCore.from_asn1_dict(d["coreData"]))
        for item in d.get("partII", []) or []:
            pid = item["partII-Id"]
            val = item["partII-Value"]
            if isinstance(val, (bytes, bytearray)):
                bsm.unknown_part2.append((pid, bytes(val)))
            elif pid == C.PARTII_VEHICLE_SAFETY:
                bsm.safety_ext = VehicleSafetyExt.from_asn1_dict(val)
            elif pid == C.PARTII_SPECIAL_VEHICLE:
                bsm.special_ext = SpecialVehicleExt.from_asn1_dict(val)
            elif pid == C.PARTII_SUPPLEMENTAL:
                bsm.supplemental_ext = SupplementalVehicleExt.from_asn1_dict(val)
            else:
                bsm.unknown_part2.append((pid, val))
        return bsm

    def summary(self) -> Dict[str, Any]:
        c = self.core
        a = self.alerts
        return {
            "id": c.temp_id.hex(), "msgCnt": c.msg_cnt, "secMark": c.sec_mark_ms,
            "lat": c.lat_deg, "lon": c.lon_deg, "speed": c.speed_mps, "heading": c.heading_deg,
            "role": self.role, "class": self.vehicle_class,
            "siren": a.siren_use if a else None, "lights": a.lights_use if a else None,
            "multi": a.multi if a else None, "responseType": a.response_type if a else None,
            "ph_points": len(self.safety_ext.path_history) if self.safety_ext and self.safety_ext.path_history else 0,
        }
