#!/usr/bin/env python3

# System imports
import sys
import numpy as np
import json
import itertools

# Import CARLA API and locate the active runtime
from find_carla_egg import find_carla_egg
carla_egg_file = find_carla_egg()
sys.path.append(carla_egg_file)
import carla

################################################################################
## Types
################################################################################

class CarlaColor:
    GRAY = carla.Color(r=102,g=153,b=204)
    GREEN = carla.Color(r=0,g=106,b=78)
    YELLOW = carla.Color(r=255,g=225,b=53)
    RED = carla.Color(r=227,g=0,b=34)
    ORANGE = carla.Color(r=255,g=103,b=0)

class Segment:
    def __init__(self, segment_name, startx, starty, startz, endx, endy, endz, color):
        self.segment_name = segment_name
        self.startx = startx
        self.starty = starty
        self.startz = startz
        self.endx = endx
        self.endy = endy
        self.endz = endz
        self.color = color

################################################################################
## Functions
################################################################################

def ingest_map_data_from_map_file(intersection_map_json_filename):
    return json.load(open(intersection_map_json_filename, "r"))

def get_reference_point_in_carla_coordinates(intersection_map_json):
    referenceLat = float(intersection_map_json["mapData"]["intersectionGeometry"]["referencePoint"]["referenceLat"])
    referenceLon = float(intersection_map_json["mapData"]["intersectionGeometry"]["referencePoint"]["referenceLon"])
    referenceElevation = float(intersection_map_json["mapData"]["intersectionGeometry"]["referencePoint"]["referenceElevation"])
    referencePointLatLon = carla.GeoLocation(referenceLat, referenceLon, referenceElevation)
    referencePointXYZ = carla.Location(262, -183, 1)
    # referencePointXYZ = world.get_map().transform_to_xyz(referencePointLatLon)
    # https://github.com/carla-simulator/carla/issues/2737
    # <geoReference>+proj=tmerc +lat_0=49 +lon_0=8 +k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +geoidgrids=egm96_15.gtx +vunits=m +no_defs </geoReference>
    return referencePointXYZ

def ingest_points_from_map_data(intersection_map_json):
    intersectionID = intersection_map_json["mapData"]["intersectionGeometry"]["referencePoint"]["intersectionID"]
    referenceLat = float(intersection_map_json["mapData"]["intersectionGeometry"]["referencePoint"]["referenceLat"])
    referenceLon = float(intersection_map_json["mapData"]["intersectionGeometry"]["referencePoint"]["referenceLon"])
    referenceElevation = float(intersection_map_json["mapData"]["intersectionGeometry"]["referencePoint"]["referenceElevation"])

    print("Intersection ID: %s"%(intersectionID))
    print("Reference Point: %f deg %f deg %f m"%(referenceLat, referenceLon, referenceElevation))

    approachList = intersection_map_json["mapData"]["intersectionGeometry"]["laneList"]["approach"]
    segmentList = list(map(lambda approach:
                    list(map(lambda lane:
                        list(map(lambda segmentPair: Segment(
                            "approachID-%s-laneID-%s" % (approach["approachID"], lane["laneID"]),
                            float(segmentPair[0]["nodeLat"]), float(segmentPair[0]["nodeLong"]), float(segmentPair[0]["nodeElev"]),
                            float(segmentPair[1]["nodeLat"]), float(segmentPair[1]["nodeLong"]), float(segmentPair[1]["nodeElev"]),
                            CarlaColor.GREEN if approach["approachType"] == "Ingress" else CarlaColor.ORANGE),

                            list(zip(lane["laneNodes"][:-1], lane["laneNodes"][1:]))  # segmentPairs
                            )),
                        approach["drivingLanes"]))
                    if (approach["approachType"] == "Ingress" or approach["approachType"] == "Egress")
                    else [],
                    approachList)
                )

    # No robust option to unwrap a nested list-of-lists in Python; these two calls are intentional.
    segmentList = list(itertools.chain.from_iterable(segmentList))
    segmentList = list(itertools.chain.from_iterable(segmentList))

    for segment in segmentList: 
        print("Segment sx %f ex %f "%(segment.startx, segment.endx))

    return segmentList

def draw_segment_list(segmentList, translation):
    for segment in segmentList:
        draw_line_segment(segment, translation)

def draw_line_segment(segment, translation):

    translation=carla.Location(x=47910.277344, y=-118664.242188, z=0)
    translation = translation + carla.Location(x=266.524994, y=-172.725006, z=1.000000)
    scalingfactor = 10000

    strt_point = (carla.Location(x=segment.startx, y=segment.starty, z=0) * scalingfactor) + translation
    stop_point = (carla.Location(x=segment.endx, y=segment.endy, z=0) * scalingfactor) + translation

    print("Drawing segment: " + segment.segment_name)
    print("strt_point (x,y,z): " + str(strt_point))
    print("stop_point (x,y,z): " + str(stop_point))

    debug.draw_line(strt_point, stop_point, 0.3, segment.color, 0)

    strt_point_geo = world.get_map().transform_to_geolocation(strt_point)
    stop_point_geo = world.get_map().transform_to_geolocation(stop_point)

    print("Drawing segment: " + segment.segment_name)
    # print("strt_point (lat/lon): " + str(strt_point_geo))
    # print("stop_point (lat/lon): " + str(stop_point_geo))

def generate_points():
    lane_width=3.5
    intersection_length=20.35

    A2a = np.array([ 255.0, -180.65,    1.00])
    B4a = np.array([ 255.2, -301.50,    1.00])

    A2b = A2a + np.array([ lane_width, 0.15, 0])
    B4b = B4a + np.array([ lane_width, 0, 0])

    A4a = A2a + np.array([0, intersection_length, 0])
    A4b = A4a + np.array([ lane_width, 0, 0])

    A1a = A2a + np.array([-(intersection_length / 2.0) + 1.8, (intersection_length / 2.0) - 0.88 + (lane_width / 2.0), 0])
    A3a = A2a + np.array([ (intersection_length / 2.0) + 1.35, (intersection_length / 2.0) + (lane_width / 2.0) - 0.5, 0])
    A1b = A1a + np.array([ 0, -lane_width, 0 ])
    A3b = A3a + np.array([ 0, -lane_width, 0 ])

    C2a = A4a + np.array([ 0, 30.85, 0])
    C2b = C2a + np.array([ lane_width, 0, 0])

    D3a = A1a + np.array([-35.9, 0, 0 ])
    D3b = D3a + np.array([ 0, -lane_width, 0 ])

    E1a = A3a + np.array([ 36.4, 0, 0 ])
    E1b = E1a + np.array([ 0, -lane_width, 0 ])

    return [
        Segment("A2a_B4a", A2a[0], A2a[1], A2a[2], B4a[0], B4a[1], B4a[2], CarlaColor.GRAY),
        Segment("A2b_B4b", A2b[0], A2b[1], A2b[2], B4b[0], B4b[1], B4b[2], CarlaColor.GRAY),
        Segment("A2a_A4a", A2a[0], A2a[1], A2a[2], A4a[0], A4a[1], A4a[2], CarlaColor.GRAY),
        Segment("A2b_A4b", A2b[0], A2b[1], A2b[2], A4b[0], A4b[1], A4b[2], CarlaColor.GRAY),
        Segment("A1a_A3a", A1a[0], A1a[1], A1a[2], A3a[0], A3a[1], A3a[2], CarlaColor.GRAY),
        Segment("A1b_A3b", A1b[0], A1b[1], A1b[2], A3b[0], A3b[1], A3b[2], CarlaColor.GRAY),
        Segment("A4a_C2a", A4a[0], A4a[1], A4a[2], C2a[0], C2a[1], C2a[2], CarlaColor.GRAY),
        Segment("A4b_C2b", A4b[0], A4b[1], A4b[2], C2b[0], C2b[1], C2b[2], CarlaColor.GRAY),
        Segment("A1a_D3a", A1a[0], A1a[1], A1a[2], D3a[0], D3a[1], D3a[2], CarlaColor.GRAY),
        Segment("A1b_D3b", A1b[0], A1b[1], A1b[2], D3b[0], D3b[1], D3b[2], CarlaColor.GRAY),
        Segment("A3a_E1a", A3a[0], A3a[1], A3a[2], E1a[0], E1a[1], E1a[2], CarlaColor.GRAY),
        Segment("A3b_E1b", A3b[0], A3b[1], A3b[2], E1b[0], E1b[1], E1b[2], CarlaColor.GRAY)
    ]

################################################################################
## Main Code
################################################################################

actor_list=[]
try:
    # Initialize
    client = carla.Client("localhost", 2000)
    client.set_timeout(300.0)
    world = client.get_world()
    debug = world.debug

    print("Which operation would you like to execute?")
    print("")
    print("1. Draw lines based on the default map file (./MAP.json)")
    print("2. Draw lines based on a map file")
    print("3. Internally-generated point set")
    print("")
    selection = int(input("? "))

    if selection == 1:
        intersection_map_filename = "MAP.json"
        intersection_map_json = ingest_map_data_from_map_file(intersection_map_filename)
        intersection_map_segment_list = ingest_points_from_map_data(intersection_map_json)
        translation = get_reference_point_in_carla_coordinates(intersection_map_json)
        draw_segment_list(intersection_map_segment_list, translation)

    elif selection == 2:
        intersection_map_filename = input("What is the filename? ")
        intersection_map_json = ingest_map_data_from_map_file(intersection_map_filename)
        intersection_map_segment_list = ingest_points_from_map_data(intersection_map_json)
        translation = get_reference_point_in_carla_coordinates(intersection_map_json)
        draw_segment_list(intersection_map_segment_list, translation)

    elif selection == 3:
        segment_list = generate_points()
        draw_segment_list(segment_list, carla.Location(0.0, 0.0, 0.0))

    else:
        print("Invalid selection. Exiting.")
        exit(1)

finally:
    print("Cleaning up actors...")
    for actor in actor_list:
        actor.destroy()
    print("Done, Actors cleaned-up successfully!")
