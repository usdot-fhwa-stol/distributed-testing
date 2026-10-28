"""CARLA <-> WGS84 conversion and heading conventions.

Two CARLA georeference behaviours exist in the wild:

* 0.9.x and the 0.10.0 release: LibCarla's GeoLocation::Transform, a
  spherical Mercator scaled at the origin latitude (x -> east, y -> south).
  ``CarlaGeoRef`` reproduces it exactly and adds the inverse CARLA lacks.
* Newer ue5-dev builds: a GeoProjection chosen from the OpenDRIVE
  <geoReference> proj string (Transverse Mercator by default, also UTM,
  Web Mercator, Lambert Conformal Conic), with no inverse in the Python API.

``CarlaGeoRef.from_carla_map`` measures the analytic model against the map's
own ``transform_to_geolocation`` over a +/-2 km grid. If it matches (< 5 cm)
the fast analytic path is used. Otherwise it switches to "carla-native":
forward conversion calls CARLA directly and the inverse is solved by a
fixed-point iteration that uses the analytic model as its local Jacobian
(converges to sub-millimetre in a few steps because both projections are
locally conformal with near-identical scale). Either way, lat/lon from a BSM
lands on the same CARLA x/y the sender used.

Headings:
  * CARLA yaw: degrees, 0 = +x, increasing clockwise when viewed from above
    (UE is left-handed with z up).
  * J2735 heading: degrees clockwise from true north.
  -> heading = yaw + 90 (exact for the Mercator model; for other projections
     grid convergence adds a small offset, see ``heading_offset_deg``)
"""

from __future__ import annotations

import logging
import math
from typing import Callable, Optional, Tuple

log = logging.getLogger(__name__)

EARTH_RADIUS_EQUA = 6378137.0

Forward = Callable[[float, float, float], Tuple[float, float, float]]


def _lat_to_scale(lat_deg: float) -> float:
    return math.cos(math.radians(lat_deg))


def _latlon_to_mercator(lat: float, lon: float, scale: float) -> Tuple[float, float]:
    mx = scale * math.radians(lon) * EARTH_RADIUS_EQUA
    my = scale * EARTH_RADIUS_EQUA * math.log(math.tan((90.0 + lat) * math.pi / 360.0))
    return mx, my


def _mercator_to_latlon(mx: float, my: float, scale: float) -> Tuple[float, float]:
    lon = mx * 180.0 / (math.pi * EARTH_RADIUS_EQUA * scale)
    lat = 360.0 * math.atan(math.exp(my / (EARTH_RADIUS_EQUA * scale))) / math.pi - 90.0
    return lat, lon


class CarlaGeoRef:
    def __init__(self, lat0: float, lon0: float, alt0: float = 0.0, forward: Optional[Forward] = None):
        self.lat0 = lat0
        self.lon0 = lon0
        self.alt0 = alt0
        self._scale = _lat_to_scale(lat0)
        self._mx0, self._my0 = _latlon_to_mercator(lat0, lon0, self._scale)
        self._forward = forward
        self.model = "carla-native" if forward else "mercator"
        self.model_error_m = 0.0
        self.heading_offset_deg = 0.0   # J2735 heading - (yaw + 90) at the origin

    # -- construction from a live map ---------------------------------------------
    @classmethod
    def from_carla_map(cls, carla_map, tol_m: float = 0.05, span_m: float = 2000.0) -> "CarlaGeoRef":
        import carla

        def fwd(x: float, y: float, z: float):
            g = carla_map.transform_to_geolocation(carla.Location(x, y, z))
            return g.latitude, g.longitude, g.altitude

        return cls.from_forward(fwd, tol_m, span_m)

    @classmethod
    def from_forward(cls, fwd: Forward, tol_m: float = 0.05, span_m: float = 2000.0) -> "CarlaGeoRef":
        lat0, lon0, alt0 = fwd(0.0, 0.0, 0.0)
        ref = cls(lat0, lon0, alt0)
        err = ref.max_error_vs(fwd, span_m)
        if err > tol_m:
            ref._forward = fwd
            ref.model = "carla-native"
            log.info("map georeference is not the legacy Mercator (model error %.2f m over +/-%.0f m); "
                     "using CARLA's projection with iterative inverse", err, span_m)
        ref.model_error_m = err
        # grid convergence: bearing of +y(south) axis vs true south
        la, lo, _ = fwd(0.0, -100.0, 0.0)
        north = math.degrees(math.atan2((lo - lon0) * math.cos(math.radians(lat0)), la - lat0))
        ref.heading_offset_deg = (north + 180.0) % 360.0 - 180.0
        if ref.model == "mercator":
            ref.heading_offset_deg = 0.0
        return ref

    # -- conversions ----------------------------------------------------------------
    def _analytic_to_geo(self, x: float, y: float, z: float) -> Tuple[float, float, float]:
        lat, lon = _mercator_to_latlon(self._mx0 + x, self._my0 - y, self._scale)
        return lat, lon, self.alt0 + z

    def _analytic_to_local(self, lat: float, lon: float) -> Tuple[float, float]:
        mx, my = _latlon_to_mercator(lat, lon, self._scale)
        return mx - self._mx0, -(my - self._my0)

    def to_geo(self, x: float, y: float, z: float = 0.0) -> Tuple[float, float, float]:
        if self._forward is not None:
            return self._forward(x, y, z)
        return self._analytic_to_geo(x, y, z)

    def to_local(self, lat: float, lon: float, alt: Optional[float] = None) -> Tuple[float, float, float]:
        z = 0.0 if alt is None else alt - self.alt0
        tx, ty = self._analytic_to_local(lat, lon)
        if self._forward is None:
            return tx, ty, z
        x, y = tx, ty
        for _ in range(8):
            la, lo, _ = self._forward(x, y, 0.0)
            ax, ay = self._analytic_to_local(la, lo)
            dx, dy = tx - ax, ty - ay
            x += dx
            y += dy
            if dx * dx + dy * dy < 1e-8:
                break
        return x, y, z

    def max_error_vs(self, fwd: Forward, span_m: float = 2000.0) -> float:
        """Max horizontal error (m) of the analytic inverse applied to ``fwd`` output."""
        worst = 0.0
        for x in (-span_m, 0.0, span_m):
            for y in (-span_m, 0.0, span_m):
                la, lo, _ = fwd(x, y, 0.0)
                lx, ly = self._analytic_to_local(la, lo)
                worst = max(worst, math.hypot(lx - x, ly - y))
        return worst

    def self_check(self, carla_map, span_m: float = 2000.0) -> float:
        """Round-trip error (m) of to_local(CARLA forward) over a grid; ~0 when healthy."""
        import carla
        worst = 0.0
        for x in (-span_m, 0.0, span_m):
            for y in (-span_m, 0.0, span_m):
                g = carla_map.transform_to_geolocation(carla.Location(x, y, 0.0))
                lx, ly, _ = self.to_local(g.latitude, g.longitude, g.altitude)
                worst = max(worst, math.hypot(lx - x, ly - y))
        return worst

    # -- headings -------------------------------------------------------------------
    def yaw_to_heading(self, yaw_deg: float) -> float:
        return (yaw_deg + 90.0 + self.heading_offset_deg) % 360.0

    def heading_to_yaw(self, heading_deg: float) -> float:
        return wrap180(heading_deg - 90.0 - self.heading_offset_deg)


def yaw_to_heading(yaw_deg: float) -> float:
    return (yaw_deg + 90.0) % 360.0


def heading_to_yaw(heading_deg: float) -> float:
    return wrap180(heading_deg - 90.0)


def wrap180(a: float) -> float:
    a = math.fmod(a + 180.0, 360.0)
    if a < 0:
        a += 360.0
    return a - 180.0


def angle_diff(a: float, b: float) -> float:
    """Absolute smallest difference between two angles in degrees, 0..180."""
    return abs(wrap180(a - b))


def local_meters_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance (m); used for sanity checks only."""
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
