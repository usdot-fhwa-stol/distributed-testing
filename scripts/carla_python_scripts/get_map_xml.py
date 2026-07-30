import argparse
import json
import socket
import sys
from collections import defaultdict
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


def get_cardinal_direction(heading: float, main_heading: float) -> tuple[str, int]:
    """Map a lane heading to NEMA phase number, relative to this intersection's
    main-street heading.

    main_heading is the compass heading (degrees, 0-360) of the "main street"
    through movement for THIS intersection. Movements running parallel to it
    get the main phases (2/6), movements running perpendicular get the side
    phases (4/8).
    """
    heading = (heading + 360) % 360
    rel = (heading - main_heading + 360) % 360

    if 45 <= rel < 135:
        return "SIDE-A", 4
    elif 135 <= rel < 225:
        return "MAIN-B", 6
    elif 225 <= rel < 315:
        return "SIDE-B", 8
    else:
        return "MAIN-A", 2


def get_junction_id(tl: "carla.TrafficLight"):
    """Find the junction a traffic light actually controls.

    Tries, in order:
      1. get_affected_lane_waypoints() -- CARLA's own resolution of which
         lane waypoints (inside the junction) this light governs. This is
         the most reliable source when available.
      2. Walking forward from each stop waypoint in increasing steps, in
         case the stop line sits further back from the junction polygon
         than expected.
    """
    try:
        affected_wps = tl.get_affected_lane_waypoints()
    except AttributeError:
        affected_wps = []

    for wp in affected_wps:
        if wp.is_junction:
            return wp.get_junction().id
        for step in (1.0, 2.0, 4.0, 8.0):
            nxt = wp.next(step)
            if nxt and nxt[0].is_junction:
                return nxt[0].get_junction().id

    try:
        stop_wps = tl.get_stop_waypoints()
    except AttributeError:
        stop_wps = []

    for wp in stop_wps:
        candidates = [wp]
        for step in (1.0, 2.0, 4.0, 8.0, 12.0):
            nxt = wp.next(step)
            if nxt:
                candidates.append(nxt[0])
        for cand in candidates:
            if cand.is_junction:
                return cand.get_junction().id

    return None


def build_actor_to_signal_id_map(world: "carla.World", carla_map: "carla.Map") -> dict:
    """Build a proper actor_id -> OpenDRIVE signal id map.

    IMPORTANT: carla_map.get_all_landmarks_from_id(id) looks a landmark UP by
    its OpenDRIVE landmark id -- it is NOT a way to find the landmark id for
    a given traffic light actor. Passing an actor id into that call (as the
    previous version of this script did) returns an unrelated landmark, if
    it returns anything at all, which is why the adapter was failing to find
    "Signal Id 42/35/34" etc. -- those numbers were landmark ids that had
    nothing to do with the actual traffic light actors.

    The correct direction is: enumerate every traffic-signal landmark on the
    map, ask CARLA which actor it maps to via world.get_traffic_light(), and
    invert that into actor_id -> landmark.id (a string, which is the real
    OpenDRIVE "Signal Id" the adapter expects).
    """
    mapping: dict[int, str] = {}

    try:
        landmarks = carla_map.get_all_landmarks_of_type("1000001")
    except AttributeError:
        landmarks = []

    for lm in landmarks:
        try:
            tl_actor = world.get_traffic_light(lm)
        except RuntimeError:
            tl_actor = None
        if tl_actor is not None:
            mapping[tl_actor.id] = lm.id

    return mapping


def get_stop_waypoint_heading(tl: "carla.TrafficLight"):
    """Heading of the lane a signal controls. Prefers affected-lane
    waypoints (consistent with get_junction_id), falls back to stop
    waypoints, then the signal head actor's own rotation as a last resort."""
    try:
        affected_wps = tl.get_affected_lane_waypoints()
    except AttributeError:
        affected_wps = []
    if affected_wps:
        return affected_wps[0].transform.rotation.yaw

    try:
        stop_wps = tl.get_stop_waypoints()
    except AttributeError:
        stop_wps = []
    if stop_wps:
        return stop_wps[0].transform.rotation.yaw

    return tl.get_transform().rotation.yaw


def extract_map_data(
    world: carla.World,
    num_waypoints: int = 6,
    main_headings: dict[int, float] | None = None,
) -> tuple[str, dict]:
    """Extracts geodetic position and signal mappings PER JUNCTION, and

    returns both the phaseSignalMappings XML and the intersections JSON.
    """
    carla_map = world.get_map()
    main_headings = main_headings or {}

    print("\n" + "=" * 60)
    print(f"Extracting configuration for map: {carla_map.name}")
    print("=" * 60)

    origin_geo = carla_map.transform_to_geolocation(carla.Location(x=0, y=0, z=0))
    print("\n1. GEODETIC ORIGIN (x=0, y=0, z=0):")
    print(f"   Latitude:  {origin_geo.latitude:.6f}\u00b0")
    print(f"   Longitude: {origin_geo.longitude:.6f}\u00b0")

    traffic_lights = world.get_actors().filter("traffic.traffic_light")
    print(
        f"\n2. Found {len(traffic_lights)} traffic light actors. Grouping by junction..."
    )

    signal_id_map = build_actor_to_signal_id_map(world, carla_map)
    print(
        f"   Resolved {len(signal_id_map)}/{len(traffic_lights)} actor->signalId "
        f"mappings via landmark reverse-lookup."
    )

    junctions: dict[int, list[dict]] = defaultdict(list)
    unassigned = []

    for tl in traffic_lights:
        jid = get_junction_id(tl)

        try:
            signal_id = tl.get_sign_id()
        except AttributeError:
            signal_id = None

        if not signal_id:
            signal_id = signal_id_map.get(tl.id)

        if not signal_id:
            print(
                f"   WARNING: could not resolve OpenDRIVE sign id for actor "
                f"{tl.id}; falling back to actor id (adapter lookup will "
                f"likely fail for this signal -- verify manually)."
            )
            signal_id = str(tl.id)

        heading = get_stop_waypoint_heading(tl)
        geo_loc = carla_map.transform_to_geolocation(tl.get_transform().location)

        record = {
            "actor_id": tl.id,
            "signal_id": signal_id,
            "heading": heading,
            "geo": geo_loc,
            "loc": tl.get_transform().location,
        }

        if jid is None:
            unassigned.append(record)
        else:
            junctions[jid].append(record)

    if unassigned:
        print(
            f"   WARNING: {len(unassigned)} traffic light(s) had no resolvable junction:"
        )
        for r in unassigned:
            tl_actor = world.get_actor(r["actor_id"])
            try:
                n_affected = len(tl_actor.get_affected_lane_waypoints())
            except AttributeError:
                n_affected = "n/a"
            try:
                n_stop = len(tl_actor.get_stop_waypoints())
            except AttributeError:
                n_stop = "n/a"
            print(
                f"      Actor {r['actor_id']}: affected_lane_waypoints={n_affected}, "
                f"stop_waypoints={n_stop}, loc={r['loc']}"
            )
        print(
            "   Skipped -- inspect manually (these may be decorative/warning "
            "signals, or too far from the nearest junction polygon)."
        )

    print(f"   Resolved {len(junctions)} distinct junctions:")
    for jid, recs in junctions.items():
        print(
            f"      Junction {jid}: {len(recs)} signal(s) "
            f"(actors {[r['actor_id'] for r in recs]})"
        )

    config_blocks = []
    controllers_xml_list = []
    intersections_json = {"intersections": []}

    for idx, (jid, recs) in enumerate(sorted(junctions.items()), start=1):
        name = f"J{jid:03d}"

        controller_entry = (
            f'    <intersectionSignalController name="{name}" adapterType="spat-adapter" adapterName="SPAT-1" lvcIndicator="Live">\n'
            f"      <userData>\n"
            f"        <CARLA>\n"
            f"          <controllers>\n"
            f'            <controller name="" id="{idx}"/>\n'
            f"          </controllers>\n"
            f"        </CARLA>\n"
            f"      </userData>\n"
            f"    </intersectionSignalController>"
        )
        controllers_xml_list.append(controller_entry)

        avg_lat = sum(r["geo"].latitude for r in recs) / len(recs)
        avg_lon = sum(r["geo"].longitude for r in recs) / len(recs)

        default_main_heading = recs[0]["heading"]
        main_heading = main_headings.get(jid, default_main_heading)

        mappings_xml = ""
        main_phases = set()
        side_phases = set()

        for r in recs:
            direction, phase = get_cardinal_direction(r["heading"], main_heading)

            mappings_xml += (
                f"      <!-- {direction}, Actor {r['actor_id']} -->\n"
                f'      <controller name="" id="">\n'
                f'        <control signalId="{r["signal_id"]}" type="">\n'
                f"          <userData><phase>{phase}</phase></userData>\n"
                f"        </control>\n"
                f"      </controller>\n"
            )

            if phase in (2, 6):
                main_phases.add(phase)
            else:
                side_phases.add(phase)

        block = (
            f'    <configuration name="{name} Configuration" controllerName="{name}">\n'
            f'      <GeodeticPosition latitudeInDegrees="{avg_lat:.6f}" longitudeInDegrees="{avg_lon:.6f}" heightAboveEllipsoidInMeters="0">\n'
            f"      </GeodeticPosition>\n"
            f"{mappings_xml}"
            f"    </configuration>"
        )
        config_blocks.append(block)

        intersections_json["intersections"].append(
            {
                "id": idx,
                "junction_id": jid,
                "main_phase_groups": sorted(main_phases),
                "side_phase_groups": sorted(side_phases),
            }
        )

    controllers_xml = "\n\n".join(controllers_xml_list)
    configs_block = "\n\n".join(config_blocks)

    xml_template = f"""<intersectionSignalControllers>
{controllers_xml}
</intersectionSignalControllers>

<phaseSignalMappings>
{configs_block}
</phaseSignalMappings>

<simulations>
  <simulation name="DEFAULT-1" type="CARLA">
    <WeatherState>ClearNoon</WeatherState>
  </simulation>
</simulations>
"""

    return xml_template, intersections_json


def parse_main_headings(raw: str | None) -> dict[int, float]:
    """Parse '--main-headings 12=90,45=0' into {12: 90.0, 45: 0.0}."""
    result: dict[int, float] = {}
    if not raw:
        return result
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        jid_str, heading_str = pair.split("=")
        result[int(jid_str)] = float(heading_str)
    return result


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
        "-m", "--map", help="load a new map (e.g., Town10HD_Opt or Town10)"
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
    argparser.add_argument(
        "--json-output",
        metavar="JSON_PATH",
        help="save extracted intersections JSON directly to a file",
    )
    argparser.add_argument(
        "--main-headings",
        metavar="JID=HEADING[,JID=HEADING...]",
        help=(
            "Override the 'main street' compass heading (degrees) used to split "
            "phases into main/side per junction, e.g. '12=90,45=0'. Junctions not "
            "listed default to the heading of their first detected signal, which "
            "you should sanity-check against the printed direction labels."
        ),
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

    main_headings = parse_main_headings(args.main_headings)
    xml_output, intersections_json = extract_map_data(
        world, main_headings=main_headings
    )

    print("\n" + "=" * 60)
    print("4. GENERATED CONFIGURATION XML:")
    print("=" * 60)
    print(xml_output)

    print("\n" + "=" * 60)
    print("5. GENERATED INTERSECTIONS JSON:")
    print("=" * 60)
    print(json.dumps(intersections_json, indent=2))

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(xml_output, encoding="utf-8")
        print(f"\nSuccessfully wrote configuration XML to {out_path.resolve()}")

    if args.json_output:
        json_path = Path(args.json_output)
        json_path.write_text(json.dumps(intersections_json, indent=2), encoding="utf-8")
        print(f"Successfully wrote intersections JSON to {json_path.resolve()}")
    elif args.output:
        default_json_path = Path(args.output).with_suffix(".json")
        default_json_path.write_text(
            json.dumps(intersections_json, indent=2), encoding="utf-8"
        )
        print(f"Successfully wrote intersections JSON to {default_json_path.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user. Bye!")
    except RuntimeError as e:
        print(f"CARLA Error: {e}")
