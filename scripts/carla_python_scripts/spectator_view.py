"""Set, inspect, or load maps with specific spectator camera views in CARLA."""

import argparse
import sys
import time
import carla

MAP_PRESETS = {
    "delave": {
        "location": carla.Location(x=-105.437805, y=726.073425, z=926.507080),
        "rotation": carla.Rotation(pitch=-89.0, yaw=-90.0, roll=0.0),
    },
    "mcity": {
        "location": carla.Location(x=99.919708, y=-34.552490, z=453.469788),
        "rotation": carla.Rotation(pitch=-88.999451, yaw=4.830535, roll=0.0),
    },
    "default": {
        "location": carla.Location(x=298.728577, y=-216.214294, z=46.651649),
        "rotation": carla.Rotation(pitch=-43.542046, yaw=144.351303, roll=0.0),
    },
}


def main() -> None:
    argparser = argparse.ArgumentParser(description=__doc__)
    argparser.add_argument(
        "--host",
        metavar="H",
        default="127.0.0.1",
        help="IP of the host server (default: 127.0.0.1)",
    )
    argparser.add_argument(
        "-p",
        "--port",
        metavar="P",
        default=2000,
        type=int,
        help="TCP port to listen to (default: 2000)",
    )
    argparser.add_argument(
        "-m",
        "--map",
        metavar="MAP",
        type=str,
        help="Optional: Load a new map into the simulation (e.g., 'Town01', 'Delave', 'Mcity')",
    )
    argparser.add_argument(
        "-g",
        "--get",
        action="store_true",
        help="Print the current spectator transform instead of setting it",
    )

    argparser.add_argument("--x", type=float, help="Spectator X coordinate")
    argparser.add_argument("--y", type=float, help="Spectator Y coordinate")
    argparser.add_argument("--z", type=float, help="Spectator Z coordinate")
    argparser.add_argument("--pitch", type=float, help="Spectator pitch angle")
    argparser.add_argument("--yaw", type=float, help="Spectator yaw angle")
    argparser.add_argument("--roll", type=float, help="Spectator roll angle")

    args = argparser.parse_args()

    client = carla.Client(args.host, args.port)
    client.set_timeout(10.0)

    try:
        if args.map:
            print(f"Loading map '{args.map}'...")
            world = client.load_world(args.map)
        else:
            world = client.get_world()

        spectator = world.get_spectator()

        if args.get:
            transform = spectator.get_transform()
            loc, rot = transform.location, transform.rotation
            print("\n----- CURRENT SPECTATOR TRANSFORM -----")
            print(f"Location: x={loc.x:.6f}, y={loc.y:.6f}, z={loc.z:.6f}")
            print(
                f"Rotation: pitch={rot.pitch:.6f}, yaw={rot.yaw:.6f}, roll={rot.roll:.6f}\n"
            )
            return

        current_map_name = world.get_map().name.split("/")[-1].lower()
        preset = MAP_PRESETS.get(current_map_name, MAP_PRESETS["default"])

        target_x = args.x if args.x is not None else preset["location"].x
        target_y = args.y if args.y is not None else preset["location"].y
        target_z = args.z if args.z is not None else preset["location"].z

        target_pitch = args.pitch if args.pitch is not None else preset["rotation"].pitch
        target_yaw = args.yaw if args.yaw is not None else preset["rotation"].yaw
        target_roll = args.roll if args.roll is not None else preset["rotation"].roll

        target_location = carla.Location(x=target_x, y=target_y, z=target_z)
        target_rotation = carla.Rotation(pitch=target_pitch, yaw=target_yaw, roll=target_roll)
        target_transform = carla.Transform(target_location, target_rotation)

        spectator.set_transform(target_transform)
        print("\n----- SUCCESSFULLY SET SPECTATOR VIEW -----\n")

    except RuntimeError as e:
        print(f"CARLA Error: {e}", file=sys.stderr)
    finally:
        time.sleep(0.5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user. Bye!")