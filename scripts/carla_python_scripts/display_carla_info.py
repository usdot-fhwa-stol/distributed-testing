"""
Overlay actor labels and traffic signal states in the CARLA simulation world.

The script is map-independent.

Examples:

    # Show traffic signals and vehicles continously.
    python carla_overlay.py --show-signals --show-vehicles --duration 0

    # Include walkers and print actor details.
    python carla_overlay.py \
      --show-vehicles \
      --show-walkers \
      --show-signals \
      --duration 0 \
      --verbose

Environment variables:

    VUG_DISPLAY_TRAFFIC_SIGNAL_STATES=true
    VUG_DISPLAY_VEHICLE_ROLENAMES=true
    VUG_DISPLAY_WALKER_ROLENAMES=true
"""

import argparse
import os
import sys
import time
from typing import Optional, cast

import carla


VEHICLE_SURFACE_COLOR = carla.Color(r=0, g=0, b=255)
VEHICLE_ABOVE_SURFACE_COLOR = carla.Color(r=80, g=160, b=140)
VEHICLE_BELOW_SURFACE_COLOR = carla.Color(r=160, g=80, b=140)
WALKER_COLOR = carla.Color(r=128, g=0, b=128)

TRAFFIC_GREEN_COLOR = carla.Color(r=0, g=255, b=0)
TRAFFIC_RED_COLOR = carla.Color(r=255, g=0, b=0)
TRAFFIC_YELLOW_COLOR = carla.Color(r=255, g=255, b=0)
TRAFFIC_UNKNOWN_COLOR = carla.Color(r=255, g=255, b=255)


def env_bool(name: str, default: bool = False) -> bool:
    """Read formatted boolean environment variable."""
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
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
        "--filterv",
        metavar="PATTERN",
        default="vehicle.*",
        help='Vehicle actor filter (default: "vehicle.*").',
    )
    parser.add_argument(
        "--filterw",
        metavar="PATTERN",
        default="walker.pedestrian.*",
        help='Walker actor filter (default: "walker.pedestrian.*").',
    )
    parser.add_argument(
        "-d",
        "--duration",
        metavar="SECONDS",
        default=10.0,
        type=float,
        help=(
            "Overlay duration in seconds. Use 0 for continuous updates "
            "(default: 10)."
        ),
    )
    parser.add_argument(
        "--refresh-interval",
        type=float,
        default=0.5,
        help="Seconds between continuous overlay updates (default: 0.5).",
    )

    parser.add_argument(
        "--show-vehicles",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Display vehicle role-name labels. If unspecified, uses "
            "VUG_DISPLAY_VEHICLE_ROLENAMES."
        ),
    )
    parser.add_argument(
        "--show-walkers",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Display walker role-name labels. If unspecified, uses "
            "VUG_DISPLAY_WALKER_ROLENAMES."
        ),
    )
    parser.add_argument(
        "--show-signals",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Display traffic-light state labels. If unspecified, uses "
            "VUG_DISPLAY_TRAFFIC_SIGNAL_STATES."
        ),
    )

    parser.add_argument(
        "--vehicle-label-height",
        type=float,
        default=2.5,
        help="Vehicle label height above actor origin in meters (default: 2.5).",
    )
    parser.add_argument(
        "--walker-label-height",
        type=float,
        default=2.0,
        help="Walker label height above actor origin in meters (default: 2.0).",
    )
    parser.add_argument(
        "--signal-label-height",
        type=float,
        default=6.0,
        help=(
            "Traffic-light label height above actor origin in meters "
            "(default: 6.0)."
        ),
    )
    parser.add_argument(
        "--surface-tolerance",
        type=float,
        default=2.0,
        help=(
            "Vehicle Z-distance in meters from nearest road waypoint considered "
            "to be at road level (default: 2.0)."
        ),
    )
    parser.add_argument(
        "--show-actor-id",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include CARLA actor IDs in labels (default: enabled).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print actor details each iteration.",
    )

    return parser.parse_args()


def get_label_lifetime(args: argparse.Namespace) -> float:
    """
    Return debug label lifetime.

    In continuous mode, labels expire just after the next refresh. This avoids
    leaving stale text in the world after actors move or are deleted.
    """
    if args.duration == 0:
        return max(args.refresh_interval * 1.25, 0.1)

    return args.duration


def clean_role_name(role_name: str) -> str:
    """Normalize known role-name variants for easier display."""
    cleaned_name = (
        role_name.replace("-MAN-", "-")
        .replace("TFHRC", "FHWA")
        .replace("carma_1", "FHWA")
    )

    # Preserve existing project-specific display behavior.
    if cleaned_name == "MCITY-TERASIM-01":
        return "MCITY-TERASIM-02"

    if cleaned_name == "MCITY-TERASIM-02":
        return "MCITY-TERASIM-01"

    return cleaned_name


def actor_label(
    actor: carla.Actor,
    display_name: str,
    include_actor_id: bool,
    prefix: str = "",
) -> str:
    """Build a compact, readable actor label."""
    if include_actor_id:
        return f"{prefix}{display_name} [{actor.id}]"

    return f"{prefix}{display_name}"


def get_vehicle_color(
    world_map: carla.Map,
    vehicle_location: carla.Location,
    surface_tolerance: float,
) -> carla.Color:
    """
    Classify a vehicle relative to the nearest road surface.

    Red:
        Vehicle is within surface_tolerance of its nearest road waypoint.

    Blue:
        Vehicle is substantially above the nearest road waypoint. This can help
        identify actors spawning on elevated layers, bridges, or staging areas.

    Gray:
        Vehicle is substantially below the nearest road waypoint.
    """
    waypoint = world_map.get_waypoint(
        vehicle_location,
        project_to_road=True,
    )

    if waypoint is None:
        return VEHICLE_SURFACE_COLOR

    road_z = waypoint.transform.location.z
    z_difference = vehicle_location.z - road_z

    if z_difference > surface_tolerance:
        return VEHICLE_ABOVE_SURFACE_COLOR

    if z_difference < -surface_tolerance:
        return VEHICLE_BELOW_SURFACE_COLOR

    return VEHICLE_SURFACE_COLOR


def draw_actor_label(
    world: carla.World,
    actor: carla.Actor,
    text: str,
    color: carla.Color,
    height_offset: float,
    label_lifetime: float,
) -> None:
    """Draw a debug label directly above an actor."""
    actor_location = actor.get_location()
    label_location = actor_location + carla.Location(z=height_offset)

    world.debug.draw_string(
        location=label_location,
        text=text,
        draw_shadow=True,
        color=color,
        life_time=label_lifetime,
        persistent_lines=False,
    )


def display_vehicle_rolenames(
    world: carla.World,
    world_map: carla.Map,
    args: argparse.Namespace,
) -> None:
    """Draw labels for all matching vehicle actors."""
    vehicle_list = world.get_actors().filter(args.filterv)
    label_lifetime = get_label_lifetime(args)

    if not vehicle_list:
        if args.verbose:
            print("    NO VEHICLES FOUND")
        return

    if args.verbose:
        print("\nCARLA VEHICLES:")

    for vehicle in vehicle_list:
        role_name = vehicle.attributes.get("role_name", "unknown")
        display_name = clean_role_name(role_name)
        vehicle_location = vehicle.get_location()

        color = get_vehicle_color(
            world_map=world_map,
            vehicle_location=vehicle_location,
            surface_tolerance=args.surface_tolerance,
        )

        label = actor_label(
            actor=vehicle,
            display_name=display_name,
            include_actor_id=args.show_actor_id,
            prefix="V: ",
        )

        if args.verbose:
            print(
                f"    Vehicle ID {vehicle.id}: "
                f"role_name={role_name!r}, "
                f"location=({vehicle_location.x:.2f}, "
                f"{vehicle_location.y:.2f}, {vehicle_location.z:.2f})"
            )

        draw_actor_label(
            world=world,
            actor=vehicle,
            text=label,
            color=color,
            height_offset=args.vehicle_label_height,
            label_lifetime=label_lifetime,
        )


def display_walker_rolenames(
    world: carla.World,
    args: argparse.Namespace,
) -> None:
    """Draw labels for all matching pedestrian actors."""
    walker_list = world.get_actors().filter(args.filterw)
    label_lifetime = get_label_lifetime(args)

    if not walker_list:
        if args.verbose:
            print("    NO WALKERS FOUND")
        return

    if args.verbose:
        print("\nCARLA WALKERS:")

    for walker in walker_list:
        role_name = walker.attributes.get("role_name", "pedestrian")
        display_name = clean_role_name(role_name)
        walker_location = walker.get_location()

        label = actor_label(
            actor=walker,
            display_name=display_name,
            include_actor_id=args.show_actor_id,
            prefix="P: ",
        )

        if args.verbose:
            print(
                f"    Walker ID {walker.id}: "
                f"role_name={role_name!r}, "
                f"location=({walker_location.x:.2f}, "
                f"{walker_location.y:.2f}, {walker_location.z:.2f})"
            )

        draw_actor_label(
            world=world,
            actor=walker,
            text=label,
            color=WALKER_COLOR,
            height_offset=args.walker_label_height,
            label_lifetime=label_lifetime,
        )


def traffic_signal_display(
    signal_state: carla.TrafficLightState,
) -> tuple[str, carla.Color]:
    """Convert a CARLA traffic-light state into display text and color."""
    match signal_state:
        case carla.TrafficLightState.Green:
            return "[GREEN]", TRAFFIC_GREEN_COLOR
        case carla.TrafficLightState.Red:
            return "[RED]", TRAFFIC_RED_COLOR
        case carla.TrafficLightState.Yellow:
            return "[YELLOW]", TRAFFIC_YELLOW_COLOR
        case carla.TrafficLightState.Off:
            return "[OFF]", TRAFFIC_UNKNOWN_COLOR
        case _:
            return f"[{str(signal_state).upper()}]", TRAFFIC_UNKNOWN_COLOR


def display_traffic_signal_state(
    world: carla.World,
    args: argparse.Namespace,
) -> None:
    """Draw state labels for every CARLA traffic light."""
    signal_list = world.get_actors().filter("traffic.traffic_light*")
    label_lifetime = get_label_lifetime(args)

    if not signal_list:
        if args.verbose:
            print("    NO TRAFFIC SIGNALS FOUND")
        return

    if args.verbose:
        print("\nTRAFFIC SIGNALS:")

    for actor in signal_list:
        signal = cast(carla.TrafficLight, actor)
        signal_state = signal.get_state()
        state_text, signal_color = traffic_signal_display(signal_state)

        label = actor_label(
            actor=signal,
            display_name=state_text,
            include_actor_id=args.show_actor_id,
            prefix="TL ",
        )

        if args.verbose:
            signal_location = signal.get_location()
            print(
                f"    Signal ID {signal.id}: "
                f"state={signal_state}, "
                f"location=({signal_location.x:.2f}, "
                f"{signal_location.y:.2f}, {signal_location.z:.2f})"
            )

        draw_actor_label(
            world=world,
            actor=signal,
            text=label,
            color=signal_color,
            height_offset=args.signal_label_height,
            label_lifetime=label_lifetime,
        )


def resolve_display_option(
    argument_value: Optional[bool],
    environment_variable: str,
) -> bool:
    if argument_value is not None:
        return argument_value

    env_val = os.getenv(environment_variable)
    if env_val is not None:
        return env_bool(environment_variable)

    return True


def main() -> None:
    """Connect to CARLA and draw selected overlays."""
    args = parse_arguments()

    if args.duration < 0:
        print("Error: --duration must be zero or greater.", file=sys.stderr)
        sys.exit(2)

    if args.refresh_interval <= 0:
        print("Error: --refresh-interval must be greater than zero.", file=sys.stderr)
        sys.exit(2)

    if args.surface_tolerance < 0:
        print("Error: --surface-tolerance must be zero or greater.", file=sys.stderr)
        sys.exit(2)

    show_signals = resolve_display_option(
        args.show_signals,
        "VUG_DISPLAY_TRAFFIC_SIGNAL_STATES",
    )
    show_vehicles = resolve_display_option(
        args.show_vehicles,
        "VUG_DISPLAY_VEHICLE_ROLENAMES",
    )
    show_walkers = resolve_display_option(
        args.show_walkers,
        "VUG_DISPLAY_WALKER_ROLENAMES",
    )

    if not show_signals and not show_vehicles and not show_walkers:
        print("No overlay types are enabled.")
        print(
            "Use --show-vehicles, --show-walkers, or --show-signals, "
            "or set the matching VUG_DISPLAY_* environment variable."
        )
        return

    try:
        client = carla.Client(args.host, args.port)
        client.set_timeout(10.0)

        print(f"Connected to CARLA at {args.host}:{args.port}")

        if show_signals:
            print("----- DISPLAYING TRAFFIC LIGHT STATES -----")
        if show_vehicles:
            print("----- DISPLAYING VEHICLE ROLE NAMES -----")
        if show_walkers:
            print("----- DISPLAYING WALKER ROLE NAMES -----")

        start_time = time.monotonic()
        last_map_name: Optional[str] = None

        while True:
            world = client.get_world()
            world_map = world.get_map()

            if world_map.name != last_map_name:
                print(f"Active CARLA map: {world_map.name}")
                last_map_name = world_map.name

            if show_signals:
                display_traffic_signal_state(world, args)

            if show_vehicles:
                display_vehicle_rolenames(world, world_map, args)

            if show_walkers:
                display_walker_rolenames(world, args)

            if args.duration != 0:
                elapsed = time.monotonic() - start_time

                if elapsed >= args.duration:
                    break

                sleep_duration = min(args.refresh_interval, args.duration - elapsed)
                time.sleep(max(sleep_duration, 0.0))
            else:
                time.sleep(args.refresh_interval)

    except RuntimeError as error:
        print(f"\nCARLA Connection Error: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user. Bye!")
