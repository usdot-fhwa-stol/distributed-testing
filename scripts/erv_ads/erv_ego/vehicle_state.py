"""Simulator-agnostic snapshot of a vehicle, in CARLA coordinates.

The BSM generator only depends on this, so it can be unit-tested and reused
for a non-CARLA source (e.g. a TENA object update or a CDA1Tenth odometry
topic) by filling the same fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet


@dataclass
class VehicleState:
    x: float
    y: float
    z: float
    yaw_deg: float                 # CARLA yaw
    speed_mps: float               # magnitude, >= 0
    accel_long_mps2: float = 0.0   # + forward
    accel_lat_mps2: float = 0.0    # + to the right
    accel_vert_g: float = 0.0
    yaw_rate_dps: float = 0.0      # + clockwise seen from above (right turn)
    steer_norm: float = 0.0        # CARLA control.steer, -1..1 (+ right)
    max_road_wheel_deg: float = 70.0
    brake: float = 0.0             # 0..1
    reverse: bool = False
    hand_brake: bool = False
    width_m: float = 2.0
    length_m: float = 4.8
    height_m: float = 1.6
    # Normalised light names: low_beam, high_beam, left_blinker, right_blinker,
    # hazard, fog, position, brake, reverse, lightbar (CARLA Special1),
    # caution (CARLA Special2)
    lights: FrozenSet[str] = field(default_factory=frozenset)
    siren: bool = False            # audio is not simulated; driven by scenario/profile
