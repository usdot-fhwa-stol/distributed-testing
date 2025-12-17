import sys
import argparse
import json
import math

from pyproj import Transformer

from find_carla_egg import find_carla_egg

carla_egg_file = find_carla_egg()

sys.path.append(carla_egg_file)

import carla

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
args = argparser.parse_args()

def parse_fc(raw):
    return json.loads(raw)

def latlon_to_mercator(lat, lon):
    R = 6378137.0
    x = R * math.radians(lon)
    y = R * math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))
    print(f"Old Mercator: x={x}, y={y}")

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3785", always_xy=True)
    x, y = transformer.transform(MAP_LON, MAP_LAT)
    print(f"New Mercator: x={x}, y={y}")

    return x, y

def mercator_to_carla(x, y, map_x, map_y):
    Xc = x - map_x
    Yc = -(y - map_y)
    return Xc, Yc

try:
    client = carla.Client(args.host, args.port)
    client.set_timeout(5.0)
    world = client.get_world()
    dbg = world.debug

    with open(args.file, "r") as f:
        child = json.load(f)

    vectors = parse_fc(child["vectors"])
    lanes = parse_fc(child["lanes"])
    boxes = parse_fc(child["box"])

    ref_feature = next(
        f for f in vectors["features"]
        if f["properties"].get("marker", {}).get("name") == "Reference Point Marker"
    )

    MAP_LAT = 39.68854712116352
    MAP_LON = -75.74805413881644

    map_x, map_y = latlon_to_mercator(MAP_LAT, MAP_LON)

    ref_x, ref_y = ref_feature["geometry"]["coordinates"]

    int_x, int_y = mercator_to_carla(ref_x, ref_y, map_x, map_y)

    print("CARLA origin Mercator:", map_x, map_y)
    print("Reference point Mercator:", ref_x, ref_y)
    print("Intersection CARLA coords:", int_x, int_y)
    x0, y0 = mercator_to_carla(map_x, map_y, map_x, map_y)
    print(f"CARLA origin in CARLA coords: x={x0}, y={y0}")

    LANE_COLORS = {
        "Vehicle": carla.Color(0, 255, 0),
        "Bike": carla.Color(0, 150, 255),
        "Pedestrian": carla.Color(255, 200, 0)
    }

    for feature in lanes["features"]:
        geom = feature["geometry"]
        if geom["type"] != "LineString":
            continue

        props = feature.get("properties", {})
        lane_type = props.get("laneType", "Vehicle")
        lane_num = props.get("laneNumber", "?")
        color = LANE_COLORS.get(lane_type, carla.Color(200,200,200))

        coords = geom["coordinates"]

        for i in range(len(coords) - 1):
            x1, y1 = mercator_to_carla(
                coords[i][0], coords[i][1],
                map_x, map_y
            )
            x2, y2 = mercator_to_carla(
                coords[i + 1][0], coords[i + 1][1],
                map_x, map_y
            )

            dbg.draw_line(
                carla.Location(x1, y1, 0.35),
                carla.Location(x2, y2, 0.35),
                thickness=0.12,
                color=color,
                life_time=10.0
            )

        lx, ly = mercator_to_carla(
            coords[0][0], coords[0][1],
            map_x, map_y
        )

        dbg.draw_string(
            carla.Location(lx, ly, 0.8),
            f"Lane {lane_num}",
            color=color,
            life_time=10
        )

    for feature in boxes["features"]:
        geom = feature["geometry"]
        if geom["type"] != "Polygon":
            continue

        approach = feature["properties"]["approaches"][0]["approachType"]
        color = carla.Color(255, 0, 0) if approach == "Ingress" else carla.Color(0, 0, 255)

        poly = geom["coordinates"][0]

        for i in range(len(poly)):
            x1, y1 = mercator_to_carla(
                poly[i][0], poly[i][1],
                map_x, map_y)
            x2, y2 = mercator_to_carla(
                poly[(i+1) % len(poly)][0], poly[(i+1) % len(poly)][1],
                map_x, map_y)

            dbg.draw_line(
                carla.Location(x1, y1, 0.15),
                carla.Location(x2, y2, 0.15),
                thickness=0.08,
                color=color,
                life_time=10.0
            )

    location = carla.Location(0.0, 0.0, 0.0)
    dbg.draw_point(
        location,
        size=0.1,
        color=carla.Color(255,0,0),
        life_time=10
    )

    geo_location = world.get_map().transform_to_geolocation(location)
    print(f"Origin Geolocation Lat: {geo_location.latitude}")
    print(f"Origin Geolocation Lon: {geo_location.longitude}")
    print(f"Origin From XML: {MAP_LAT}, {MAP_LON}")

    lon = ref_feature["properties"]["LonLat"]["lon"]
    lat = ref_feature["properties"]["LonLat"]["lat"]

    print(f"Lat: {lat} Lon: {lon}")

    mx_calc, my_calc = latlon_to_mercator(lat, lon)
    mx_geo, my_geo = ref_feature["geometry"]["coordinates"]

    print("dx: ", mx_geo - mx_calc)
    print("dy: ", my_geo - my_calc)

    del3_geo_location = world.get_map().transform_to_geolocation(carla.Location(-377.653805, 756.960938, 0))
    print(f"del3 Lat: {del3_geo_location.latitude}")
    print(f"del3 Lon: {del3_geo_location.longitude}")
    

finally:
    print('\nDone!')