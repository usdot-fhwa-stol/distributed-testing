"""
Receive live SAE J3224 SDSM (Sensor Data Sharing Message) UDP streams and
render VRU bounding boxes in CARLA.

Coordinate modes:

1. georef (default)
   Uses the loaded CARLA map's OpenDRIVE geoReference to convert SDSM WGS-84
   latitude/longitude coordinates into CARLA coordinates.

2. calibrated
   Uses one known geographic point and its corresponding CARLA X/Y position.
   Use this for custom CARLA maps without a valid geoReference.

Examples:

    # Use the CARLA map's built-in georeference.
    python sdsm_renderer.py --coordinate-mode georef

    # Use a manually calibrated map origin.
    python sdsm_renderer.py \
      --coordinate-mode calibrated \
      --calibration-lat 42.3005934 \
      --calibration-lon -83.6992832 \
      --calibration-x 54.4 \
      --calibration-y -37.9 \
      --calibration-yaw 0

    # If SDSM offsetY is opposite of the expected CARLA/map direction.
    python sdsm_renderer.py --coordinate-mode georef --invert-sdsm-y
"""

import argparse
import math
import os
import socket
from dataclasses import dataclass
from typing import Any, Literal, Optional

import xml.etree.ElementTree as ET
from pathlib import Path

import carla
import SDSMDecoder


EARTH_RADIUS_M = 6_378_137.0


def get_georeference_from_local_xodr(map_name="Town10HD_Opt"):
    clean_map_name = map_name.split('/')[-1]
    
    xodr_path = Path(f"~/carlaCache/0.10.0/Carla/Maps/OpenDrive/{clean_map_name}.xodr").expanduser()
    print(f"Looking for XODR file at: {xodr_path}")
    
    if not xodr_path.exists():
        print(f"XODR file not found at: {xodr_path}")
        return None

    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
        header = root.find('header')
        if header is not None:
            geo_ref = header.find('geoReference')
            if geo_ref is not None and geo_ref.text:
                return geo_ref.text.strip()
    except Exception as e:
        print(f"Error parsing XODR file: {e}")
        
    return None

@dataclass(frozen=True)
class SdsmAxisConvention:
    x_axis: Literal["east", "north"] = "east"
    y_axis: Literal["east", "north"] = "north"
    x_sign: float = 1.0
    y_sign: float = 1.0

    def offsets_to_enu(
        self,
        offset_x: float,
        offset_y: float,
    ) -> tuple[float, float]:
        adjusted_x = offset_x * self.x_sign
        adjusted_y = offset_y * self.y_sign

        east_m = 0.0
        north_m = 0.0

        if self.x_axis == "east":
            east_m += adjusted_x
        else:
            north_m += adjusted_x

        if self.y_axis == "east":
            east_m += adjusted_y
        else:
            north_m += adjusted_y

        return east_m, north_m


@dataclass
class CoordinateMapper:
    """
    Convert SDSM reference coordinates and object offsets into CARLA locations.

    In georef mode, CARLA map OpenDRIVE geoReference metadata is used.

    In calibrated mode, a known latitude/longitude and CARLA X/Y correspondence
    is used as the local origin.
    """

    carla_map: carla.Map
    mode: Literal["georef", "calibrated"]
    axis_convention: SdsmAxisConvention
    calibration_latitude: Optional[float] = None
    calibration_longitude: Optional[float] = None
    calibration_carla_x: Optional[float] = None
    calibration_carla_y: Optional[float] = None
    calibration_yaw_deg: float = 0.0
    calibration_scale: float = 1.0

    def __post_init__(self) -> None:
        if self.mode != "calibrated":
            return

        required_values = (
            self.calibration_latitude,
            self.calibration_longitude,
            self.calibration_carla_x,
            self.calibration_carla_y,
        )

        if any(value is None for value in required_values):
            raise ValueError(
                "Calibrated mode requires all of the following arguments: "
                "--calibration-lat, --calibration-lon, --calibration-x, "
                "--calibration-y."
            )

    @staticmethod
    def enu_to_geodetic(
        latitude: float,
        longitude: float,
        east_m: float,
        north_m: float,
    ) -> tuple[float, float]:
        """
        Approximate a nearby local ENU position as latitude and longitude.
        """
        latitude_rad = math.radians(latitude)

        delta_lat_rad = north_m / EARTH_RADIUS_M
        delta_lon_rad = east_m / (
            EARTH_RADIUS_M * max(math.cos(latitude_rad), 1e-12)
        )

        return (
            latitude + math.degrees(delta_lat_rad),
            longitude + math.degrees(delta_lon_rad),
        )

    @staticmethod
    def geodetic_delta_to_enu(
        origin_latitude: float,
        origin_longitude: float,
        latitude: float,
        longitude: float,
    ) -> tuple[float, float]:
        """Approximate east/north meters between two nearby geographic points."""
        latitude_delta_rad = math.radians(latitude - origin_latitude)
        longitude_delta_rad = math.radians(longitude - origin_longitude)
        origin_latitude_rad = math.radians(origin_latitude)

        north_m = latitude_delta_rad * EARTH_RADIUS_M
        east_m = (
            longitude_delta_rad
            * EARTH_RADIUS_M
            * math.cos(origin_latitude_rad)
        )

        return east_m, north_m

    def sdsm_to_carla(
        self,
        reference_latitude: float,
        reference_longitude: float,
        offset_x: float,
        offset_y: float,
        altitude: float = 0.0,
    ) -> carla.Location:
        """
        Convert an SDSM reference position plus local object offsets to CARLA.
        """
        east_m, north_m = self.axis_convention.offsets_to_enu(
            offset_x,
            offset_y,
        )

        if self.mode == "georef":
            latitude, longitude = self.enu_to_geodetic(
                latitude=reference_latitude,
                longitude=reference_longitude,
                east_m=east_m,
                north_m=north_m,
            )

            geo_location = carla.GeoLocation(
                latitude=latitude,
                longitude=longitude,
                altitude=altitude,
            )

            return self.carla_map.geolocation_to_transform(
                geo_location
            ).location

        return self.calibrated_to_carla(
            reference_latitude=reference_latitude,
            reference_longitude=reference_longitude,
            east_m=east_m,
            north_m=north_m,
            altitude=altitude,
        )

    def calibrated_to_carla(
        self,
        reference_latitude: float,
        reference_longitude: float,
        east_m: float,
        north_m: float,
        altitude: float,
    ) -> carla.Location:
        """
        Use a manually configured reference point to calculate CARLA X/Y.
        """
        assert self.calibration_latitude is not None
        assert self.calibration_longitude is not None
        assert self.calibration_carla_x is not None
        assert self.calibration_carla_y is not None

        reference_east_m, reference_north_m = self.geodetic_delta_to_enu(
            origin_latitude=self.calibration_latitude,
            origin_longitude=self.calibration_longitude,
            latitude=reference_latitude,
            longitude=reference_longitude,
        )

        total_east_m = reference_east_m + east_m
        total_north_m = reference_north_m + north_m

        yaw_rad = math.radians(self.calibration_yaw_deg)
        cos_yaw = math.cos(yaw_rad)
        sin_yaw = math.sin(yaw_rad)

        carla_x = self.calibration_carla_x + self.calibration_scale * (
            total_east_m * cos_yaw - total_north_m * sin_yaw
        )
        carla_y = self.calibration_carla_y + self.calibration_scale * (
            total_east_m * sin_yaw + total_north_m * cos_yaw
        )

        return carla.Location(
            x=carla_x,
            y=carla_y,
            z=altitude,
        )


def get_reference_altitude(ref_pos: dict[str, Any]) -> float:
    for key in ("altitude", "elevation", "elev"):
        value = ref_pos.get(key)

        if value is None:
            continue

        try:
            return float(value)
        except (TypeError, ValueError):
            continue

    return 0.0


def draw_sdsm(
    world: carla.World,
    sdsm_json: dict[str, Any],
    coordinate_mapper: CoordinateMapper,
    draw_lifetime: float,
    z_offset: float,
    box_half_width: float,
    box_half_length: float,
    box_half_height: float,
    debug_opts: argparse.Namespace,
) -> None:
    """Render all VRU objects from a decoded SDSM message in CARLA."""
    ref_pos = sdsm_json.get("refPos")

    if not isinstance(ref_pos, dict):
        print(f"SDSM {sdsm_json.get('msgCnt')} has no usable refPos.")
        return

    try:
        reference_latitude = float(ref_pos["lat"])
        reference_longitude = float(ref_pos["long"])
    except (KeyError, TypeError, ValueError) as error:
        print(
            f"SDSM {sdsm_json.get('msgCnt')} has invalid reference coordinates: "
            f"{error}"
        )
        return

    reference_altitude = get_reference_altitude(ref_pos)
    vru_count = 0

    for object_index, obj in enumerate(sdsm_json.get("objects", [])):
        if not isinstance(obj, dict):
            continue

        common = obj.get("detObjCommon", {})

        if not isinstance(common, dict) or common.get("objType") != "vru":
            continue

        position = common.get("pos", {})

        if not isinstance(position, dict):
            print(
                f"SDSM {sdsm_json.get('msgCnt')}, object {object_index}: "
                "missing position."
            )
            continue

        try:
            offset_x = float(position.get("offsetX", 0.0))
            offset_y = float(position.get("offsetY", 0.0))
            offset_z = float(position.get("offsetZ", 0.0))
        except (TypeError, ValueError) as error:
            print(
                f"SDSM {sdsm_json.get('msgCnt')}, object {object_index}: "
                f"invalid offset value: {error}"
            )
            continue

        location = coordinate_mapper.sdsm_to_carla(
            reference_latitude=reference_latitude,
            reference_longitude=reference_longitude,
            offset_x=offset_x,
            offset_y=offset_y,
            altitude=reference_altitude + offset_z + z_offset,
        )

        box_center = carla.Location(
            x=location.x,
            y=location.y,
            z=location.z + box_half_height,
        )

        vru_box = carla.BoundingBox(
            box_center,
            carla.Vector3D(
                x=box_half_length,
                y=box_half_width,
                z=box_half_height,
            ),
        )

        world.debug.draw_box(
            box=vru_box,
            rotation=carla.Rotation(),
            thickness=0.15,
            color=carla.Color(r=255, g=0, b=0),
            life_time=draw_lifetime,
            persistent_lines=False,
        )

        if debug_opts.debug_vru_str:
            world.debug.draw_string(
                location=carla.Location(
                    x=location.x,
                    y=location.y,
                    z=location.z + (box_half_height * 2.0) + 0.5,
                ),
                text=f"[VRU {object_index}]",
                draw_shadow=False,
                color=carla.Color(r=255, g=0, b=0),
                life_time=draw_lifetime,
                persistent_lines=False,
            )

        if debug_opts.debug_coords:
            print(f"SDSM #{sdsm_json.get('msgCnt')}, VRU object {object_index}")
            print(
                "  Reference WGS-84: "
                f"lat={reference_latitude:.8f}, "
                f"lon={reference_longitude:.8f}, "
                f"alt={reference_altitude:.2f}"
            )
            print(
                "  Object offsets: "
                f"x={offset_x:.2f}, y={offset_y:.2f}, z={offset_z:.2f}"
            )
            print(
                "  CARLA location: "
                f"x={location.x:.2f}, y={location.y:.2f}, z={location.z:.2f}"
            )

        vru_count += 1

    if vru_count == 0:
        print(f"No VRU objects found in SDSM {sdsm_json.get('msgCnt')}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--host",
        metavar="HOST",
        default="127.0.0.1",
        help="CARLA server host/IP address (default: 127.0.0.1).",
    )
    parser.add_argument(
        "-p",
        "--port",
        metavar="PORT",
        default=2000,
        type=int,
        help="CARLA server TCP port (default: 2000).",
    )
    parser.add_argument(
        "--udp-host",
        default=os.getenv("VUG_J3224_ADAPTER_SEND_ADDRESS", "127.0.0.1"),
        help=(
            "UDP address to bind for SDSM messages. Defaults to "
            "VUG_J3224_ADAPTER_SEND_ADDRESS or 127.0.0.1."
        ),
    )
    parser.add_argument(
        "--udp-port",
        type=int,
        default=int(os.getenv("VUG_J3224_ADAPTER_SEND_PORT", "12345")),
        help=(
            "UDP port to bind for SDSM messages. Defaults to "
            "VUG_J3224_ADAPTER_SEND_PORT or 12345."
        ),
    )

    parser.add_argument(
        "--coordinate-mode",
        choices=("georef", "calibrated"),
        default="georef",
        help=(
            "Coordinate conversion method. 'georef' uses the CARLA map's "
            "OpenDRIVE geoReference. 'calibrated' uses manual map parameters."
        ),
    )
    parser.add_argument(
        "--sdsm-x-axis",
        choices=("east", "north"),
        default="east",
        help="Direction represented by decoded SDSM offsetX (default: east).",
    )
    parser.add_argument(
        "--sdsm-y-axis",
        choices=("east", "north"),
        default="north",
        help="Direction represented by decoded SDSM offsetY (default: north).",
    )
    parser.add_argument(
        "--invert-sdsm-x",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Invert the sign of decoded SDSM offsetX.",
    )
    parser.add_argument(
        "--invert-sdsm-y",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Invert the sign of decoded SDSM offsetY.",
    )

    parser.add_argument(
        "--calibration-lat",
        type=float,
        help="Latitude of a known SDSM-to-CARLA calibration point.",
    )
    parser.add_argument(
        "--calibration-lon",
        type=float,
        help="Longitude of a known SDSM-to-CARLA calibration point.",
    )
    parser.add_argument(
        "--calibration-x",
        type=float,
        help="CARLA X value of the known calibration point.",
    )
    parser.add_argument(
        "--calibration-y",
        type=float,
        help="CARLA Y value of the known calibration point.",
    )
    parser.add_argument(
        "--calibration-yaw",
        type=float,
        default=0.0,
        help=(
            "Rotation in degrees from SDSM east/north to CARLA X/Y when using "
            "calibrated mode. Default: 0."
        ),
    )
    parser.add_argument(
        "--calibration-scale",
        type=float,
        default=1.0,
        help="Meters-to-CARLA units scale in calibrated mode. Default: 1.0.",
    )

    parser.add_argument(
        "--draw-lifetime",
        type=float,
        default=0.2,
        help="Seconds that each debug box remains visible. Default: 0.2.",
    )
    parser.add_argument(
        "--draw-z-offset",
        type=float,
        default=0.0,
        help=(
            "Additional CARLA Z offset applied to all detections. Useful if "
            "SDSM elevation is unavailable or your map is vertically offset."
        ),
    )
    parser.add_argument(
        "--box-half-width",
        type=float,
        default=0.5,
        help="Half-width of VRU debug box in meters. Default: 0.5.",
    )
    parser.add_argument(
        "--box-half-length",
        type=float,
        default=0.5,
        help="Half-length of VRU debug box in meters. Default: 0.5.",
    )
    parser.add_argument(
        "--box-half-height",
        type=float,
        default=1.0,
        help="Half-height of VRU debug box in meters. Default: 1.0.",
    )

    parser.add_argument(
        "--debug-origin",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Draw the CARLA world origin marker.",
    )
    parser.add_argument(
        "--debug-vru-str",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Draw a label over every VRU.",
    )
    parser.add_argument(
        "--debug-coords",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Print decoded and transformed coordinate details.",
    )

    args = parser.parse_args()
    sock: Optional[socket.socket] = None

    try:
        client = carla.Client(args.host, args.port)
        client.set_timeout(5.0)

        world = client.get_world()
        carla_map = world.get_map()

        axis_convention = SdsmAxisConvention(
            x_axis=args.sdsm_x_axis,
            y_axis=args.sdsm_y_axis,
            x_sign=-1.0 if args.invert_sdsm_x else 1.0,
            y_sign=-1.0 if args.invert_sdsm_y else 1.0,
        )

        coordinate_mapper = CoordinateMapper(
            carla_map=carla_map,
            mode=args.coordinate_mode,
            axis_convention=axis_convention,
            calibration_latitude=args.calibration_lat,
            calibration_longitude=args.calibration_lon,
            calibration_carla_x=args.calibration_x,
            calibration_carla_y=args.calibration_y,
            calibration_yaw_deg=args.calibration_yaw,
            calibration_scale=args.calibration_scale,
        )

        print(f"Connected to CARLA map: {carla_map.name}")
        print(f"Coordinate mode: {args.coordinate_mode}")
        print(
            "SDSM axes: "
            f"offsetX -> {args.sdsm_x_axis}, "
            f"offsetY -> {args.sdsm_y_axis}"
        )

        if args.coordinate_mode == "georef":
            print(f"CARLA map georeference: {get_georeference_from_local_xodr(carla_map.name)}")

        if args.debug_origin:
            world.debug.draw_string(
                location=carla.Location(x=0.0, y=0.0, z=2.0),
                text="[CARLA ORIGIN]",
                draw_shadow=False,
                color=carla.Color(r=0, g=255, b=0),
                life_time=0.0,
                persistent_lines=True,
            )

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((args.udp_host, args.udp_port))
        sock.settimeout(1.0)

        print(
            "Listening for UDP SDSM messages on "
            f"{args.udp_host}:{args.udp_port}..."
        )

        while True:
            try:
                data, sender = sock.recvfrom(65535)
            except socket.timeout:
                continue

            hex_data = data.hex()

            if not hex_data.startswith("0029"):
                if args.debug_coords:
                    print(
                        f"Ignoring non-SDSM UDP packet from {sender[0]}:"
                        f"{sender[1]}"
                    )
                continue

            try:
                decoded_sdsm = SDSMDecoder.sdsm_decoder(hex_data)

                if not isinstance(decoded_sdsm, dict):
                    print("SDSM decoder returned an unexpected non-dict payload.")
                    continue

                print(
                    f"Received SDSM msgCnt={decoded_sdsm.get('msgCnt')} "
                    f"from {sender[0]}:{sender[1]}"
                )

                draw_sdsm(
                    world=world,
                    sdsm_json=decoded_sdsm,
                    coordinate_mapper=coordinate_mapper,
                    draw_lifetime=args.draw_lifetime,
                    z_offset=args.draw_z_offset,
                    box_half_width=args.box_half_width,
                    box_half_length=args.box_half_length,
                    box_half_height=args.box_half_height,
                    debug_opts=args,
                )

            except Exception as error:
                print(f"Error processing SDSM packet: {error}")

    except KeyboardInterrupt:
        print("\nCancelled by user.")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}")
    finally:
        if sock is not None:
            sock.close()

        print("Done.")


if __name__ == "__main__":
    main()
