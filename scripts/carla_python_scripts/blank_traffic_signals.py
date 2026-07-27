#!/usr/bin/env python3

# Copyright (c) 2019 Computer Vision Center (CVC) at the Universitat Autonoma de
# Barcelona (UAB).
#
# This work is licensed under the terms of the MIT license.
# For a copy, see <https://opensource.org/licenses/MIT>.

"""Either blanks all traffic signals OR blanks traffic signals with a defined radius of predefined locations"""

import argparse
import sys
import time

import carla

# Example targeted intersection locations [x, y, z]
TARGET_TL_LOCATIONS: list[list[float]] = [
    [249.8, -163.4, 0.0],
    [251.7, -180.3, 0.0],
    [262.2, -165.6, 0.0],
    [262.5, -175.9, 0.0],
]


def blank_traffic_light(actor: carla.TrafficLight) -> None:
    """Freeze and turn off a traffic light actor."""
    actor.set_green_time(999999.0)
    actor.set_yellow_time(999999.0)
    actor.set_red_time(999999.0)
    actor.set_state(carla.TrafficLightState.Off)
    actor.freeze(True)


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
        "--filter-location",
        action="store_true",
        help="Only blank traffic lights near predefined target locations",
    )
    argparser.add_argument(
        "--radius",
        type=float,
        default=5.0,
        help="Distance radius (meters) when filtering by location (default: 5.0)",
    )
    args = argparser.parse_args()

    client = carla.Client(args.host, args.port)
    client.set_timeout(10.0)

    try:
        world = client.get_world()
        traffic_lights = world.get_actors().filter("traffic.traffic_light*")

        blanked_count = 0

        for actor in traffic_lights:
            if not isinstance(actor, carla.TrafficLight):
                continue

            if args.filter_location:
                actor_loc = actor.get_location()
                matched = False
                for target_coords in TARGET_TL_LOCATIONS:
                    target_loc = carla.Location(
                        x=target_coords[0],
                        y=target_coords[1],
                        z=target_coords[2],
                    )
                    if actor_loc.distance(target_loc) <= args.radius:
                        matched = True
                        break

                if not matched:
                    continue

            blank_traffic_light(actor)
            blanked_count += 1

        print(f"\n----- SUCCESSFULLY BLANKED {blanked_count} TRAFFIC SIGNALS -----\n")

    except RuntimeError as e:
        print(f"CARLA Error: {e}", file=sys.stderr)
    finally:
        time.sleep(0.5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user. Bye!")
