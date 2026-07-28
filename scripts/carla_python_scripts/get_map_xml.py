import argparse
import socket
import sys
from pathlib import Path

import carla


def get_ip(host: str) -> str:
    """Resolve host IP for local network connections."""
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


def get_cardinal_direction(yaw: float) -> tuple[str, int]:
    """Map yaw rotation to cardinal directions (EB, SB, NB, WB) and NEMA phase numbers."""
    yaw = (yaw + 360) % 360
    if 45 <= yaw < 135:
        return "SB", 4
    elif 135 <= yaw < 225:
        return "WB", 8
    elif 225 <= yaw < 315:
        return "NB", 6
    else:
        return "EB", 2


def extract_map_data(world: carla.World, num_waypoints: int = 6) -> str:
    """Extracts geodetic position, signal IDs, and waypoints to generate XML config."""
    carla_map = world.get_map()
    
    print("\n" + "=" * 60)
    print(f"Extracting configuration for map: {carla_map.name}")
    print("=" * 60)

    # 1. Geodetic Origin
    origin_geo = carla_map.transform_to_geolocation(carla.Location(x=0, y=0, z=0))
    print("\n1. GEODETIC ORIGIN (x=0, y=0, z=0):")
    print(f"   Latitude:  {origin_geo.latitude:.6f}°")
    print(f"   Longitude: {origin_geo.longitude:.6f}°")
    print(f"   Height:    {origin_geo.altitude:.2f}m")

    # 2. Traffic Signal Mappings
    traffic_lights = world.get_actors().filter("traffic.traffic_light")
    print(f"\n2. TRAFFIC SIGNAL MAPPINGS ({len(traffic_lights)} traffic lights found):")
    print("   [Actor ID] | [Signal ID] | [Phase] | [Dir] | [Latitude] | [Longitude]")
    print("   " + "-" * 58)

    tl_records = []
    for tl in traffic_lights:
        tl_id = tl.id
        transform = tl.get_transform()
        loc = transform.location
        geo_loc = carla_map.transform_to_geolocation(loc)

        # FIXED: Retrieve OpenDRIVE signal landmarks using landmark ID API
        landmarks = carla_map.get_all_landmarks_from_id(str(tl_id))
        signal_id = landmarks[0].id if landmarks else f"{tl_id}"
        
        direction, phase = get_cardinal_direction(transform.rotation.yaw)

        tl_records.append({
            "actor_id": tl_id,
            "signal_id": signal_id,
            "phase": phase,
            "dir": direction,
            "geo": geo_loc,
            "loc": loc,
        })

        print(
            f"   Actor {tl_id:<4} | Signal {signal_id:<6} | Phase {phase} | {direction:<2}  | "
            f"{geo_loc.latitude:.6f} | {geo_loc.longitude:.6f}"
        )

    # 3. Route Waypoints
    waypoints_xml = []
    if tl_records:
        start_wp = carla_map.get_waypoint(tl_records[0]["loc"])
        curr_wp = start_wp
        time_step = 0

        print(f"\n3. SAMPLE ROUTE WAYPOINTS (Near Actor {tl_records[0]['actor_id']}):")
        for _ in range(num_waypoints):
            loc = curr_wp.transform.location
            geo = carla_map.transform_to_geolocation(loc)
            heading = curr_wp.transform.rotation.yaw

            snippet = (
                f'      <waypoint latitudeInDegrees="{geo.latitude:.9f}" '
                f'longitudeInDegrees="{geo.longitude:.9f}" '
                f'heightAboveEllipsoidInMeters="{geo.altitude:.0f}" '
                f'heading="{heading:.1f}" time="{time_step}"/>'
            )
            waypoints_xml.append(snippet)
            print(snippet)

            next_wps = curr_wp.next(5.0)
            if next_wps:
                curr_wp = next_wps[0]
            time_step += 1

    # 4. Generate XML Snippet
    mappings_xml = ""
    for tl in tl_records[:4]:  # First 4 traffic signals
        mappings_xml += (
            f'    <mapping signalId="{tl["signal_id"]}" phase="{tl["phase"]}"/> '
            f'<!-- {tl["dir"]}, Actor {tl["actor_id"]} -->\n'
        )

    waypoints_block = "\n".join(waypoints_xml)

    xml_template = f"""<intersectionSignalControllers>
  <intersectionSignalController name="Town10_Main" adapterName="V2XEG-1" lvcIndicator="Live">
    <controller name="" id="0"/>
  </intersectionSignalController>
</intersectionSignalControllers>

<phaseSignalMappings>
  <configuration name="Town10_Main Configuration" controllerName="Town10_Main">
    <GeodeticPosition latitudeInDegrees="{origin_geo.latitude:.6f}" longitudeInDegrees="{origin_geo.longitude:.6f}" heightAboveEllipsoidInMeters="0"/>
{mappings_xml}  </configuration>
</phaseSignalMappings>

<simulations>
  <simulation name="DEFAULT-1" type="CARLA">
    <WeatherState>ClearNoon</WeatherState>
  </simulation>
</simulations>

<routes>
  <route name="DEFAULT-Route-1" entityIdentifier="DEFAULT-R-1" csvRoute="route_files/town10_test_route.csv"/>
  <route name="DEFAULT-Route-2" entityIdentifier="DEFAULT-P-1">
{waypoints_block}
  </route>
</routes>"""

    return xml_template


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
        "-m",
        "--map",
        help="load a new map (e.g., Town10HD_Opt or Town10)",
    )
    argparser.add_argument(
        "-x",
        "--xodr-path",
        metavar="XODR_FILE_PATH",
        help="load map from an OpenDRIVE file",
    )
    argparser.add_argument(
        "--osm-path",
        metavar="OSM_FILE_PATH",
        help="load map from an OpenStreetMap file",
    )
    argparser.add_argument(
        "-o",
        "--output",
        metavar="XML_PATH",
        help="save extracted configuration XML directly to a file",
    )

    args = argparser.parse_args()

    client = carla.Client(args.host, args.port, worker_threads=1)
    client.set_timeout(10.0)

    resolved_ip = get_ip(args.host)
    print(f"Connected to CARLA server at {resolved_ip}:{args.port}")

    if args.map is not None:
        print(f"Loading map {args.map!r}...")
        world = client.load_world(args.map)
    elif args.xodr_path is not None:
        xodr_file = Path(args.xodr_path)
        if xodr_file.exists():
            data = xodr_file.read_text(encoding="utf-8")
            print(f"Loading OpenDRIVE map {xodr_file.name!r}...")
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
            print("ERROR: OpenDRIVE file not found.")
            sys.exit(1)
    elif args.osm_path is not None:
        osm_file = Path(args.osm_path)
        if osm_file.exists():
            data = osm_file.read_text(encoding="utf-8")
            settings = carla.Osm2OdrSettings()
            print("Converting OSM data to OpenDRIVE...")
            xodr_data = carla.Osm2Odr.convert(data, settings)
            world = client.generate_opendrive_world(xodr_data)
        else:
            print("ERROR: OSM file not found.")
            sys.exit(1)
    else:
        world = client.get_world()

    xml_output = extract_map_data(world)

    print("\n" + "=" * 60)
    print("4. GENERATED CONFIGURATION XML:")
    print("=" * 60)
    print(xml_output)

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(xml_output, encoding="utf-8")
        print(f"\nSuccessfully wrote configuration to {out_path.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user. Bye!")
    except RuntimeError as e:
        print(f"CARLA Error: {e}")