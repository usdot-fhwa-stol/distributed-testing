import sys
import argparse
import json
import socket
import J2735_201603_2023_06_22 as J2735
import binascii as ba

from pyproj import CRS, Transformer

from find_carla_egg import find_carla_egg

carla_egg_file = find_carla_egg()

sys.path.append(carla_egg_file)

import carla

LANE_COLORS = {
    "Vehicle": carla.Color(0, 255, 0),
    "Bike": carla.Color(0, 150, 255),
    "Pedestrian": carla.Color(255, 200, 0)
}

LIFETIME = 30.0

POINT_LAT = 39.681598395740764
POINT_LONG = -75.75374507537425

STREAMER_HOST = '192.168.55.237'
STREAMER_PORT = 8005

argparser = argparse.ArgumentParser(
    description=__doc__)
argparser.add_argument(
    '--host',
    metavar='H',
    default='127.0.0.1',
    help='IP of the host server (default: 127.0.0.1)')
argparser.add_argument(
    '-p', '--port',
    metavar='P',
    default=2000,
    type=int,
    help='TCP port to listen to (default: 2000)')
argparser.add_argument(
    '-f', '--file',
    metavar='f',
    type=str,
    help='Import file to read crossing data')
argparser.add_argument(
    '-g', '--geojson',
    action='store_true',
    help='Indicates that the input file is GeoJSON. If not present, assumes plain JSON.'
)
argparser.add_argument(
    '-l', '--live',
    action='store_true',
    help='Indicates that the program should be run live, taking updates from received map JSONs'
)
args = argparser.parse_args()

def parse_fc(raw):
    return json.loads(raw)

def setup_transformer():
    CRS_TMerc = CRS.from_proj4(
        "+proj=tmerc +lat_0=39.68854712116352 +lon_0=-75.748054413881644 "
        "+k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
    )

    CRS_WGS84 = CRS.from_epsg(4326)

    return Transformer.from_crs(CRS_WGS84, CRS_TMerc, always_xy=True)

def decode_j2735(input_hex):
    #print(f'input_hex:  {input_hex}')
    try:
        #specify message type inside J2735.py
        decoded_msg = J2735.DSRC.MessageFrame
        
        # convert from hex using unhexlify then from uper using library
        decoded_msg.from_uper(ba.unhexlify(input_hex))
        
        #format data into json
        decoded_msg_json = json.loads(decoded_msg.to_json())

        return decoded_msg_json
    except Exception as err:
        print(f"Unexpected error: {err}")
        return "ERROR"

def get_coordinates_from_geojson(geojson):
    vectors = parse_fc(child["vectors"])
    lanes = parse_fc(child["lanes"])
    boxes = parse_fc(child["box"])

    return vectors, boxes, lanes

def get_coordinates_from_json(json):
    intersection = json["mapData"]["intersectionGeometry"]

    vectors = {
        "features": [
            {
                "geometry": {
                    "type": "Point",
                    "coordinates": [0,0]
                },
                "properties": {
                    "LonLat": {
                        "lat": intersection["referencePoint"]["referenceLat"],
                        "lon": intersection["referencePoint"]["referenceLon"]
                    },
                    "marker": {
                        "name": "Reference Point Marker"
                    }
                }
            }
        ]
    }

    boxes = {"features": []}
    for approach in intersection["laneList"]["approach"]:
        polygon_points = []
        for lane in approach.get("drivingLanes", []):
            for node in lane.get("laneNodes", []):
                polygon_points.append([node["nodeLong"], node["nodeLat"]])
        if polygon_points:
            boxes["features"].append({
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [polygon_points]
                },
                "properties": {
                    "approaches": [
                        {"approachType": approach["approachType"], "selected": True}
                    ]
                }
            })

    lanes = {"features": []}
    for approach in intersection["laneList"]["approach"]:
        for lane in approach.get("drivingLanes", []):
            coords = [[node["nodeLat"], node["nodeLong"]] for node in lane.get("laneNodes", [])]
            if coords:
                lanes["features"].append({
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "properties": {
                        "laneType": lane.get("laneType", "Vehicle"),
                        "laneNumber": lane.get("laneID", "?"),
                        "elevation": [{"latlon": {"lat": lat, "lon": lon}, "value": float(node.get("nodeElev", 0))}
                                      for lat, lon, node in zip([n["nodeLat"] for n in lane["laneNodes"]],
                                                                [n["nodeLong"] for n in lane["laneNodes"]],
                                                                lane["laneNodes"])]
                    }
                })

    return vectors, boxes, lanes

def get_coordinates_from_j2735(j2735):
    intersections = j2735["value"]["intersections"]
    intersection = intersections[0]

    ref_lat = intersection["refPoint"]["lat"] * 1e-7
    ref_lon = intersection["refPoint"]["long"] * 1e-7

    vectors = {
        "features": [{
            "geometry": {
                "type": "Point",
                "coordinates": [0, 0]
            },
            "properties": {
                "LonLat": {
                    "lat": ref_lat,
                    "lon": ref_lon
                },
                "marker": {
                    "name": "Reference Point Marker"
                }
            }
        }]
    }

    lanes = {"features": []}
    boxes = {"features": []}

    approach_polygons = {}

    for lane in intersection.get("laneSet", []):
        coords = []

        for node in lane["nodeList"]["nodes"]:
            lat = node["delta"]["node-LatLon"]["lat"] * 1e-7
            lon = node["delta"]["node-LatLon"]["lon"] * 1e-7
            coords.append([lat, lon])

        if not coords:
            continue

        # -------------------------
        # Lane feature
        # -------------------------
        lanes["features"].append({
            "geometry": {
                "type": "LineString",
                "coordinates": coords
            },
            "properties": {
                "laneType": "Vehicle",
                "laneNumber": lane.get("laneID", "?"),
                "maneuvers": lane.get("maneuvers"),
                "elevation": [{
                    "latlon": {"lat": lat, "lon": lon},
                    "value": float(intersection["refPoint"].get("elevation", 0))
                } for lat, lon in coords]
            }
        })

        # -------------------------
        # Boxes (approach polygons)
        # -------------------------
        approach_id = (
            lane.get("ingressApproach")
            or lane.get("egressApproach")
            or "unknown"
        )

        approach_polygons.setdefault(approach_id, [])
        approach_polygons[approach_id].extend(coords)

    # Build box features per approach
    for approach_id, polygon in approach_polygons.items():
        if len(polygon) >= 3:
            boxes["features"].append({
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [polygon]
                },
                "properties": {
                    "approaches": [{
                        "approachType": approach_id,
                        "selected": True
                    }]
                }
            })

    return vectors, boxes, lanes

def latlon_to_carla(transformer, lat, lon):
    x, y = transformer.transform(lon, lat)
    return x, -y

def draw_intersection_center(dbg, transformer, vectors):
    
    ref_feature = next(
        f for f in vectors["features"]
        if f["properties"].get("marker", {}).get("name") == "Reference Point Marker"
    )

    lat, lon = float(ref_feature["properties"]["LonLat"]["lat"]), float(ref_feature["properties"]["LonLat"]["lon"])
    x, y = latlon_to_carla(transformer, lat, lon)
    merc_x, merc_y = ref_feature["geometry"]["coordinates"]

    offset=0.3
    dbg.draw_line(
        carla.Location(x - offset, y, 0.5),
        carla.Location(x + offset, y, 0.5),
        thickness=0.2, color=carla.Color(100, 0, 0), life_time=LIFETIME
    )
    dbg.draw_line(
        carla.Location(x, y - offset, 0.5),
        carla.Location(x, y + offset, 0.5),
        thickness=0.2, color=carla.Color(100, 0, 0), life_time=LIFETIME
    )

    return x, y, merc_x, merc_y

def draw_approaches(dbg, int_center, boxes):
    int_carla_x = int_center[0]
    int_carla_y = int_center[1]
    int_merc_x = int_center[2]
    int_merc_y = int_center[3]

    for feature in boxes["features"]:
        geom = feature["geometry"]
        if geom["type"] != "Polygon":
            continue

        approach_type = feature["properties"]["approaches"][0]["approachType"]
        color = carla.Color(255, 0, 0) if approach_type == "Ingress" else carla.Color(0, 0, 255)

        polygon = feature["geometry"]["coordinates"][0]
        carla_coords = []
        for x_merc, y_merc in polygon:
            dx = x_merc - int_merc_x
            dy = y_merc - int_merc_y
            carla_x = int_carla_x + dx
            carla_y = int_carla_y - dy
            carla_coords.append((carla_x, carla_y))

        for i in range(len(carla_coords)):
            x1, y1 = carla_coords[i]
            x2, y2 = carla_coords[(i+1)%len(carla_coords)]
            dbg.draw_line(
                carla.Location(x1, y1, 0.15),
                carla.Location(x2, y2, 0.15),
                thickness=0.08,
                color=color,
                life_time=LIFETIME
            )

def draw_lanes(dbg, transformer, lanes):
    for feature in lanes["features"]:
        geom = feature["geometry"]
        if geom["type"] != "LineString":
            continue

        props = feature.get("properties", {})
        lane_type = props.get("laneType", "Vehicle")
        lane_num = props.get("laneNumber", "?")
        color = LANE_COLORS.get(lane_type, carla.Color(200,200,200))

        coords_latlon = [ (node['latlon']['lat'], node['latlon']['lon'])
                         for node in props.get('elevation',[]) ]
        
        if not coords_latlon:
            coords_latlon = geom["coordinates"]

        for i in range (len(coords_latlon) - 1):
            x1, y1 = latlon_to_carla(transformer, *coords_latlon[i])
            x2, y2 = latlon_to_carla(transformer, *coords_latlon[i+1])
            dbg.draw_line(
                carla.Location(x1, y1, 0.35),
                carla.Location(x2, y2, 0.35),
                thickness=0.12,
                color=color,
                life_time=LIFETIME
            )

        lx, ly = latlon_to_carla(transformer, *coords_latlon[0])
        dbg.draw_string(
            carla.Location(lx, ly, 0.8),
            f"Lane {lane_num}",
            color=color,
            life_time=LIFETIME
        )

def draw_world_axes(world,
                    origin=carla.Location(0.0, 0.0, 0.0),
                    length=10.0,
                    thickness=0.2,
                    arrow_size=0.8,
                    life_time=0.0,
                    persistent=False):
    """
    Draw arrows from 'origin' along +X, +Y, +Z in CARLA.
    Axis colors: X=red, Y=green, Z=blue.
    """
    dbg = world.debug

    end_x = carla.Location(origin.x + length, origin.y, origin.z)  # +X (North)
    end_y = carla.Location(origin.x, origin.y + length, origin.z)  # +Y (East)
    end_z = carla.Location(origin.x, origin.y, origin.z + length)  # +Z (Up)

    # Signature: draw_arrow(begin, end, thickness, arrow_size, color, life_time=-1.0, persistent_lines=True)
    dbg.draw_arrow(origin, end_x, thickness, arrow_size, carla.Color(255, 0, 0), float(life_time), persistent)  # X (red)
    dbg.draw_arrow(origin, end_y, thickness, arrow_size, carla.Color(0, 255, 0), float(life_time), persistent)  # Y (green)
    dbg.draw_arrow(origin, end_z, thickness, arrow_size, carla.Color(0, 0, 255), float(life_time), persistent)  # Z (blue)

    # draw_string signature varies slightly by version; this form is widely compatible:
    # draw_string(location, text, draw_shadow=False, color=Color(), life_time=-1.0, persistent_lines=True)
    dbg.draw_string(end_x, " +X", False, carla.Color(255, 0, 0), float(life_time), persistent)
    dbg.draw_string(end_y, " +Y", False, carla.Color(0, 255, 0), float(life_time), persistent)
    dbg.draw_string(end_z, " +Z", False, carla.Color(0, 0, 255), float(life_time), persistent)

try:
    client = carla.Client(args.host, args.port)
    client.set_timeout(5.0)
    world = client.get_world()
    dbg = world.debug

    transformer = setup_transformer()

    if args.live:

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        sock.bind((STREAMER_HOST, STREAMER_PORT))
        print(f"Server listening on {STREAMER_HOST}:{STREAMER_PORT} for UDP data... Press Ctrl + C to cancel...")

        while True:
            data, addr = sock.recvfrom(55555)
            try:
                json_data = json.loads(data.decode('utf-8'))

                if json_data["metadata"]["type_name"] == "DOT_OSTR::TV2XMsg::V2X" and json_data["attributes"]["messageType"] == "MAP":
                    binary_content = json_data["attributes"]["binaryContent"]
                    byte_list = [list(item.values())[0] for item in binary_content]
                    raw_bytes = bytes(byte_list)
                    map_hex = raw_bytes.hex()

                    map_json = decode_j2735(map_hex)

                    vectors, boxes, lanes = get_coordinates_from_j2735(map_json)

                    int_center = draw_intersection_center(dbg, transformer, vectors)

                    draw_lanes(dbg, transformer, lanes)

            except json.JSONDecodeError as e:
                print(f"Error decoding JSON data from {addr}: {e}")

    else:
        with open(args.file, "r") as f:
            child = json.load(f)

        if args.geojson:
            vectors, boxes, lanes = get_coordinates_from_geojson(child)
        else:
            vectors, boxes, lanes = get_coordinates_from_json(child)

        int_center = draw_intersection_center(dbg, transformer, vectors)

        draw_lanes(dbg, transformer, lanes)

    #draw_approaches(dbg, int_center, boxes)

    # point_x, point_y = latlon_to_carla(transformer, POINT_LAT, POINT_LONG)
    # print(f"x: {point_x}, y: {point_y}")
    # location = carla.Location(point_x, point_y, 0)
    # location = carla.Location(532.728759765625, 844.072448730469, 0)

    # draw_world_axes(world, origin=location, life_time=LIFETIME)

finally:
    print('\nDone!')