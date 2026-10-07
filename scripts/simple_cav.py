"""
BSM-aware CARLA Vehicle Controller

Behavior:

1. Connect to CARLA
2. Spawn a defined vehicle at a specified location/heading
3. Drive forward at a target speed
4. Listen to V2X Adapter for BSMs
5. Decode BSMs using J2735
6. Identify emergency response vehicles (ERVs) using BSM data
7. Calculate:
    - distance from ego to ERV
    - whether the ERV is approaching / traveling toward ego
8. If an approaching ERV is within the configured warning distance:
    - reduce speed
    - move toward an adjacent lane
9. Once the ERV has passed:
    - return to the original lane
    - resume target speed
"""

import argparse
import math
import socket
import threading
import time
import json

import j2735_202409 as J2735
import binascii as ba

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Dict, List, Optional

import carla


# ===============================================
# Configuration
# ===============================================

@dataclass
class ControllerConfig:

    # -------------------------------------------
    # CARLA
    # -------------------------------------------
    carla_host: str = "127.0.0.1"
    carla_port: int = 2000

    vehicle_model: str = "vehicle.lincoln.mkz"
    role_name: str = "DEFAULT-M-1"

    spawn_x: float = 0.0
    spawn_y: float = 0.0
    spawn_z: float = 0.5

    spawn_yaw: float = 0.0
    spawn_pitch: float = 0.0
    spawn_roll: float = 0.0

    # -------------------------------------------
    # Vehicle behavior
    # -------------------------------------------

    target_speed_kph: float = 50.0

    # Speed while yielding to ERV
    yield_speed_kph: float = 20.0

    # -------------------------------------------
    # BSM
    # -------------------------------------------

    bsm_bind_address: str = "127.0.0.1"
    bsm_port: int = 5398

    # Maximum age of a BSM before we consider it stale
    bsm_timeout_s: float = 1.0

    # -------------------------------------------
    # ERV response
    # -------------------------------------------

    erv_response_distance_m: float = 100.0

    # Once the ERV is behind us / farther away than this,
    # we can consider returning to our lane
    erv_clear_distance_m: float = 50.0

    # Minimum amount of time than an approaching ERV condition
    # must persist before triggering the response.
    erv_confirmation_time_s: float = 0.5

    # -------------------------------------------
    # Controller
    # -------------------------------------------

    control_hz: float = 20.0

    # How far ahead we look for the lane-change target
    waypoint_lookahead_m: float = 15.0

    # Maximum steering command
    max_steer: float = 0.8

# ===============================================
# BSM Representation
# ===============================================

@dataclass
class BSM:

    """
    Normalized BSM representation.

    The decoder converts your actual BSM format into this structure.
    """

    received_time: float

    sender_id: str

    latitude: float
    longitude: float
    elevation_m: float

    speed_mps: float

    # Normalized heading in degrees
    #
    # IMPORTANT:
    # This should eventually be converted to the same convention used by the CARLA coordinate adapter
    heading_deg: float

    # True if this BSM belongs to an emergency response vehicle
    is_erv: bool
    vehicle_role: Optional[str] = None
    vehicle_classification: Optional[int] = None

    siren_use: Optional[str] = None
    lights_use: Optional[str] = None


    message_id: Optional[int] = None
    message_count: Optional[int] = None
    second_mark: Optional[int] = None

# ===============================================
# BSM Decoder
# ===============================================

class BSMDecoder:
    """
    Converts raw UDP data into the BSM class defined above.

    Uses J2735 Message frames to decode the data and convert into json
    """

    # -------------------------------------------
    # Scaling Constants
    # -------------------------------------------

    LATITUDE_SCALE = 1e-7
    LONGITUDE_SCALE = 1e-7

    HEADING_SCALE_DEG = 0.0125
    UNAVAILABLE_HEADING = 28800

    SPEED_SCALE_MPS = 0.02
    UNAVAILABLE_SPEED = 8191

    ELEVATION_SCALE_M = 0.1
    ELEVATION_OFFSET_M = -409.5
    UNAVAILABLE_ELEVATION = 4095

    def decode(self, data: bytes) -> Optional[BSM]:
        """
        Decode a single BSM Packet and convert into BSM class
        """
        decoded_bsm = J2735.MessageFrame.MessageFrame
        decoded_bsm.from_uper(data)
        bsm_json = decoded_bsm.to_json()
        bsm_dict = json.loads(bsm_json)

        return self.convert_dict(bsm_dict)

    def convert_dict(self, message: Dict[str, Any]) -> Optional[BSM]:
        """
        Convert received BSM in JSON/Dict format into BSM class
        """
        try:
            # Get Base BSM information
            message_id = message.get("messageId")
            core = message["value"]["coreData"]
            sender_id = str(core["id"])
            latitude = float(core["lat"]) * self.LATITUDE_SCALE
            longitude = float(core["long"]) * self.LONGITUDE_SCALE
            elevation_m = self.decode_elevation(core.get("elev"))
            speed_mps = self.decode_speed(core.get("speed"))
            heading_deg = self.decode_heading(core.get("heading"))
            message_count = core.get("msgCnt")
            second_mark = core.get("secMark")
            
            # Get BSM PartII information
            part_ii = message["value"].get("partII",[])
            (vehicle_role, vehicle_classification, siren_use, lights_use) = self.decode_part_ii(part_ii)
            
        except( KeyError,TypeError, ) as exc:
            print(f"[BSM] Missing required field: {exc}")

        # Determine whether BSM is from an ERV
        is_erv = self.determine_erv(
            vehicle_role = vehicle_role,
            vehicle_classification = vehicle_classification,
            siren_use = siren_use,
            lights_use = lights_use
        )

        return BSM(
            sender_id = sender_id,
            latitude = latitude,
            longitude = longitude,
            elevation_m = elevation_m,
            speed_mps = speed_mps,
            heading_deg = heading_deg,
            is_erv = is_erv,
            vehicle_role = vehicle_role,
            vehicle_classification = vehicle_classification,
            siren_use = siren_use,
            lights_use = lights_use,
            message_id = message_id,
            message_count = message_count,
            second_mark = second_mark,
            received_time = time.monotonic(),
        )

    @classmethod
    def decode_heading(self, value) -> Optional[float]:
        """
        J2735 heading resolution:
            <value> * 0.0125 degrees
        """

        if value is None:
            return None

        value = int(value)
        if value >= self.UNAVAILABLE_HEADING:
            return None

        return value * self.HEADING_SCALE_DEG

    @classmethod
    def decode_speed(self, value) -> Optional[float]:
        """
        J2735 speed resolution:
            <value> * 0.02 m/s
        """

        if value is None:
            return None

        value = int(value)
        if value >= self.UNAVAILABLE_SPEED:
            return None

        return value * self.SPEED_SCALE_MPS

    @classmethod
    def decode_elevation(self, value) -> Optional[float]:
        """
        J2735 elevation resolution
            ( <value> * 0.1 ) - 409.5
        """

        if value is None:
            return None

        value = int(value)
        if value >= self.UNAVAILABLE_ELEVATION:
            return None

        return (value * self.ELEVATION_SCALE_M) + self.ELEVATION_OFFSET_M 

    @staticmethod
    def decode_part_ii(part_ii):
        
        VEHICLE_SAFETY_EXTENSIONS = 1
        SPECIAL_VEHICLE_EXTENSIONS = 2
        vehicle_role = None
        vehicle_classification = None

        siren_use = None
        lights_use = None

        for part in part_ii:
            part_id = part.get("partII-Id")

            part_value = part.get("partII-Value", {})

            if part_id == VEHICLE_SAFETY_EXTENSIONS:
                vehicle_alerts = part_value.get("vehicleAlerts", {})
                siren_use = vehicle_alerts.get("sirenUse")
                lights_use = vehicle_alerts.get("lightsUse")
            elif part_id == SPECIAL_VEHICLE_EXTENSIONS:
                class_details = part_value.get("classDetails",{})
                vehicle_role = class_details.get("role")
                vehicle_classification = part_value.get("classification")

        return (vehicle_role, vehicle_classification, siren_use, lights_use)

    @staticmethod
    def determine_erv(vehicle_role: Optional[str], vehicle_classification: Optional[int], siren_use: Optional[str], lights_use: Optional[str]) -> bool:
        """
        Determine whether BSM represents an ERV
        """
        emergency_roles = {
            "ambulance",
            "firetruck",
            "police",
        }

        if vehicle_role and (vehicle_role in emergency_roles):
            return True

        return False

# ===============================================
# UDP BSM Receiver
# ===============================================

class BSMReceiver:
    """
    Background UDP receiver.

    The CARLA control loop will not wait for network data.
    """

    def __init__(self, bind_address: str, port: int, decoder: BSMDecoder):

        self.bind_address = bind_address
        self.port = port
        self.decoder = decoder

        self._socket = None
        self._thread = None
        self._running = False

        self._lock = threading.Lock()

        # Most recent BSM indexed by sender ID
        self._latest: Dict[str, BSM] = {}

    def start(self):

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((self.bind_address, self.port))
        self._socket.settimeout(0.5)

        self._running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()

        print(
            f"[BSM] Listening on "
            f"{self.bind_address}:{self.port}"
        )

    def stop(self):
        
        self._running = False

        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass

        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _receive_loop(self):

        while self._running:
            # Receive data from V2X Adapter
            try:
                data, address = self._socket.recvfrom(8192)
            except socket.timeout:
                continue
            except OSError:
                break

            # Decode data and format into BSM defined above
            try:
                bsm = self.decoder.decode(data)

                if bsm is None:
                    continue

                with self._lock:
                    self._latest[bsm.sender_id] = bsm
            except Exception as exc:
                print(
                    f"[BSM] Decode error from "
                    f"{address}: {exc}"
                )

    def get_fresh_BSMs(self, max_age_s: float) -> List[BSM]:

        now = time.monotonic()
        with self._lock:
            return [
                bsm for bsm in self._latest.values() if now - bsm.received_time <= max_age_s
            ]

# ===============================================
# Coordinate conversion
# ===============================================

class CoordinateConverter:
    """
    Converts BSM geographic coordinates into CARLA coordinates.
    """

    def __init__(self, world: carla.World):

        self.world = world
        self.map = world.get_map()

    def bsm_to_carla(
        self,
        bsm: BSM,
    ) -> carla.Location:
        raise NotImplementedError(
            "BSM -> CARLA Coordinate Conversion not yet implemented."
        )

# ===============================================
# Geometry Helpers
# ===============================================

def magnitude_2d(x: float, y: float) -> float:
    return math.sqrt((x*x)+(y*y))

def distance_2d(a: carla.Location, b: carla.Location) -> float:
    return magnitude_2d((a.x - b.x), (a.y - b.y))

def normalize_angle_deg(angle: float) -> float:
    return ((angle + 180.0) % 360.0) - 180.0

def heading_vector(heading_deg: float):
    angle = math.radians(heading_deg)
    return (math.cos(angle), math.sin(angle))

# ===============================================
# ERV Assessment
# ===============================================

@dataclass
class ERVAssessment:

    bsm: BSM
    distance_m: float
    approaching: bool
    closing_spped_mps: float
    relative_bearing_deg: float

class ERVDetector:
    """
    Determines wheter a BSM represents an approaching ERV
    """

    def __init__(self, world: carla.World, ego_vehicle: carla.Vehicle, coordinate_converter: CoordinateConverter):
        self.world = world
        self.ego = ego_vehicle

        self.converter = coordinate_converter

    def assess(self, bsm: BSM) -> Optional[ERVAssessment]:

        # Is this an ERV?
        if not bsm.is_erv:
            return None

        # Get locations of vehicles
        ego_location = self.ego.get_location()
        erv_location = self.converter.bsm_to_carla(bsm)

        # Distance calculations
        #   dx = ego_location.x - erv_location.x
        #   dy = ego_location.y - erv_location.y
        #   distance = magnitude_2d(dx, dy)
        distance = distance_2d(ego_location, erv_location)

        if distance < 0.001:
            return ERVAssessment(
                bsm=bsm,
                distance_m=0.0,
                approaching=True,
                closing_speed_mps=0.0,
                relative_bearing_deb=0.0,
            )

        # Determine direction (from/toward ego)
        erv_to_ego_x = dx / distance
        erv_to_ego_y = dy / distance

        erv_heading_x, erv_heading_y = heading_vector(bsm.heading_deg)

        # Dot product: 
        # +1 = directly toward ego 
        # 0 = perpendicular 
        # -1 = directly away 
        direction_alignment = ( (erv_heading_x * erv_to_ego_x) + (erv_heading_y * erv_to_ego_y) ) 
        approaching = ( direction_alignment > 0.5 )

        # Relative velocity
        ego_velocity = self.ego.get_velocity()
        ego_speed = magnitude_2d(ego_velocity.x, ego_velocity.y)

        # TODO: Refine this using road geometry and relative velocity
        erv_closing_component = bsm.speed_mps * max(0.0, direction_alignment)
        closing_speed = erv_closing_component + ego_speed

        # Relative bearing
        ego_forward = self.ego.get_transform().get_forward_vector()
        to_erv_x = erv_location.x - ego_location.x
        to_erv_y = erv_location.y - ego_location.y
        to_erv_mag = magnitude_2d(to_erv_x, to_erv_y)

        to_erv_x /= to_erv_mag
        to_erv_y /= to_erv_mag

        dot = (ego_forward.x * to_erv_x) + (ego_forward.y * to_erv_y)
        cross = (ego_forward.x * to_erv_y) - (ego_forward.y * to_erv_x)

        relative_bearing = math.degrees(math.atan2(cross,dot))

        return ERVAssessment(
            bsm=bsm,
            distance_m=distance,
            approaching=approaching,
            closing_speed_mps = closing_speed,
            relative_bearing_deg=relative_bearing
        )

# ===============================================
# Controller State Machine
# ===============================================

class ControllerState(Enum):
    
    NORMAL = auto()
    SLOWING = auto()
    MOVING_OVER = auto()
    YIELDED = auto()
    RETURNING = auto()

# ===============================================
# Lane Manager
# ===============================================

class LaneManager:
    """
    Handles CARLA waypoint/lane information

    CARLA 0.10.0's waypoint API provides get_left_lane() and get_right_lane(),
    so the controller uses those rather tahn teleporting the vehicle between lanes
    """

    def __init__(self, world: carla.World, vehicle: carla.Vehicle):
        self.world = world
        self.vehicle = vehicle
        self.map = world.get_map()

        self.original_lane_id = None
        self.original_road_id = None

        self.target_lane_id = None

    def current_waypoint(self):
        return self.map.get_waypoint(self.vehicle.get_location(), project_to_road=True, lane_type=carla.LaneType.Driving)

    def capture_original_lane(self):
        waypoint = self.current_waypoint()
        if waypoint is None:
            raise RuntimeError(
                "Ego vehicle is not currently on a driving lane"
            )
        self.original_land_id = waypoint.lane_id
        self.original_road_id = waypoint.road_id

        return waypoint

    def get_adjacent_lane(self, diration: str):
        current = self.current_waypoint()

        if current is None:
            return None

        if direction == "left":
            return current.get_left_lane()
        if direction == "right":
            return current.get_right_lane()
        raise ValueError(f"Invalid lane direction: {direction}")

    def can_move_over(self, direction: str) -> bool:
        adjacent = self.get_adjacent_lane(direction)
        if adjacent is None:
            return False

        if adjacent.lane_type != carla.LaneType.Driving:
            return False

        return True

    def set_target_lane(self, direction: str) -> bool:
        adjacent = self.get_adjacent_lane(direction)
        if adjacent is None:
            return False

        if adjacent.lane_type != carla.LaneType.Driving:
            return False

        self.target_lane_id = adjacent.lane_id

        return True

    def is_in_target_lane(self):
        if self.target_lane_id is None:
            return False

        current = self.current_waypoint()

        if current is None:
            return False

        return current.lane_id == self.target_lane_id

    def is_in_original_lane(self):
        current = self.current_waypoint()
        if current is None:
            return False

        return current.lane_id == self.original_lane_id    

# ===============================================
# Vehicle Controller
# ===============================================

class VehicleController:
    """
    Main control algorithm for ego vehicle
    """

    def __init__(self, world: carla.World, vehicle: carla.Vehicle, config: ControllerConfig):
        self.world = world
        self.vehicle = vehicle
        self.config = config

        self.lanes = LaneManager(world, vehicle)
        self.state = ControllerState.NORMAL
        self.original_waypoint = None
        self.erv_confirmation_start = None
        self.current_erv = None

    # Speed
    def speed_mps(self):
        velocity = self.vehicle.get_velocity()
        return magnitude_2d(velocity.x, velocity.y)

    def speed_kph(self):
        return self.speed_mps() * 3.6

    # Longitudinal controller
    def speed_control(self, target_speed_kph: float):
        current_speed = self.speed_kph()
        error = target_speed_kph - current_speed

        # Simple proportional controller
        # TODO: Replace with tuned PID/Ackermann controller

        throttle = max(0.0, min(0.75, error * 0.025))
        brake = 0.0
        if error < -2.0:
            brake = max(0.0, min(1.0, (-error) * 0.04))
            throttle = 0.0
        return throttle, brake

    # Steering
    def steer_to_waypoint(self, waypoint: carla.Waypoint):
        vehicle_transform = self.vehicle.get_transform()
        vehicle_yaw = vehicle_transform.rotation.yaw
        target_yaw = waypoint.transform.rotation.yaw
        yaw_error = normalize_angle_deg(target_yaw - vehicle_yaw)

        # Simple heading controller
        # TODO: Replace with tuned controller
        steer = yaw_error/45.0
        return max(-self.config.max_steer, min(self.config.max_steer, steer))

    # Vehicle Controls
    def normal_control(self):
        waypoint = self.lanes.current_waypoint()
        if waypoint is None:
            return carla.VehicleControl(throttle=0.0,brake=1.0)

        throttle, brake = self.speed_control(self.config.target_speed_kph)

        return carla.VehicleControl(
            throttle=throttle,
            brake=brake,
            steer=self.steer_to_waypoint(waypoint)
        )

    def yield_control(self):
        waypoint = self.lanes.current_waypoint()
        throttle, brake = self.speed_control(self.config.yield_speed_kph)
        steer = 0.0
        if waypoint is not None:
            steer = self.steer_to_waypoint(waypoint)

        return carla.VehicleControl(
            throttle=throttle,
            brake=brake,
            steer=steer
        )

    def move_over_control(self):
        current = self.lanes.current_waypoint()
        if current is None:
            return self.yield_control()

        # Look for waypoint in target lane
        # Using target lane's waypoint ahead of us rather than directly steering at the center
        target_lane = None
        if self.lanes.target_lane_id is not None:
            candidates = current.next(self.config.waypoint_lookahead_m)
            for waypoint in candidates:
                if waypoint.lane_id == self.lanes.target_lane_id:
                    target_lane = waypoint
                    break

        if target_lane is None:
            return self.yield_control()

        throttle, brake = self.speed_control(self.config.yield_speed_kph)
        steer = self.steer_to_waypoint(target_lane)
        return carla.VehicleControl(
            throttle=throttle,
            brake=brake,
            steer=steer
        )

    def return_control(self):
        current = self.lanes.current_waypoint()
        if current is None:
            return self.yield_control()

        target = None
        candidates = current.next(self.config.waypoint_lookahead_m)
        for waypoint in candidates:
            if waypoint.lane_id == self.lanes.original_lane_id:
                target = waypoint
                break

        if target is None:
            return self.yield_control()

        throttle, brake = self.speed_control(self.config.target_speed_kph)
        steer = self.steer_to_waypoint(target)
        return carla.VehicleControl(
            throttle=throttle,
            brake=brake,
            steer=steer
        )

    # ERV State Machine
    def update(self, assessment: Optional[ERVAssessment]):
        now = time.monotonic()

        if self.state == ControllerState.NORMAL:
            if assessment is None:
                self.erv_confirmation_start = None
                return
            if not assessment.approaching:
                self.erv_confirmation_start = None
                return
            if assessment.distance_m > self.config.erv_response_distance_m:
                self.erv_confirmation_start = None
                return
            if self.erv_confirmation_start is None:
                self.erv_confirmation_start = now
                self.current_erv = assessment.bsm.sender_id
                return
            if (now - self.erv_confirmation_start) < self.config.erv_confirmation_time_s:
                return

            # Determine whether we have an adjacent lane
            # Initially prefer right
            # TODO: Reconfigure this to match scenario or use road topology

            if self.lanes.can_move_over("right"):
                if self.lanes.set_target_lane("right"):
                    self.state = ControllerState.SLOWING
                    print("[CTRL] ERV response: SLOWING")
            else:
                # No adjacent lane available
                # For now remain in lane and slow down
                # TODO: Fix this logic
                self.state = ControllerState.SLOWING
                print("[CTRL] ERV response: SLOWING (no lane change available)")
        elif self.state == ControllerState.SLOWING:
            # Once we are sufficiently slow, move over
            if self.speed_kph() <= self.config.yield_speed_kph + 5.0:
                if self.lanes.target_lane_id is not None:
                    self.state = ControllerState.MOVING_OVER
                    print("[CTRL] ERV resposne: MOVING OVER")
                else:
                    self.state = ControllerState.YIELDED
        elif self.state == ControllerState.MOVING_OVER:
            if self.lanes.is_in_target_lane():
                self.state = ControllerState.YIELDED
                print("[CTRL] ERV response: YIELDED")
        elif self.state == ControllerState.YIELDED:
            if assessment is None:
                self.state = ControllerState.RETURNING
                print("[CTRL] ERV no longer detected: RETURNING")
                return
            # ERV is no longer approaching
            if not assessment.approaching:
                self.state = ControllerState.RETURNING
                print("[CTRL] ERV passed: RETURNING")
                return
            # Or it has moved sufficiently far away
            if assessment.distance_m > self.config.erv_clear_distance_m:
                self.state = ControllerState.RETURNING
                print("[CTRL] ERV cleared: RETURNING")
        elif self.state == ControllerState.RETURNING:
            if self.lanes.is_in_original_lane():
                self.state = ControllerState.NORMAL
                self.erv_confirmation_start = None
                self.current_erv = None
                self.lanes.target_lane_id = None
                print("[CTRL] Back in original lane: NORMAL OPERATION")

    # -------------------------------------------
    # Generate Vehicle Command
    # -------------------------------------------

    def get_control(self):
        if self.state == ControllerState.NORMAL:
            return self.normal_control()

        if self.state == ControllerState.SLOWING:
            return self.yield_control()

        if self.state == ControllerState.MOVING_OVER:
            return self.move_over_control()

        if self.state == ControllerState.YIELDED:
            return self.yield_control()

        if self.state == ControllerState.RETURNING:
            return self.return_control()

        return self.normal_control()

# ===============================================
# Spawning/Attaching to Vehicle
# ===============================================

def spawn_vehicle(world: carla.World, config: ControllerConfig):
    
    blueprint_library = world.get_blueprint_library()
    blueprint = blueprint_library.find(config.vehicle_model)
    if blueprint is None:
        raise RuntimeError(f"Vehicle blueprint not found: {config.vehicle_model}")

    if blueprint.has_attribute("role_name"):
        blueprint.set_attribute("role_name", config.role_name)

    transform = carla.Transform(
        carla.Location(x=config.spawn_x, y=config.spawn_y, z=config.spawn_z),
        carla.Rotation(pitch=config.spawn_pitch, yaw=config.spawn_yaw, roll=config.spawn_roll)
    )

    vehicle = world.try_spawn_actor(blueprint, transform)

    if vehicle is None:
        raise RuntimeError("CARLA failed to spawn vehicle. The spawn location may be occupied.")

    print(
        "[CARLA] Spawned:"
        f"  type = {vehicle.type_id}"
        f"  id = {vehicle.id}"
        f"  role_name = {config.role_name}"
        f"  location = ({config.spawn_x},{config.spawn_y},{config.spawn_z})"
        f"  yaw = {config.spawn_yaw}"
    )

    return vehicle


# ===============================================
# Main
# ===============================================

def main():
    
    # -------------------------------------------
    # Argument Parser
    # -------------------------------------------
    parser = argparse.ArgumentParser(
        description=(
            "CARLA C-ADS Controller "
            "ERV BSM Aware"
        )
    )

    # CARLA
    parser.add_argument(
        "--host",
        default="127.0.0.1",
    )
    parser.add_argument(
        "--carla-port",
        type=int,
        default=2000,
    )
    parser.add_argument(
        "--model",
        #required=True,
        help="CARLA 0.10.0 vehicle blueprint string"
    )
    parser.add_argument(
        "--role-name",
        default="DEFAULT-M-1",
    )
    parser.add_argument(
        "--x",
        type=float,
        #required=True,
    )
    parser.add_argument(
        "--y",
        type=float,
        #required=True,
    )
    parser.add_argument(
        "--z",
        type=float,
        #required=True,
    )
    parser.add_argument(
        "--yaw",
        type=float,
        #required=True,
    )

    # Driving
    parser.add_argument(
        "--speed",
        type=float,
        default=50.0,
        help="Target speed in km/h",
    )
    parser.add_argument(
        "--yield-speed",
        type=float,
        default=20.0,
        help="Yield speed in km/h"
    )

    # BSM
    parser.add_argument(
        "--bsm-port",
        type=int,
        default=5398,
    )
    parser.add_argument(
        "--bsm-bind",
        default="127.0.0.1"
    )

    # ERV
    parser.add_argument(
        "--erv-distance",
        type=float,
        default=100.0,
        help="ERV response distance in meters",
    )

    # -------------------------------------------
    # Main Control Loop
    # -------------------------------------------

    args = parser.parse_args()

    config = ControllerConfig(
        carla_host=args.host,
        carla_port=args.carla_port,

        vehicle_model=args.model,
        role_name=args.role_name,

        spawn_x=args.x,
        spawn_y=args.y,
        spawn_z=args.z,
        spawn_yaw=args.yaw,

        target_speed_kph=args.speed,
        yield_speed_kph=args.yield_speed,

        bsm_bind_address = args.bsm_bind,
        bsm_port=args.bsm_port,

        erv_response_distance_m=args.erv_distance,
    )

    # Connect to CARLA
    print(f"[CARLA] Connecting to {config.carla_host}:{config.carla_port}")
    client = carla.Client(config.carla_host, config.carla_port)
    client.set_timeout(30.0)
    world = client.get_world()
    print(f"[CARLA] Connected")
    print(f"[CARLA] Map: {world.get_map().name}")

    vehicle = None
    bsm_receiver = None

    try:
        # Spawn vehicle
        vehicle = spawn_vehicle(world,config)

        # Lane Manager
        lane_manager = LaneManager(world, vehicle)
        original_waypoint = lane_manager.capture_original_lane()
        print(
            f"[CARLA] Original lane:"
            f"  road_id = {original_waypoint.road_id}"
            f"  lane_id = {original_waypoint.lane_id}"
        )

        # Start BSM Listener
        decoder = BSMDecoder()
        bsm_receiver = BSMReceiver(
            bind_address=(
                config.bsm_bind_address
            ),
            port=config.bsm_port,
            decoder=decoder,
        )
        bsm_receiver.start()

        # Coordinate conversion
        coordinate_converter = CoordinateConverter(world)

        # ERV detector
        erv_detector = ERVDetector(world=world, ego_vehicle=vehicle, coordinate_converter=coordinate_converter)

        # Main controller
        controller = VehicleController(world=world, vehicle=vehicle, config=config)
        controller.original_waypoint = original_waypoint

        # Main loop
        period = 1.0 / config.control_hz
        print("[CTRL] Controller started")

        while(True):
            loop_start = time.monotonic()

            # Get fresh BSMs
            bsms = bsm_receiver.get_fresh_BSMs(config.bsm_timeout_s)
            
            # Assess ERVs
            assessments = []
            for bsm in bsms:
                try:
                    assessment = erv_detector.assess(bsm)
                    if assessment is not None:
                        assessments.append(assessment)
                except Exception as exc:
                    print(f"[ERV] Assessment error: {exc}")

            # Determine closest approaching ERV
            closest_erv = None
            for assessment in assessments:
                if not assessment.approaching:
                    continue

                if closest_erv is None or (assessment.distance_m < closest_erv.distance_m):
                    closest_erv = assessment

            # Update state machine
            controller.update(closest_erv)

            # Generate vehicle control
            control = controller.get_control()
            vehicle.apply_control(control)

            # Diagnostics
            if closest_erv is not None:
                print(
                    "[ERV] " 
                    f"id={closest_erv.bsm.sender_id} "
                    f"distance={closest_erv.distance_m:.1f}m "
                    f"closing={closest_erv.closing_speed_mps:.1f}m/s "
                    f"bearing={closest_erv.relative_bearing_deg:.1f}deg "
                    f"approaching={closest_erv.approaching} "
                    f"state={controller.state.name}"
                )

            # Maintain loop frequency
            elapsed = time.monotonic() = loop_start
            sleep_time = period - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n[CTRL] Interrupted")
    finally:
        print("[CTRL] Shutting down...")
        if bsm_receiver is not None:
            bsm_receiver.stop()
        if vehicle is not None:
            try:
                vehicle.destroy()
            except Exception:
                pass
        print("[CTRL] Done")

if __name__ == "__main__":
    main()