import argparse
import datetime
import re
import socket
import sys
import textwrap
from pathlib import Path

import carla


def get_ip(host: str) -> str:
    if host in ["localhost", "127.0.0.1"]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("10.255.255.255", 1))
            host = sock.getsockname()[0]
        except OSError:
            pass
        finally:
            sock.close()
    return host


def find_weather_presets() -> list[tuple[carla.WeatherParameters, str]]:
    presets = [x for x in dir(carla.WeatherParameters) if re.match(r"[A-Z].+", x)]
    return [(getattr(carla.WeatherParameters, x), x) for x in presets]


def list_options(client: carla.Client) -> None:
    maps = [m.replace("/Game/Carla/Maps/", "") for m in client.get_available_maps()]
    indent = 4 * " "

    def wrap(text: str) -> str:
        return "\n".join(
            textwrap.wrap(text, initial_indent=indent, subsequent_indent=indent)
        )

    print("weather presets:\n")
    print(f"{wrap(', '.join(x for _, x in find_weather_presets()))}.\n")
    print("available maps:\n")
    print(f"{wrap(', '.join(sorted(maps)))}.\n")


def list_blueprints(world: carla.World, bp_filter: str) -> None:
    blueprint_library = world.get_blueprint_library()
    blueprints = [bp.id for bp in blueprint_library.filter(bp_filter)]
    print(f"available blueprints (filter {bp_filter!r}):\n")
    for bp in sorted(blueprints):
        print(f"    {bp}")
    print("")


def inspect(args: argparse.Namespace, client: carla.Client) -> None:
    address = f"{get_ip(args.host)}:{args.port}"

    world = client.get_world()
    elapsed_time_sec = world.get_snapshot().timestamp.elapsed_seconds
    elapsed_time = datetime.timedelta(seconds=int(elapsed_time_sec))

    actors = world.get_actors()
    s = world.get_settings()

    weather = "Custom"
    current_weather = world.get_weather()
    for preset, name in find_weather_presets():
        if current_weather == preset:
            weather = name
            break

    if s.fixed_delta_seconds is None or s.fixed_delta_seconds == 0.0:
        frame_rate = "variable"
    else:
        frame_rate = f"{1000.0 * s.fixed_delta_seconds:.2f} ms ({int(1.0 / s.fixed_delta_seconds)} FPS)"

    print("-" * 34)
    print(f"address:   {address:>22s}")
    print(f"version:   {client.get_server_version():>22s}\n")
    print(f"map:       {world.get_map().name:>22s}")
    print(f"weather:   {weather:>22s}\n")
    print(f"time:      {str(elapsed_time):>22s}\n")
    print(f"frame rate:{frame_rate:>22s}")
    print(f"rendering: {'disabled' if s.no_rendering_mode else 'enabled':>22s}")
    print(f"sync mode: {'enabled' if s.synchronous_mode else 'disabled':>22s}\n")
    print(f"actors:    {len(actors):>22d}")
    print(f"  * spectator: {len(actors.filter('spectator')):>16d}")
    print(f"  * static:    {len(actors.filter('static.*')):>16d}")
    print(f"  * traffic:   {len(actors.filter('traffic.*')):>16d}")
    print(f"  * vehicles:  {len(actors.filter('vehicle.*')):>16d}")
    print(f"  * walkers:   {len(actors.filter('walker.*')):>16d}")
    print("-" * 34)


def main() -> None:
    argparser = argparse.ArgumentParser(description=__doc__)
    argparser.add_argument(
        "--host",
        metavar="H",
        default="localhost",
        help="IP of the host CARLA Simulator (default: localhost)",
    )
    argparser.add_argument(
        "-p",
        "--port",
        metavar="P",
        default=2000,
        type=int,
        help="TCP port of CARLA Simulator (default: 2000)",
    )
    argparser.add_argument(
        "-d", 
        "--default", 
        action="store_true", 
        help="set default settings"
    )
    argparser.add_argument(
        "-m", 
        "--map", 
        help="load a new map, use --list to see available maps"
    )
    argparser.add_argument(
        "-r", 
        "--reload-map", 
        action="store_true", 
        help="reload current map"
    )
    argparser.add_argument(
        "--delta-seconds",
        metavar="S",
        type=float,
        help="set fixed delta seconds, zero for variable frame rate",
    )
    argparser.add_argument(
        "--fps",
        metavar="N",
        type=float,
        help="set fixed FPS, zero for variable FPS (similar to --delta-seconds)",
    )
    argparser.add_argument(
        "--rendering",
        action="store_true",
        help="enable rendering"
    )
    argparser.add_argument(
        "--sync",
        action="store_true",
        help="enable synchronous mode"
    )
    argparser.add_argument(
        "--no-sync",
        action="store_true",
        help="disable synchronous mode"
    )
    argparser.add_argument(
        "--weather",
        help="set weather preset, use --list to see available presets"
    )
    argparser.add_argument(
        "-i",
        "--inspect",
        action="store_true",
        help="inspect simulation"
    )
    argparser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="list available options"
    )
    argparser.add_argument(
        "-b",
        "--list-blueprints",
        metavar="FILTER",
        help="list available blueprints matching FILTER (use '*' to list them all)",
    )
    argparser.add_argument(
        "-x",
        "--xodr-path",
        metavar="XODR_FILE_PATH",
        help="load a new map with a minimum physical road representation of the provided OpenDRIVE",
    )
    argparser.add_argument(
        "--osm-path",
        metavar="OSM_FILE_PATH",
        help="load a new map with a minimum physical road representation of the provided OpenStreetMaps",
    )

    if len(sys.argv) < 2:
        argparser.print_help()
        return

    args = argparser.parse_args()

    client = carla.Client(args.host, args.port, worker_threads=1)
    client.set_timeout(10.0)

    if args.default:
        args.rendering = True
        args.delta_seconds = 0.0
        args.weather = "Default"
        args.no_sync = True

    if args.map is not None:
        print(f"load map {args.map!r}.")
        world = client.load_world(args.map)

    elif args.reload_map:
        print("reload map.")
        world = client.reload_world()

    elif args.xodr_path is not None:
        xodr_file = Path(args.xodr_path)
        if xodr_file.exists():
            try:
                data = xodr_file.read_text(encoding="utf-8")
            except OSError:
                print("file could not be read.")
                sys.exit(1)

            print(f"load opendrive map {xodr_file.name!r}.")
            world = client.generate_opendrive_world(
                data,
                carla.OpendriveGenerationParameters(
                    vertex_distance=2.0,
                    max_road_length=500.0,
                    wall_height=1.0,
                    additional_width=0.6,
                    smooth_junctions=True,
                    enable_mesh_visibility=True,
                ),
            )

        else:
            print("file not found.")
            sys.exit(1)

    elif args.osm_path is not None:
        osm_file = Path(args.osm_path)
        if osm_file.exists():
            try:
                data = osm_file.read_text(encoding="utf-8")
            except OSError:
                print("file could not be read.")
                sys.exit(1)

            settings = carla.Osm2OdrSettings()
            print("Converting OSM data to OpenDRIVE...")
            xodr_data = carla.Osm2Odr.convert(data, settings)
            print("load opendrive map.")
            world = client.generate_opendrive_world(
                xodr_data,
                carla.OpendriveGenerationParameters(
                    vertex_distance=2.0,
                    max_road_length=500.0,
                    wall_height=0.0,
                    additional_width=0.6,
                    smooth_junctions=True,
                    enable_mesh_visibility=True,
                ),
            )
        else:
            print("file not found.")
            sys.exit(1)
    else:
        world = client.get_world()

    settings = world.get_settings()

    if args.no_rendering:
        print("disable rendering.")
        settings.no_rendering_mode = True
    elif args.rendering:
        print("enable rendering.")
        settings.no_rendering_mode = False

    if args.sync:
        print("enable synchronous mode.")
        settings.synchronous_mode = True
    elif args.no_sync:
        print("disable synchronous mode.")
        settings.synchronous_mode = False

    if args.delta_seconds is not None:
        settings.fixed_delta_seconds = args.delta_seconds
    elif args.fps is not None:
        settings.fixed_delta_seconds = (1.0 / args.fps) if args.fps > 0.0 else 0.0

    if args.delta_seconds is not None or args.fps is not None:
        if settings.fixed_delta_seconds and settings.fixed_delta_seconds > 0.0:
            print(
                f"set fixed frame rate {1000.0 * settings.fixed_delta_seconds:.2f} milliseconds "
                f"({int(1.0 / settings.fixed_delta_seconds)} FPS)"
            )
        else:
            print("set variable frame rate.")
            settings.fixed_delta_seconds = None

    world.apply_settings(settings)

    if args.weather is not None:
        if not hasattr(carla.WeatherParameters, args.weather):
            print(f"ERROR: weather preset {args.weather!r} not found.")
        else:
            print(f"set weather preset {args.weather!r}.")
            world.set_weather(getattr(carla.WeatherParameters, args.weather))

    if args.inspect:
        inspect(args, client)
    if args.list:
        list_options(client)
    if args.list_blueprints:
        list_blueprints(world, args.list_blueprints)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user. Bye!")
    except RuntimeError as e:
        print(e)
