import sys
import argparse
import json
import math

from pyproj import CRS, Transformer

from find_carla_egg import find_carla_egg

carla_egg_file = find_carla_egg()

sys.path.append(carla_egg_file)

import carla

MAP_LAT, MAP_LON = 39.68854712116352, -75.74805413881644

LANE_COLORS = {
    "Vehicle": carla.Color(0, 255, 0),
    "Bike": carla.Color(0, 150, 255),
    "Pedestrian": carla.Color(255, 200, 0)
}

LIFETIME = 20.0

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

def get_coordinates_from_geojson(geojson):
    vectors = parse_fc(child["vectors"])
    lanes = parse_fc(child["lanes"])
    boxes = parse_fc(child["box"])

    return vectors, boxes, lanes

def get_coordinates_from_json(json):
    return

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

try:
    client = carla.Client(args.host, args.port)
    client.set_timeout(5.0)
    world = client.get_world()
    dbg = world.debug

    transformer = setup_transformer()

    with open(args.file, "r") as f:
        child = json.load(f)

    if args.geojson:
        vectors, boxes, lanes = get_coordinates_from_geojson(child)
    else:
        vectors, boxes, lanes = get_coordinates_from_json(child)

    int_center = draw_intersection_center(dbg, transformer, vectors)

    draw_lanes(dbg, transformer, lanes)

    draw_approaches(dbg, int_center, boxes)

finally:
    print('\nDone!')