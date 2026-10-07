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
    def decode_part_ii(
        part_ii
    ):
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

    def __init__(
        self,
        bind_address: str,
        port: int,
        decoder: BSMDecoder,
    ):

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

        self._socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM,
        )

        self._socket.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1,
        )

        self._socket.bind(
            (
                self.bind_address,
                self.port,
            )
        )

        self._socket.settimeout(0.5)

        self._running = True

        self._thread = threading.Thread(
            target=self._receive_loop,
            daemon=True,
        )

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
                print(bsm)

                if bsm is None:
                    continue

                with self._lock:
                    self._latest[bsm.sender_id] = bsm
            except Exception as exc:
                print(
                    f"[BSM] Decode error from "
                    f"{address}: {exc}"
                )

    def get_fresh_BSMs(
        self,
        max_age_s: float,
    ) -> List[BSM]:

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
# ERVAssessment
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

    def __init__(
        self,
        world: carla.World,
        ego_vehicle: carla.Vehicle,
        coordinate_converter: CoordinateConverter,
    ):
        self.world = world
        self.ego = ego_vehicle

        self.converter = coordinate_converter

    def assess(
        self,
        bsm: BSM,
    ) -> Optional[ERVAssessment]:

        # Is this an ERV?
        if not bsm.is_erv:
            return None

        # Get locations of vehicles
        ego_location = self.ego.get_location()
        erv_location = self.converter.bsm_to_carla(bsm)

        # Distance calculations
        dx = ego_location.x - erv_location.x
        dy = ego_location.y - erv_location.y
        distance = magnitude_2d(
            dx,
            dy,
        )

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
        direction_alignment = ( erv_heading_x * erv_to_ego_x + erv_heading_y * erv_to_ego_y ) 
        approaching = ( direction_alignment > 0.5 )



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



# ===============================================
# Vehicle Controller
# ===============================================



# ===============================================
# Spawning/Attaching to Vehicle
# ===============================================



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

    decoder = BSMDecoder()

    bsm_receiver = BSMReceiver(
        bind_address=(
            config.bsm_bind_address
        ),
        port=config.bsm_port,
        decoder=decoder,
    )

    bsm_receiver.start()

    while(1):
        x=1

if __name__ == "__main__":
    main()