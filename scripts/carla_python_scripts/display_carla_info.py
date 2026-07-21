"""Overlay vehicle role names and traffic signal states in the CARLA simulation world."""

import argparse
import os
import sys
import time
from typing import cast

import carla

MAP_HEIGHT_DICT: dict[str, dict[str, float]] = {
    "mcity_map_voices_v2-2-21": {"bottom_line": 230.0, "spawn_line": 245.0}
}


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        metavar="<hostname>",
        default="127.0.0.1",
        help="IP of the host server (default: 127.0.0.1)",
    )
    parser.add_argument(
        "-p",
        "--port",
        metavar="<port>",
        default=2000,
        type=int,
        help="TCP port to listen to (default: 2000)",
    )
    parser.add_argument(
        "--filterv",
        metavar="PATTERN",
        default="vehicle.*",
        help='Vehicles filter (default: "vehicle.*")',
    )
    parser.add_argument(
        "--filterw",
        metavar="PATTERN",
        default="walker.pedestrian.*",
        help='Pedestrians filter (default: "walker.pedestrian.*")',
    )
    parser.add_argument(
        "-d",
        "--duration",
        metavar="<seconds>",
        default=10,
        type=int,
        help="Duration in seconds to display overlay text (use 0 for continuous update loop, default: 10)",
    )
    parser.add_argument(
        "--show-vehicles",
        action="store_true",
        help="Display vehicle role names (overrides VUG_DISPLAY_VEHICLE_ROLENAMES env var)",
    )
    parser.add_argument(
        "--show-signals",
        action="store_true",
        help="Display traffic light states (overrides VUG_DISPLAY_TRAFFIC_SIGNAL_STATES env var)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Display actor details each iteration in standard output",
    )
    return parser.parse_args()


def display_vehicle_rolenames(
    world: carla.World,
    args: argparse.Namespace,
    map_string: str,
) -> None:
    text_offset = carla.Location(x=5.0, y=0.0, z=2.0)
    vehicle_list = world.get_actors().filter(args.filterv)
    label_duration = 0.5 if args.duration == 0 else float(args.duration)

    if not vehicle_list:
        if args.verbose:
            print("    NO VEHICLES FOUND")
        return

    if args.verbose:
        print("\nCARLA VEHICLES:")

    for vehicle in vehicle_list:
        role_name = vehicle.attributes.get("role_name", "unknown")

        cleaned_veh_name = (
            role_name.replace("-MAN-", "-")
            .replace("TFHRC", "FHWA")
            .replace("carma_1", "FHWA")
        )

        if cleaned_veh_name == "MCITY-TERASIM-01":
            cleaned_veh_name = "MCITY-TERASIM-02"
        elif cleaned_veh_name == "MCITY-TERASIM-02":
            cleaned_veh_name = "MCITY-TERASIM-01"

        if args.verbose:
            print(f"    ID {vehicle.id}: {vehicle.attributes}")

        veh_location = vehicle.get_location()

        if map_string in MAP_HEIGHT_DICT:
            height_limits = MAP_HEIGHT_DICT[map_string]
            if veh_location.z < height_limits["bottom_line"]:
                continue
            elif veh_location.z > height_limits["spawn_line"]:
                color = carla.Color(r=0, g=0, b=255)
            else:
                color = carla.Color(r=255, g=0, b=0)
        else:
            color = carla.Color(r=255, g=0, b=0)

        world.debug.draw_string(
            veh_location + text_offset,
            cleaned_veh_name,
            draw_shadow=False,
            color=color,
            life_time=label_duration,
            persistent_lines=True,
        )


def display_traffic_signal_state(world: carla.World, args: argparse.Namespace) -> None:
    signal_list = world.get_actors().filter("traffic.traffic_light")
    label_duration = 0.5 if args.duration == 0 else float(args.duration)

    if not signal_list:
        if args.verbose:
            print("    NO TRAFFIC SIGNALS FOUND")
        return

    if args.verbose:
        print("\nTRAFFIC SIGNALS:")

    for signal in signal_list:
        signal = cast(carla.TrafficLight, signal)

        if args.verbose:
            print(f"    Signal ID {signal.id}: {signal.attributes}")

        signal_state = signal.get_state()
        signal_state_display = str(signal_state).upper()

        if signal_state_display == "OFF":
            continue

        match signal_state:
            case carla.TrafficLightState.Green:
                signal_color = carla.Color(r=0, g=255, b=0)
            case carla.TrafficLightState.Red:
                signal_color = carla.Color(r=255, g=0, b=0)
            case carla.TrafficLightState.Yellow:
                signal_color = carla.Color(r=255, g=255, b=0)
            case _:
                signal_color = carla.Color(r=0, g=0, b=255)

        signal_draw_loc = signal.get_location() + carla.Location(x=0.0, y=0.0, z=10.0)

        world.debug.draw_string(
            signal_draw_loc,
            signal_state_display,
            draw_shadow=False,
            color=signal_color,
            life_time=label_duration,
            persistent_lines=True,
        )


def main() -> None:
    args = parse_arguments()

    env_signals = os.getenv("VUG_DISPLAY_TRAFFIC_SIGNAL_STATES", "").lower() == "true"
    env_vehicles = os.getenv("VUG_DISPLAY_VEHICLE_ROLENAMES", "").lower() == "true"

    show_signals = args.show_signals or env_signals
    show_vehicles = args.show_vehicles or env_vehicles

    if not show_signals and not show_vehicles:
        print("Neither vehicle role names nor traffic signal states are enabled.")
        print("Use --show-vehicles / --show-signals or set environment variables.")
        sys.exit(0)

    try:
        client = carla.Client(args.host, args.port)
        client.set_timeout(10.0)
        world = client.get_world()

        map_string = world.get_map().name
        if map_string not in MAP_HEIGHT_DICT:
            print(
                f"Notice: Map '{map_string}' vertical bounds are unconfigured. Rendering vehicle labels as red."
            )

        if show_signals:
            print("----- DISPLAYING TRAFFIC LIGHT STATES -----")
        if show_vehicles:
            print("----- DISPLAYING VEHICLE ROLENAMES -----")

        while True:
            current_world = client.get_world()

            if show_signals:
                display_traffic_signal_state(current_world, args)

            if show_vehicles:
                display_vehicle_rolenames(current_world, args, map_string)

            if args.duration != 0:
                break

            time.sleep(0.5)

    except RuntimeError as e:
        print(f"\nCARLA Connection Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user. Bye!")
