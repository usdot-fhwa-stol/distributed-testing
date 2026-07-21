#!/usr/bin/env python3

# Copyright (c) 2019 Computer Vision Center (CVC) at the Universitat Autonoma de
# Barcelona (UAB).
#
# This work is licensed under the terms of the MIT license.
# For a copy, see <https://opensource.org/licenses/MIT>.

"""Set or inspect the spectator camera view for Mcity in CARLA."""

import argparse
import sys
import time

import carla

DEFAULT_LOCATION = carla.Location(x=99.919708, y=-34.552490, z=453.469788)
DEFAULT_ROTATION = carla.Rotation(pitch=-88.999451, yaw=4.830535, roll=0.0)


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
        "-g",
        "--get",
        action="store_true",
        help="Print the current spectator transform instead of setting it",
    )
    argparser.add_argument(
        "--x",
        type=float,
        default=DEFAULT_LOCATION.x,
        help=f"Spectator X coordinate (default: {DEFAULT_LOCATION.x})",
    )
    argparser.add_argument(
        "--y",
        type=float,
        default=DEFAULT_LOCATION.y,
        help=f"Spectator Y coordinate (default: {DEFAULT_LOCATION.y})",
    )
    argparser.add_argument(
        "--z",
        type=float,
        default=DEFAULT_LOCATION.z,
        help=f"Spectator Z coordinate (default: {DEFAULT_LOCATION.z})",
    )
    argparser.add_argument(
        "--pitch",
        type=float,
        default=DEFAULT_ROTATION.pitch,
        help=f"Spectator pitch angle (default: {DEFAULT_ROTATION.pitch})",
    )
    argparser.add_argument(
        "--yaw",
        type=float,
        default=DEFAULT_ROTATION.yaw,
        help=f"Spectator yaw angle (default: {DEFAULT_ROTATION.yaw})",
    )
    argparser.add_argument(
        "--roll",
        type=float,
        default=DEFAULT_ROTATION.roll,
        help=f"Spectator roll angle (default: {DEFAULT_ROTATION.roll})",
    )
    args = argparser.parse_args()

    client = carla.Client(args.host, args.port)
    client.set_timeout(10.0)

    try:
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
        else:
            target_location = carla.Location(x=args.x, y=args.y, z=args.z)
            target_rotation = carla.Rotation(
                pitch=args.pitch, yaw=args.yaw, roll=args.roll
            )
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
