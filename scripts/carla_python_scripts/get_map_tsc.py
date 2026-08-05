import argparse
import json
import math
import socket
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compass bearing (0-360) from point 1 to point 2."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def get_turn_type(tl: "carla.TrafficLight") -> str:
    """Classify the movement a signal controls as 'left', 'through', or
    'right' by comparing the lane's heading before the junction to its
    heading after the junction (a static heading alone can't tell a
    through lane from a left-turn lane pointed the same direction).

    This is fully generic geometry -- no per-map assumptions.
    """
    try:
        affected_wps = tl.get_affected_lane_waypoints()
    except AttributeError:
        affected_wps = []

    for wp in affected_wps:
        entry_heading = wp.transform.rotation.yaw
        # Walk forward through the junction to find the exit lane.
        cur = wp
        exit_wp = None
        for _ in range(40):
            nxts = cur.next(2.0)
            if not nxts:
                break
            cur = nxts[0]
            if not cur.is_junction:
                exit_wp = cur
                break
        if exit_wp is None:
            continue

        exit_heading = exit_wp.transform.rotation.yaw
        delta = (exit_heading - entry_heading + 540) % 360 - 180  # -180..180

        if delta <= -30:
            return "left"
        elif delta >= 30:
            return "right"
        else:
            return "through"

    return "through"  # default: can't determine turn geometry, assume through


def get_cardinal_direction(
    heading: float, main_heading: float, turn_type: str = "through"
) -> Tuple[str, int]:
    """Map a lane heading + turn type to a full NEMA dual-ring phase number,
    relative to this intersection's main-street heading.

    main_heading is the compass heading (degrees, 0-360) of the "main street"
    through movement for THIS intersection.

    NEMA convention used here:
        MAIN-A through/right -> 2   MAIN-A left -> 1
        MAIN-B through/right -> 6   MAIN-B left -> 5
        SIDE-A through/right -> 4   SIDE-A left -> 3
        SIDE-B through/right -> 8   SIDE-B left -> 7
    Right turns are typically permitted concurrently with the through phase
    on the same approach, so they share its even phase number.
    """
    heading = (heading + 360) % 360
    rel = (heading - main_heading + 360) % 360

    if 45 <= rel < 135:
        label, through_phase, left_phase = "SIDE-A", 4, 3
    elif 135 <= rel < 225:
        label, through_phase, left_phase = "MAIN-B", 6, 5
    elif 225 <= rel < 315:
        label, through_phase, left_phase = "SIDE-B", 8, 7
    else:
        label, through_phase, left_phase = "MAIN-A", 2, 1

    if turn_type == "left":
        return label, left_phase
    return label, through_phase


def get_junction_id(tl: "carla.TrafficLight") -> Optional[int]:
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


def build_actor_to_signal_id_map(world: "carla.World", carla_map: "carla.Map") -> Dict[int, str]:
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
    mapping: Dict[int, str] = {}

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


def get_lane_key(tl: "carla.TrafficLight") -> Optional[Tuple[int, int]]:
    """(road_id, lane_id) of the lane a signal controls, used to detect
    duplicate signal heads (e.g. near/far bulbs) governing the same lane
    so only one mapping entry is emitted per real movement."""
    try:
        affected_wps = tl.get_affected_lane_waypoints()
    except AttributeError:
        affected_wps = []
    if affected_wps:
        wp = affected_wps[0]
        return (wp.road_id, wp.lane_id)
    return None


def get_stop_waypoint_heading(tl: "carla.TrafficLight") -> float:
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
    main_headings: Optional[Dict[int, float]] = None,
    name_prefix: str = "J",
    junction_order: str = "junction_id",
    extra_signals_by_jid: Optional[Dict[int, List[dict]]] = None,
    exclude_from_json: Optional[List[int]] = None,
) -> Tuple[str, dict]:
    """Extracts geodetic position and signal mappings PER JUNCTION, and

    returns both the phaseSignalMappings XML and the intersections JSON.

    All phase/turn/lane-dedup logic is fully generic (derived from CARLA
    map geometry) and works for any map. The last three parameters exist
    only for the handful of facts geometry genuinely can't tell you --
    e.g. "this junction sits off the corridor and is unused" or "this
    signal head is a warning repeater for another intersection" -- and
    default to empty/no-op, so behavior is identical across maps unless
    you explicitly pass them.
    """
    carla_map = world.get_map()
    main_headings = main_headings or {}
    extra_signals_by_jid = extra_signals_by_jid or {}
    exclude_from_json = set(exclude_from_json or [])

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

    junctions: Dict[int, List[dict]] = defaultdict(list)
    unassigned = []

    for tl in traffic_lights:
        jid = get_junction_id(tl)

        try:
            signal_id = tl.get_opendrive_id()
        except AttributeError:
            signal_id = None

        if not signal_id:
            signal_id = signal_id_map.get(tl.id)

        if not signal_id:
            print(
                f"   WARNING: could not resolve a real OpenDRIVE signal id for "
                f"actor {tl.id}; skipping it (this actor isn't a real, "
                f"independently-controllable signal head -- including it under "
                f"its internal actor id would fabricate a movement that "
                f"doesn't exist in the adapter's config)."
            )
            continue

        heading = get_stop_waypoint_heading(tl)
        turn_type = get_turn_type(tl)
        lane_key = get_lane_key(tl)
        geo_loc = carla_map.transform_to_geolocation(tl.get_transform().location)

        record = {
            "actor_id": tl.id,
            "signal_id": signal_id,
            "heading": heading,
            "turn_type": turn_type,
            "lane_key": lane_key,
            "geo": geo_loc,
            "loc": tl.get_transform().location,
        }

        if jid is None:
            unassigned.append(record)
        else:
            junctions[jid].append(record)

    # De-duplicate signal heads that control the exact same lane (e.g. a
    # near/far bulb pair for one movement) so only one mapping entry is
    # emitted per real movement. Keeps the first one seen.
    for jid, recs in junctions.items():
        seen_lanes = set()
        deduped = []
        for r in recs:
            key = r["lane_key"]
            if key is not None:
                if key in seen_lanes:
                    print(
                        f"   Dropping duplicate signal head: actor {r['actor_id']} "
                        f"(signal {r['signal_id']}) controls the same lane "
                        f"{key} as an already-seen signal in junction {jid}."
                    )
                    continue
                seen_lanes.add(key)
            deduped.append(r)
        junctions[jid] = deduped

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

    # Precompute every junction's average geo position up front -- needed
    # both for longitude ordering and for the nearest-neighbor main-heading
    # default below.
    avg_geo_by_jid: Dict[int, Tuple[float, float]] = {
        jid: (
            sum(r["geo"].latitude for r in recs) / len(recs),
            sum(r["geo"].longitude for r in recs) / len(recs),
        )
        for jid, recs in junctions.items()
    }

    def nearest_neighbor_heading(jid: int) -> Optional[float]:
        """Bearing from this junction toward its nearest neighboring
        junction. For a corridor of signals (like an arterial), this is a
        far more reliable proxy for the "main street" direction than the
        heading of an arbitrary single signal, since it's derived from the
        actual layout of the intersections themselves rather than which
        traffic light actor CARLA happened to return first."""
        lat1, lon1 = avg_geo_by_jid[jid]
        best_dist = None
        best_bearing = None
        for other_jid, (lat2, lon2) in avg_geo_by_jid.items():
            if other_jid == jid:
                continue
            dist = (lat2 - lat1) ** 2 + (lon2 - lon1) ** 2
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_bearing = bearing_deg(lat1, lon1, lat2, lon2)
        return best_bearing

    if junction_order == "longitude":
        ordered_jids = sorted(junctions.keys(), key=lambda j: avg_geo_by_jid[j][1])
    else:
        ordered_jids = sorted(junctions.keys())

    for idx, jid in enumerate(ordered_jids, start=1):
        recs = junctions[jid]
        if name_prefix == "J" and junction_order == "junction_id":
            name = f"J{jid:03d}"  # original default naming, unchanged
        else:
            name = f"{name_prefix}_{idx:02d}"

        controller_entry = (
            f'    <intersectionSignalController name="{name}" adapterName="SPAT-1" lvcIndicator="Live">\n'
            f'      <controller name="" id="{idx}"/>\n'
            f"    </intersectionSignalController>"
        )
        controllers_xml_list.append(controller_entry)

        avg_lat, avg_lon = avg_geo_by_jid[jid]

        default_main_heading = nearest_neighbor_heading(jid)
        if default_main_heading is None:  # only junction on the map
            default_main_heading = recs[0]["heading"]
        main_heading = main_headings.get(jid, default_main_heading)

        mappings_xml = ""
        main_phases = set()
        side_phases = set()

        for r in recs:
            direction, phase = get_cardinal_direction(
                r["heading"], main_heading, r.get("turn_type", "through")
            )

            mappings_xml += f'      <mapping signalId="{r["signal_id"]}" phase="{phase}"/>\n'

            if phase in (1, 2, 5, 6):
                main_phases.add(phase)
            else:
                side_phases.add(phase)

        for extra in extra_signals_by_jid.get(jid, []):
            note = extra.get("note")
            if note:
                mappings_xml += f"      <!-- {note} -->\n"
            mappings_xml += f'      <mapping signalId="{extra["signal_id"]}" phase="{extra["phase"]}"/>\n'
            if extra["phase"] in (1, 2, 5, 6):
                main_phases.add(extra["phase"])
            else:
                side_phases.add(extra["phase"])

        block = (
            f'    <configuration name="{name} Configuration" controllerName="{name}">\n'
            f'      <GeodeticPosition latitudeInDegrees="{avg_lat:.6f}" longitudeInDegrees="{avg_lon:.6f}" heightAboveEllipsoidInMeters="0"/>\n'
            f"{mappings_xml}"
            f"    </configuration>"
        )
        config_blocks.append(block)

        if jid in exclude_from_json:
            continue

        intersections_json["intersections"].append(
            {
                "id": idx,
                "main_phase_groups": sorted(main_phases) if main_phases else [0],
                "side_phase_groups": sorted(side_phases) if side_phases else [0],
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
"""

    return xml_template, intersections_json


def parse_main_headings(raw: Optional[str]) -> Dict[int, float]:
    """Parse '--main-headings 12=90,45=0' into {12: 90.0, 45: 0.0}."""
    result: Dict[int, float] = {}
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
    argparser.add_argument(
        "--name-prefix",
        default="J",
        help=(
            "Prefix for generated intersection names, e.g. pass your "
            "corridor/map name (e.g. 'DelAve') to get 'DelAve_01', "
            "'DelAve_02'... in longitude order. Default 'J' keeps the "
            "map-agnostic 'J<junction_id>' naming with no map-specific input."
        ),
    )
    argparser.add_argument(
        "--junction-order",
        choices=["junction_id", "longitude"],
        default="junction_id",
        help=(
            "How to order/number junctions: by CARLA's internal junction id "
            "(default), or west-to-east by longitude (useful with "
            "--name-prefix for a corridor like 'DelAve_01'..'DelAve_09')."
        ),
    )
    argparser.add_argument(
        "--exclude-junctions",
        metavar="JID[,JID...]",
        help=(
            "Junction ids to keep in the XML but omit from the intersections "
            "JSON summary -- for junctions that are detected but not actually "
            "part of the corridor being modeled."
        ),
    )
    argparser.add_argument(
        "--extra-signal",
        metavar="JID:SIGNAL_ID:PHASE[:NOTE]",
        action="append",
        default=[],
        help=(
            "Manually add a signal mapping CARLA can't derive on its own "
            "(e.g. a warning-sign head that mirrors a downstream "
            "intersection's phase). Repeatable. Example: "
            "'128:800:2:warning sign for intersection 9'."
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

    exclude_from_json = []
    if args.exclude_junctions:
        exclude_from_json = [int(j.strip()) for j in args.exclude_junctions.split(",") if j.strip()]

    extra_signals_by_jid: Dict[int, List[dict]] = defaultdict(list)
    for raw in args.extra_signal:
        parts = raw.split(":", 3)
        if len(parts) < 3:
            print(f"ERROR: --extra-signal '{raw}' must be JID:SIGNAL_ID:PHASE[:NOTE]")
            sys.exit(1)
        jid_str, signal_id, phase_str = parts[0], parts[1], parts[2]
        note = parts[3] if len(parts) == 4 else None
        extra_signals_by_jid[int(jid_str)].append(
            {"signal_id": signal_id, "phase": int(phase_str), "note": note}
        )

    xml_output, intersections_json = extract_map_data(
        world,
        main_headings=main_headings,
        name_prefix=args.name_prefix,
        junction_order=args.junction_order,
        extra_signals_by_jid=extra_signals_by_jid,
        exclude_from_json=exclude_from_json,
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