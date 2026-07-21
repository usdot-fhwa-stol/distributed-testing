"""Receive live SAE J3224 SDSM (Sensor Data Sharing Message) UDP streams and render VRU bounding boxes in CARLA."""

import argparse
import json
import math
import os
import socket
from typing import Any, Optional

import carla
import SDSMDecoder


def list_json_file() -> list[str] | None:
    """Lists available JSON files in the current working directory."""
    json_files = [file for file in os.listdir() if file.endswith(".json")]
    if not json_files:
        print("No .json files found in the current directory.")
        return None

    print("\nAvailable .json files:\n")
    for i, file in enumerate(json_files, 1):
        print(f"\t{i}. {file}")
    return json_files


def load_selected_json_file(selected_file: str) -> dict[str, Any] | None:
    """Loads and parses a specified JSON file."""
    try:
        with open(selected_file, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"Error: File not found at '{selected_file}'")
    except json.JSONDecodeError:
        print(f"Error: Unable to decode JSON from file '{selected_file}'")
    return None


def lat_lon_alt_to_xyz(
    latitude: float, longitude: float, altitude: float
) -> dict[str, float]:
    """Converts spherical Geodetic coordinates to spherical Cartesian coordinates."""
    earth_radius = 6371000.0  # Earth radius in meters (average)
    lat_rad = math.radians(latitude)
    lon_rad = math.radians(longitude)

    x = (earth_radius + altitude) * math.cos(lat_rad) * math.cos(lon_rad)
    y = (earth_radius + altitude) * math.cos(lat_rad) * math.sin(lon_rad)
    z = (earth_radius + altitude) * math.sin(lat_rad)

    return {"x": x, "y": y, "z": z}


def lat_long_to_xyz_better(
    latitude: float, longitude: float, altitude: float
) -> dict[str, float]:
    """Converts Geodetic coordinates using WGS 84 ellipsoid calculations."""
    semi_major_axis = 6378137.0  # in meters
    flattening = 1 / 298.257223563

    lat_rad = math.radians(latitude)
    lon_rad = math.radians(longitude)

    n_val = semi_major_axis / math.sqrt(
        1 - flattening * (2 - flattening) * math.sin(lat_rad) ** 2
    )

    x = (n_val + altitude) * math.cos(lat_rad) * math.cos(lon_rad)
    y = (n_val + altitude) * math.cos(lat_rad) * math.sin(lon_rad)
    z = ((1 - flattening) ** 2 * n_val + altitude) * math.sin(lat_rad)

    return {"x": x, "y": y, "z": z}


def geodetic_to_ecef(
    latitude: float, longitude: float, altitude: float
) -> dict[str, float]:
    """Converts WGS-84 Geodetic coordinates to Earth-Centered, Earth-Fixed (ECEF)."""
    a = 6378137.0  # Earth semimajor axis (m)
    b = 6356752.314245  # Earth semiminor axis (m)
    f = (a - b) / a
    e_sq = f * (2 - f)  # Square of Eccentricity

    lambdaa = math.radians(latitude)
    phi = math.radians(longitude)

    sin_lambda = math.sin(lambdaa)
    cos_lambda = math.cos(lambdaa)
    sin_phi = math.sin(phi)
    cos_phi = math.cos(phi)

    n_val = a / math.sqrt(1 - e_sq * sin_lambda * sin_lambda)

    x = (altitude + n_val) * cos_lambda * cos_phi
    y = (altitude + n_val) * cos_lambda * sin_phi
    z = (altitude + (1 - e_sq) * n_val) * sin_lambda

    return {"x": x, "y": y, "z": z}


def draw_sdsm(
    world: carla.World,
    sdsm_json: dict[str, Any],
    draw_z_height: float,
    draw_lifetime: float,
    mcity_origin: dict[str, float],
    debug_opts: argparse.Namespace,
) -> None:
    """Parses SDSM object payload and renders debug shapes inside CARLA simulator."""
    sdsm_obj_index: Optional[int] = None

    for obj_i, obj in enumerate(sdsm_json.get("objects", [])):
        if obj.get("detObjCommon", {}).get("objType") == "vru":
            sdsm_obj_index = obj_i
            break

    if sdsm_obj_index is None:
        print(f"No VRU object found in SDSM: msgCnt {sdsm_json.get('msgCnt')}")
        return

    # Dynamic calculation or hardcoded defaults
    # vru_ref_pos = geodetic_to_ecef(sdsm_json["refPos"]["lat"], sdsm_json["refPos"]["long"], 0)
    vru_ref_pos = {"x": 518558.359, "y": -4696023.893, "z": 0.0}

    x_fudge = 0.0  # 4.0
    y_fudge = 0.0  # 9.0

    # Local offset computation parameter
    # local_vru_ref_pos = {
    #     "x": (vru_ref_pos["x"] - mcity_origin["x"] + x_fudge),
    #     "y": -1 * (vru_ref_pos["y"] - mcity_origin["y"] + y_fudge),
    #     "z": (vru_ref_pos["z"] - mcity_origin["z"])
    # }
    local_vru_ref_pos = {"x": 54.403637, "y": -37.924835, "z": 0.0}

    if debug_opts.debug_vru_ref:
        world.debug.draw_string(
            carla.Location(
                x=local_vru_ref_pos["x"], y=local_vru_ref_pos["y"], z=draw_z_height
            ),
            "[R]",
            draw_shadow=False,
            color=carla.Color(r=255, g=0, b=0),
            life_time=draw_lifetime,
            persistent_lines=True,
        )

    vru_obj_common = sdsm_json["objects"][sdsm_obj_index]["detObjCommon"]
    vru_x = local_vru_ref_pos["x"] + vru_obj_common["pos"]["offsetX"]
    vru_y = local_vru_ref_pos["y"] + vru_obj_common["pos"]["offsetY"]

    if debug_opts.debug_coords:
        print(f"SDSM #: {sdsm_json.get('msgCnt')}")
        print(f"\tvru_ref_pos: {vru_ref_pos}")
        print(f"\tlocal_vru_ref_pos: {local_vru_ref_pos}")
        print(f"\tvru_x: {vru_x}")
        print(f"\tvru_y: {vru_y}")

    box_center = carla.Location(x=vru_x, y=vru_y, z=draw_z_height + 1.0)
    vru_box = carla.BoundingBox(box_center, carla.Vector3D(1.5, 1.5, 0))

    world.debug.draw_box(
        vru_box,
        carla.Rotation(0, 0, 0),
        thickness=0.2,
        color=carla.Color(r=255, g=0, b=0),
        life_time=draw_lifetime,
        persistent_lines=True,
    )

    if debug_opts.debug_vru_str:
        world.debug.draw_string(
            carla.Location(x=vru_x, y=vru_y, z=draw_z_height),
            "[VRU]",
            draw_shadow=False,
            color=carla.Color(r=255, g=0, b=0),
            life_time=draw_lifetime,
            persistent_lines=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        metavar="H",
        default="127.0.0.1",
        help="IP of the host server (default: 127.0.0.1)",
    )
    parser.add_argument(
        "-p",
        "--port",
        metavar="P",
        default=2000,
        type=int,
        help="TCP port to listen to (default: 2000)",
    )
    parser.add_argument(
        "-f", "--file", metavar="F", type=str, help="Import file to read crossing data"
    )

    parser.add_argument(
        "--debug-origin",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Toggle origin location debug strings in world.",
    )
    parser.add_argument(
        "--debug-vru-ref",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Toggle VRU reference marker ([R]) debug string.",
    )
    parser.add_argument(
        "--debug-vru-str",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Toggle VRU label string drawing.",
    )
    parser.add_argument(
        "--debug-coords",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Toggle verbose SDSM coordinate logs.",
    )

    args = parser.parse_args()

    try:
        client = carla.Client(args.host, args.port)
        client.set_timeout(5.0)
        world = client.get_world()

        draw_z_height = 237.5
        draw_lifetime = 0.2

        # mcity_origin = geodetic_to_ecef(42.30059341574939, -83.69928318881136, 0)
        mcity_origin = {"x": 518508.658, "y": -4696054.02, "z": 0.0}

        print(f"mcity_origin: {mcity_origin}")

        if args.debug_origin:
            world.debug.draw_string(
                carla.Location(
                    x=mcity_origin["x"], y=mcity_origin["y"], z=draw_z_height
                ),
                "ORIGIN",
                draw_shadow=False,
                color=carla.Color(r=255, g=0, b=0),
                life_time=draw_lifetime,
                persistent_lines=True,
            )
            world.debug.draw_string(
                carla.Location(x=0, y=0, z=245),
                "[0,0,245]",
                draw_shadow=False,
                color=carla.Color(r=255, g=0, b=0),
                life_time=draw_lifetime,
                persistent_lines=True,
            )

        receive_ip = os.getenv("VUG_J3224_ADAPTER_SEND_ADDRESS", "127.0.0.1")
        receive_port = int(os.getenv("VUG_J3224_ADAPTER_SEND_PORT", "12345"))

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((receive_ip, receive_port))
        sock.settimeout(1.0)

        print(f"Listening for UDP SDSM messages on {receive_ip}:{receive_port}...")

        while True:
            try:
                data, _ = sock.recvfrom(4096)
            except socket.timeout:
                continue

            hex_data = data.hex()

            if hex_data.startswith("0029"):
                print("Received SDSM")
                decoded_sdsm = SDSMDecoder.sdsm_decoder(hex_data)
                print(f"Decoded SDSM: {decoded_sdsm}")
                draw_sdsm(
                    world,
                    decoded_sdsm,
                    draw_z_height,
                    draw_lifetime,
                    mcity_origin,
                    args,
                )

    except KeyboardInterrupt:
        print("\nCancelled by user.")
    finally:
        print("Done!")


if __name__ == "__main__":
    main()
