import os
import sys
import re
import argparse
import json
import math
import time

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

def mercator_to_carla(x, y, ref_x, ref_y, offset_x=0, offset_y=0):
    Xc = x - ref_x + offset_x
    Yc = -(y - ref_y) + offset_y
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

    ref_x, ref_y = ref_feature["geometry"]["coordinates"]
    carla_offset_x = -377.653805
    carla_offset_y = 756.960938

    LANE_COLORS = {
        "Vehicle": carla.Color(0, 255, 0),
        "Bike": carla.Color(0, 150, 255),
        "Pedestrian": carla.Color(255, 200, 0)
    }

    for feature in lanes["features"]:
        geom = feature["geometry"]
        if geom["type"] != "LineString":
            continue

        props = feature["properties"]
        lane_type = props.get("laneType", "Vehicle")
        lane_num = props.get("laneNumber", "?")

        color = LANE_COLORS.get(lane_type, carla.Color(200, 200, 200))
        coords = geom["coordinates"]

        for i in range(len(coords) - 1):
            x1, y1 = mercator_to_carla(*coords[i], ref_x, ref_y, carla_offset_x, carla_offset_y)
            x2, y2 = mercator_to_carla(*coords[i+1], ref_x, ref_y, carla_offset_x, carla_offset_y)

            dbg.draw_line(
                carla.Location(x1, y1, 0.35),
                carla.Location(x2, y2, 0.35),
                thickness=0.12,
                color=color,
                life_time=10.0
            )

        lx, ly = mercator_to_carla(*coords[0], ref_x, ref_y, carla_offset_x, carla_offset_y)
        dbg.draw_string(
            carla.Location(lx, ly, 0.8),
            f"Lane {lane_num}",
            draw_shadow=False,
            color=color,
            life_time=10.0,
            persistent_lines=True
        )

    for feature in boxes["features"]:
        geom = feature["geometry"]
        if geom["type"] != "Polygon":
            continue

        approach = feature["properties"]["approaches"][0]["approachType"]
        color = carla.Color(255, 0, 0) if approach == "Ingress" else carla.Color(0, 0, 255)

        poly = geom["coordinates"][0]

        for i in range(len(poly)):
            x1, y1 = mercator_to_carla(*poly[i], ref_x, ref_y, carla_offset_x, carla_offset_y)
            x2, y2 = mercator_to_carla(*poly[(i+1) % len(poly)], ref_x, ref_y, carla_offset_x, carla_offset_y)

            dbg.draw_line(
                carla.Location(x1, y1, 0.15),
                carla.Location(x2, y2, 0.15),
                thickness=0.08,
                color=color,
                life_time=10.0
            )

finally:
    print('\nDone!')