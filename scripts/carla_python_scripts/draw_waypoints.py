import os
import sys
import re
import argparse
import json
import math
import time
from pathlib import Path

import pandas as pd
import numpy as np

from pynput import keyboard
from pynput.keyboard import Key


import carla

from agents.navigation.global_route_planner import GlobalRoutePlanner
# from agents.navigation.global_route_planner_dao import GlobalRoutePlannerDAO
# NOTE: GlobalRoutePlannerDAO was removed years ago (pre-0.9.11) - GlobalRoutePlanner
# now takes (map, sampling_resolution) directly. Kept as a historical comment.

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
    '-l', '--lifetime',
    default=10,
    type=int,
    help='Number of seconds to display each route (default: 10)')
argparser.add_argument(
    '-e', '--export',
    action='store_true',
    help='export waypoints to file (creates ~/waypoint_files dir)')
argparser.add_argument(
    '-o', '--overlay',
    action='store_true',
    help='overlay all routes on top of each other')
argparser.add_argument(
    '--output-dir',
    default='~/waypoint_files',
    help='Directory to write exported waypoint/CARMA files to (default: ~/waypoint_files)')
argparser.add_argument(
    '--follow_vehicle',
    help='Vehicle to be used for the follow cam (default: "TFHRC-MANUAL-1"')
argparser.add_argument(
    '--output_name',
    default=None,
    help='Name to use when exporting a --follow_vehicle recording '
         '(default: the --follow_vehicle rolename)')
args = argparser.parse_args()

# Resolve the output directory once, up front, so '~' is always expanded correctly
# regardless of where/how the script is invoked (this was the source of the
# "No such file or directory" / permission errors when using a raw '~' string
# with open(), since the shell - not Python - normally expands '~').
OUTPUT_DIR = Path(args.output_dir).expanduser().resolve()


# Colors
red    = carla.Color(255,   0,   0)
green  = carla.Color(  0, 255,   0)
blue   = carla.Color( 47, 210, 231)
cyan   = carla.Color(  0, 255, 255)
yellow = carla.Color(255, 255,   0)
orange = carla.Color(255, 162,   0)
white  = carla.Color(255, 255, 255)

waypoint_separation = 0.2

waypoint_size = 0.1
drawing_lifetime = args.lifetime

draw_arrow_size = 0.2
draw_arrow_thickness = 0.2
draw_arrow_z_offset = carla.Location(0,0,0)

# Key used to start/stop continuous waypoint capture. Deliberately an
# out-of-the-way function key (NOT space) since space is bound to the
# brake in the driving sim and would get hit constantly while driving
# the segment you're trying to record.
CAPTURE_TOGGLE_KEY = Key.f8

# True while we're actively sampling the follow vehicle's location into
# spawn_data["waypoints"]. Toggled on/off by CAPTURE_TOGGLE_KEY. The main
# loop (see the `while recording:` block below) checks this flag and
# appends a sample whenever it's True; on_press itself never touches
# spawn_data anymore, which avoids two threads mutating the list at once.
capturing = False

def on_press(key):
    global recording, capturing

    try:
        key_char = key.char
    except Exception:
        key_char = None

    if key == CAPTURE_TOGGLE_KEY:
        capturing = not capturing
        print(f"Waypoint capture {'STARTED' if capturing else 'STOPPED'} "
              f"(press {CAPTURE_TOGGLE_KEY} again to "
              f"{'stop' if capturing else 'start'})")
    elif key == Key.delete:
        print("Removing waypoint")

        if len(spawn_data["waypoints"]) > 0:
            spawn_data["waypoints"].pop()
        else:
            print("No waypoints to remove")
    elif key == Key.enter:
        capturing = False
        recording = False
        print("Done adding waypoints")
        print(f"Waypoints:")
        for waypoint in spawn_data["waypoints"]:
            print(f"\tx: {waypoint.x} y: {waypoint.y} z: {waypoint.z}")


def get_veh_with_name(veh_rolename):
    player = None
    carlaVehicles = world.get_actors().filter('vehicle.*')
    for vehicle in carlaVehicles:
        currentAttributes = vehicle.attributes
        # print("Checking vehicle: " + str(currentAttributes["role_name"]))
        if currentAttributes["role_name"] == veh_rolename:
            player = vehicle
    if not player:
        print("ERROR: Unable to find vehicle with rolename: " + veh_rolename)
        sys.exit()
    
    return player

def get_road_grade(start_point,end_point,mid_point):

    print(f'mid_point: {mid_point[0].transform}')
    
    run = math.sqrt((end_point[0].transform.location.x - start_point[0].transform.location.x)**2 + (end_point[0].transform.location.y - start_point[0].transform.location.y)**2 )
    print(f'\nrun: {run}')
    rise = end_point[0].transform.location.z - start_point[0].transform.location.z
    print(f'rise: {rise}')

    if run == 0:
        grade = 0
    else:
        grade = rise/run*100

    # world.debug.draw_arrow(
    #     mid_point[0].transform.location + draw_arrow_z_offset, 
    #     mid_point[0].transform.location + mid_point[0].transform.get_forward_vector() + draw_arrow_z_offset,
    #     thickness=draw_arrow_thickness, 
    #     arrow_size=draw_arrow_size, 
    #     color=carla.Color(r=0, g=50, b=255), 
    #     life_time=drawing_lifetime)
    
    world.debug.draw_string(mid_point[0].transform.location,str(grade), draw_shadow=False,color = carla.Color(r=0, g=255, b=0), life_time=drawing_lifetime,persistent_lines=True)


    print(f'grade: {grade}')

def draw_waypoint_info(debug, w, lt=drawing_lifetime, x_offset=0,draw_data=False):
    w_loc = w.transform.location
    # debug.draw_point(w_loc, waypoint_size, red, lt)
    world.debug.draw_arrow(
                    w.transform.location + draw_arrow_z_offset, 
                    w.transform.location + w.transform.get_forward_vector() + draw_arrow_z_offset,
                    thickness=draw_arrow_thickness, 
                    arrow_size=draw_arrow_size, 
                    color=red, 
                    life_time=drawing_lifetime)
    if draw_data:
        debug.draw_string(w_loc + carla.Location(x=x_offset,z=0.5),  f"lane: {w.lane_id}", False, yellow, lt)
        debug.draw_string(w_loc + carla.Location(x=x_offset,z=1.0),  f"road: {w.road_id}", False, cyan,   lt)
        debug.draw_string(w_loc + carla.Location(x=x_offset,z=1.5), f"lc: {w.lane_change}",    False, red,    lt)
        debug.draw_string(w_loc + carla.Location(x=x_offset,z=2), f"lt: {w.lane_type}",    False, red,    lt)
        debug.draw_string(w_loc + carla.Location(x=x_offset,y=0.5,z=2), f"x: {w.transform.location.x}",    False, orange,    lt)
        debug.draw_string(w_loc + carla.Location(x=x_offset,y=1,z=2), f"y: {w.transform.location.y}",    False, orange,    lt)

def draw_waypoint_union(debug, w0, w1, color=green, lt=drawing_lifetime):
    # debug.draw_line(
    #     w0.transform.location + carla.Location(z=0.25),
    #     w1.transform.location + carla.Location(z=0.25),
    #     thickness=0.1, color=color, life_time=lt, persistent_lines=False)
    debug.draw_point(w1.transform.location + carla.Location(z=1), 0.1, color, lt, False)

def draw_waypoints(world,map,waypoints,draw_arrows,veh_name,verbose=True,draw_debug=True):
    # verbose: gates the (very chatty) per-segment debug prints below.
    # draw_debug: gates drawing the route overlay (arrows/points/labels) into
    # the CARLA world. Both default True to preserve old behavior for the
    # "real" export calls; the in-progress preview call in the follow_vehicle
    # loop passes both as False so it doesn't spam the console or light up
    # roads in the sim on every poll.
    log = print if verbose else (lambda *a, **k: None)

    log("SETTING UP MAP")
    sampling_resolution = 2
    # dao = GlobalRoutePlannerDAO(map, sampling_resolution)
    grp = GlobalRoutePlanner(map, sampling_resolution)
    # grp.setup()
    log("FINISHED SETTING UP MAP")

    route_waypoints = []
    segment_endpoints = []

    carma_route = []
    general_route = []

    for i_sp in range(1,len(waypoints)):
        
        start_point = waypoints[i_sp-1]
        end_point = waypoints[i_sp]

        log(f"\nSegment {i_sp}")

        log("Start Point XYZ: " + str(start_point))
        start_point_geo = map.transform_to_geolocation(start_point)
        log("Start Point Lat/Long: " + str(start_point_geo))
        log("End Point XYZ: " + str(end_point))
        end_point_geo = map.transform_to_geolocation(end_point)
        log("End Point Lat/Long: " + str(end_point_geo))
        
        if i_sp == 1:
            general_route.append(f'index,x,y,z,latitide,longitude,altitude')
            general_route.append(f'0,{start_point.x},{start_point.y},{start_point.z},{start_point_geo.latitude},{start_point_geo.longitude},{start_point_geo.altitude}')
            general_route.append(f'{i_sp},{end_point.x},{end_point.y},{end_point.z},{end_point_geo.latitude},{end_point_geo.longitude},{end_point_geo.altitude}')
        else:
            general_route.append(f'{i_sp},{end_point.x},{end_point.y},{end_point.z},{end_point_geo.latitude},{end_point_geo.longitude},{end_point_geo.altitude}')


        if i_sp == len(waypoints)-1:
            carma_route.append(f'{end_point_geo.longitude},{end_point_geo.latitude},0,{veh_name}_route')
        else:
            carma_route.append(f'{end_point_geo.longitude},{end_point_geo.latitude},0,{veh_name}_route_waypoint_{i_sp}')
        
        try:
            segment_waypoints = grp.trace_route(start_point, end_point) # there are other funcations can be used to generate a route in GlobalRoutePlanner.
        except Exception as errMsg:
            log(f"Error generating route: {errMsg}")
            segment_waypoints = []

        num_segment_waypoints = len(segment_waypoints)
        log(f"Added {num_segment_waypoints} points")

        route_waypoints = route_waypoints + segment_waypoints

        if i_sp != (len(waypoints) - 1):
            segment_endpoints.append(len(route_waypoints))
            # log(f'segment_endpoints: {segment_endpoints}')
    
    log(f'\n ~~~~~~~~~FINDING SEGMENTS~~~~~~~~~')

    log(f'num route waypoints: {len(route_waypoints)}')

    if len(route_waypoints) == 0:
        # Nothing was traced (e.g. unreachable waypoints) - bail out cleanly
        # instead of crashing on route_waypoints[0] below.
        log("ERROR: No route waypoints were found - check that your waypoints "
              "are reachable and on/near the road network.")
        return {
            "index": [], "x": [], "y": [], "z": [], "carla_yaw": [],
            "carla_bearing_yaw": [], "roll": [], "latitude": [], "longitude": [],
            "altitude": [], "road_grade": [],
        }

    segment_list = []
    first_waypoint,first_road_options = route_waypoints[0]
    first_segment_end_wp = first_waypoint.next_until_lane_end(0.001)[-1]
    segment_list.append(
        {
            "starting_waypoint": first_waypoint,
            "ending_waypoint": first_segment_end_wp,
            "road_id": first_waypoint.road_id,
            "section_id": first_waypoint.section_id,
            "lane_id": first_waypoint.lane_id,
        }
    )

    for waypoint,road_option in route_waypoints:
        # log(f'waypoint id: {waypoint.id} option: {road_option} road: {waypoint.road_id} section: {waypoint.section_id} lane_id: {waypoint.lane_id}' )
            
        if (    segment_list[-1]["road_id"] == waypoint.road_id and 
                segment_list[-1]["section_id"] == waypoint.section_id and 
                segment_list[-1]["lane_id"] == waypoint.lane_id  
        ):
            continue
        else:
            log(f'finished current segment, found first wp of next')
            current_segment_end_wp = waypoint.next_until_lane_end(0.1)[-1]
            log("adding segment: ")
            segment_list.append(
                {
                    "starting_waypoint": waypoint,
                    "ending_waypoint": current_segment_end_wp,
                    "road_id": waypoint.road_id,
                    "section_id": waypoint.section_id,
                    "lane_id": waypoint.lane_id,
                }
            )
    debug = world.debug

    final_segment_list = []
    # roads_to_exclude = [131,281,382,328]
    # roads_to_exclude_delave_right = [438,318,368,143]
    roads_to_exclude = [440,319,364,150]
    for segment in segment_list:
        
        if segment["ending_waypoint"].road_id in roads_to_exclude:
            log("Skipping segment as road is excluded (usually bike or similar)")
            continue
        
        if draw_debug:
            draw_waypoint_union(debug,segment["starting_waypoint"],segment["ending_waypoint"],green)
            draw_waypoint_info(debug,segment["starting_waypoint"],draw_data=True)
            draw_waypoint_info(debug,segment["ending_waypoint"],x_offset=1,draw_data=True)
        final_segment_list.append(segment)


    for segment in final_segment_list:
        log(f'start road: {segment["starting_waypoint"].road_id}')

    
    final_waypoints = []

    for i_seg, segment in enumerate(final_segment_list):
        final_waypoints.append(segment["starting_waypoint"])
        cur_wp = final_waypoints[-1]
        log(f'i_seg: {i_seg} road: {segment["starting_waypoint"].road_id}')

        reached_end = False
        while True:
            next_wp = list(cur_wp.next(waypoint_separation))
            if len(next_wp) == 0:
                log(f'no next wp found')
                reached_end = True
                break
            elif len(next_wp) == 1:
                next_wp = next_wp[0]
                # log(f'progressing down road: {next_wp.road_id}')
            else: 
                log(f'found fork...')
                # Guard against being on the last segment (no "next" segment to match against)
                if i_seg + 1 < len(final_segment_list):
                    target_road_id = final_segment_list[i_seg + 1]["ending_waypoint"].road_id
                    for fork_wp in next_wp:
                        log(f'fork_wp.road_id: {fork_wp.road_id} final_segment_list road: {target_road_id}')
                        if fork_wp.road_id == target_road_id:
                            log(f'found next road in fork: {fork_wp.road_id}')
                            next_wp = fork_wp
                            break
                    else:
                        # No fork matched the expected next road - just take the first option
                        next_wp = next_wp[0]
                else:
                    next_wp = next_wp[0]

            # log(f'next_wp: {next_wp.id}')
            if next_wp.road_id != cur_wp.road_id:
                log(f'reached end of road')
                break

            if draw_debug:
                draw_waypoint_info(debug,cur_wp)
            final_waypoints.append(next_wp)
            cur_wp = next_wp

            if reached_end:
                log(f'reached end of route')
                break
            time.sleep(0.001)



    if args.export and veh_name:
        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

            carma_path = OUTPUT_DIR / f'{veh_name}_carma_route'
            with open(carma_path, "w") as f_c:
                log("\nCARMA ROUTE:")
                for route_line in carma_route:
                    log(route_line)
                    f_c.write(f'{route_line}\n')
            os.chmod(carma_path, 0o666)

            general_path = OUTPUT_DIR / f'{veh_name}_waypoints.csv'
            with open(general_path, "w") as f_g:
                log("\nGENERAL ROUTE:")
                for route_line in general_route:
                    log(route_line)
                    f_g.write(f'{route_line}\n')
            os.chmod(general_path, 0o666)
        except PermissionError as errMsg:
            log(f"ERROR: Permission denied writing to {OUTPUT_DIR}: {errMsg}")
            log(f"\tTry: chmod 755 {OUTPUT_DIR}  (or chown it to your user)")
        except OSError as errMsg:
            log(f"ERROR: Unable to write route files to {OUTPUT_DIR}: {errMsg}")


    waypoint_data = {
        "index" : [],
        "x" : [],
        "y" : [],
        "z" : [],
        "carla_yaw" : [],
        # "geo_heading" : [],
        "carla_bearing_yaw" : [],
        "roll" : [],
        "latitude" : [],
        "longitude" : [],
        "altitude" : [],
        "road_grade" : [],
        # "is_segment_endpoint" : [],
    }

    car_length = 3
    car_width = 2

    midpoint_count = 0

    for i,waypoint in enumerate(final_waypoints):
        if draw_arrows and draw_debug:
            if i == 0:
                start_box_center = final_waypoints[i].transform.location + draw_arrow_z_offset

                start_box = carla.BoundingBox(start_box_center,carla.Vector3D(car_length,car_width,0))

                world.debug.draw_box(
                    start_box, 
                    final_waypoints[i].transform.rotation,
                    0.2,
                    # draw_shadow=False,
                    color=carla.Color(r=0, g=255, b=0), 
                    life_time=drawing_lifetime,
                    persistent_lines=True)
                
                world.debug.draw_string(start_box_center,"        " + veh_name + ' START', draw_shadow=False,color = green, life_time=drawing_lifetime,persistent_lines=True)

            elif i == (len(final_waypoints) -1):
                end_box_center = final_waypoints[i].transform.location + draw_arrow_z_offset

                end_box = carla.BoundingBox(end_box_center,carla.Vector3D(car_length,car_width,0))

                world.debug.draw_box(
                    end_box, 
                    final_waypoints[i].transform.rotation,
                    0.2,
                    # draw_shadow=False,
                    color=red, 
                    life_time=drawing_lifetime,
                    persistent_lines=True)
            
                world.debug.draw_string(end_box_center,"             " +  veh_name + ' END', draw_shadow=False,color = red, life_time=drawing_lifetime,persistent_lines=True)

            elif i in segment_endpoints:
                mid_box_center = final_waypoints[i].transform.location + draw_arrow_z_offset

                mid_box = carla.BoundingBox(mid_box_center,carla.Vector3D(car_length/2,car_width/2,0))
                this_color = carla.Color(r=255, g=50, b=0)

                world.debug.draw_box(
                    mid_box, 
                    final_waypoints[i].transform.rotation,
                    0.2,
                    # draw_shadow=False,
                    color=this_color, 
                    life_time=drawing_lifetime,
                    persistent_lines=True)

                midpoint_count += 1
                world.debug.draw_string(mid_box_center,"" + 'MID_' + str(midpoint_count), draw_shadow=False,color=this_color, life_time=drawing_lifetime,persistent_lines=True)
            
            elif i % 12 == 0:
                world.debug.draw_arrow(
                    waypoint.transform.location + draw_arrow_z_offset, 
                    waypoint.transform.location + waypoint.transform.get_forward_vector() + draw_arrow_z_offset,
                    thickness=draw_arrow_thickness, 
                    arrow_size=draw_arrow_size, 
                    color=blue, 
                    life_time=drawing_lifetime)
                # world.debug.draw_string(waypoint.transform.location, 'O', draw_shadow=False,color=carla.Color(r=0, g=0, b=255), life_time=drawing_lifetime,persistent_lines=True)
            elif i % 3 == 0:
                world.debug.draw_arrow(
                    waypoint.transform.location + draw_arrow_z_offset, 
                    waypoint.transform.location + waypoint.transform.get_forward_vector() + draw_arrow_z_offset,
                    thickness=draw_arrow_thickness, 
                    arrow_size=draw_arrow_size, 
                    color=carla.Color(r=0, g=50, b=255), 
                    life_time=drawing_lifetime)
                # world.debug.draw_string(waypoint.transform.location, str(i), draw_shadow=False,color = carla.Color(r=0, g=50, b=255), life_time=drawing_lifetime,persistent_lines=True)

        waypoint_data["index"].append(i)
        waypoint_data["x"].append(waypoint.transform.location.x) # we swap x and y at the end for export to ltpENU
        waypoint_data["y"].append(waypoint.transform.location.y)
        waypoint_data["z"].append(waypoint.transform.location.z)

        # CARLA yaw (deg): 0 points along +X, +90 along +Y (Unreal coords: X forward, Y right, Z up)
        carla_yaw = waypoint.transform.rotation.yaw % 360
        waypoint_data["carla_yaw"].append(carla_yaw)
        
        # Geographic bearing (deg): 0 is North (+Y if you treat Y as North), 90 is East (+X), 180 South, 270 West
        # geo_heading = (90 - waypoint.transform.rotation.yaw ) % 360.0# we apply the coord transform (90 - yaw) % 360 at the end
        # waypoint_data["geo_heading"].append(geo_heading)

        # also try calculating bearing using the next waypoint
        # we apply the coord transform (90 - yaw) % 360 at the end
        if i < len(final_waypoints) - 1:
            next_waypoint = final_waypoints[i+1]
            dx = next_waypoint.transform.location.x - waypoint.transform.location.x
            dy = next_waypoint.transform.location.y - waypoint.transform.location.y
            if dx == 0 and dy == 0:
                 # if we didnt move, use the previous yaw
                 carla_bearing_yaw = waypoint_data["carla_bearing_yaw"][-1] if waypoint_data["carla_bearing_yaw"] else carla_yaw  # degenerate
            else:
                # theta from +X (East), CCW
                carla_bearing_yaw = math.degrees(math.atan2(dy, dx))
        else:
            # if this is the last point, just use the prev value
            carla_bearing_yaw = waypoint_data["carla_bearing_yaw"][-1] if waypoint_data["carla_bearing_yaw"] else carla_yaw

        

        waypoint_data["carla_bearing_yaw"].append(carla_bearing_yaw) # this is transformed at the end

        waypoint_data["roll"].append(0)
        waypoint_data["road_grade"].append(waypoint.transform.rotation.pitch)

        w_geo = map.transform_to_geolocation(waypoint.transform.location)

        waypoint_data["latitude"].append(w_geo.latitude)
        waypoint_data["longitude"].append(w_geo.longitude)
        waypoint_data["altitude"].append(w_geo.altitude)


        # if i > 0 and i < len(final_waypoints) - 1:
        #     get_road_grade(final_waypoints[i-1],final_waypoints[i+1],final_waypoints[i])



    return waypoint_data

def add_linear_distance(df):
    """
    Adds segment and cumulative linear distances in meters
    based on x,y,z columns (CARLA world coordinates).
    Assumes df is ordered in travel direction.
    """
    # Extract numpy arrays for speed
    coords = df[['x', 'y', 'z']].to_numpy()

    # Differences between successive rows (shifted by 1)
    deltas = coords[1:] - coords[:-1]

    # Euclidean distances
    seg_dist = np.linalg.norm(deltas, axis=1)

    # First waypoint has zero distance traveled from start
    seg_dist = np.insert(seg_dist, 0, 0.0)

    df['segment_distance_m'] = seg_dist
    df['distance_traveled_m'] = seg_dist.cumsum()

    return df

try:
    client = carla.Client(args.host, args.port)
    client.set_timeout(5.0)
    world = client.get_world()
    map = world.get_map()

    # orig 
    # event2_spawn = {
    #         "veh_in_order" : ["MCITY","FHWA", "ORNL", "ANL", "UCLA"],
    #         "wp_btwn_veh" : 5,
    #         "waypoints" : [
    #             carla.Location(x=26.685774, y=129.308929, z=232.633194), # start
    #             carla.Location(x=59.296265, y=67.242165, z=235.812256),
    #             carla.Location(x=99.357674, y=-83.244278, z=242.828964), # end
    #         ],
    # }

    #loop
    # event2_spawn = {
    #         "veh_in_order" : ["MCITY","FHWA", "ORNL", "ANL", "UCLA"],
    #         "wp_btwn_veh" : 5,
    #         "waypoints" : [
    #             carla.Location(x=149.985428, y=-228.668350, z=244),          # start
    #             carla.Location(x=109.453369, y=-60.563061, z=238.563339),   # mid 1
    #             carla.Location(x=100.363297, y=63.378155, z=236.299454),    # mid 2
    #             carla.Location(x=55.186951, y=42.167976, z=236.767197),     # mid 3
    #             carla.Location(x=56.355728, y=-10.193906, z=237.101028),    # mid 4
    #             carla.Location(x=57.891472, y=-66.892288, z=238.003296),    # mid 5
    #             # carla.Location(x=78.490326, y=-120.598251, z=240.014816),   # mid 6
    #             carla.Location(104.506683, y=-130.960526, z=241.668213),    # end
    #         ],
    # }
    # energy_campaign = {
    #         "veh_in_order" : ["UCLA"],
    #         "wp_btwn_veh" : 5,
    #         "waypoints" : [
    #             carla.Location(x=-754.107971, y=730.503052, z=1.324147), 
    #             carla.Location(x=-421.867340, y=764.293213, z=0.899224), 
    #             carla.Location(x=1.540522, y=720.684692, z=1.235085), 
    #             carla.Location(x=313.938751, y=726.293762, z=0.711762), 
    #             carla.Location(x=521.184143, y=845.688660, z=1.005151), 
    #             carla.Location(x=621.049255, y=832.310791, z=1.037112), 
    #         ],
    # }
    energy_campaign_left = {
        "veh_in_order" : ["UCLA"],
        "wp_btwn_veh" : 5,
        "waypoints" : [
            carla.Location(x=-745.4163818, y=728.8236694, z=0.03611618),
            carla.Location(x=-607.802185, y=769.692688, z=-0.005152),
            carla.Location(x=-311.8514709472656, y=748.8836059570312, z=0.036188773810863495),
            carla.Location(x=-88.226082, y=726.184509, z=-0.029539),
            carla.Location(x=305.2701110839844, y=722.4840698242188, z=0.036436766386032104),
            carla.Location(x=603.3434448242188, y=830.186767578125, z=0.036185529083013535),
        ],
    }

    recording = False

    spawn_data = energy_campaign_left

    draw_loop_sleep = args.lifetime

    if args.overlay:
        draw_loop_sleep = 0


    
    start_vehicle_wp_spacing = 5
    end_vehicle_wp_spacing = 7

    if args.export:
        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            os.chmod(OUTPUT_DIR, 0o777)
        except Exception as errMsg:
            print(f"ERROR: Unable to make directory {OUTPUT_DIR}: {errMsg}")
            print(f"\tCreate the directory manually with read/write permissions for your user:")
            print(f"\t\t'mkdir -p {OUTPUT_DIR}' -> 'chmod 755 {OUTPUT_DIR}'")
            sys.exit(1)

    if args.follow_vehicle:
        # NOTE: this branch (continuous follow-vehicle capture) and the
        # "normal" road-segment waypoint creator (the `else:` branch further
        # below) are mutually exclusive by construction - args.follow_vehicle
        # picks exactly one of the two at process start, and there's no path
        # for both to run in the same invocation.
        listener = keyboard.Listener(on_press=on_press)

        print("Starting keyboard listener")
        listener.start()
        print("Keyboard listener started")
        print(f"Press {CAPTURE_TOGGLE_KEY} to start capturing waypoints, "
              f"press it again to stop. DELETE removes the last captured "
              f"waypoint. ENTER finishes and exports.")

        spawn_data["waypoints"] = []

        recording = True

        # How often (seconds) to poll the vehicle's location while capturing.
        # This is independent of draw_loop_sleep (which controls how often
        # the preview route is redrawn) so capture stays responsive even
        # when --lifetime is large.
        capture_poll_interval = 0.1

        last_capture_location = None
        last_draw_time = 0.0

        while recording:
            world = client.get_world()
            map = world.get_map()

            follow_vehicle = get_veh_with_name(args.follow_vehicle)
            current_location = follow_vehicle.get_location()

            if capturing:
                # Only record a new waypoint once the vehicle has moved far
                # enough from the last captured point - otherwise sitting
                # still (or driving slowly) floods the list with duplicates.
                if (last_capture_location is None or
                        current_location.distance(last_capture_location) >= waypoint_separation):
                    spawn_data["waypoints"].append(current_location)
                    last_capture_location = current_location

            now = time.time()
            if len(spawn_data["waypoints"]) > 0 and (now - last_draw_time) >= draw_loop_sleep:
                last_draw_time = now
                # add vehicle as final dest
                spawn_data["waypoints"].append(current_location)
                try:
                    # Preview only - draw the route so far, but don't export yet
                    # (veh_name intentionally left blank here so draw_waypoints
                    # doesn't try to write partial/in-progress files every loop).
                    # verbose=False / draw_debug=False so this repeated preview
                    # call doesn't spam the console or light up roads in the
                    # sim every draw_loop_sleep seconds - only the final export
                    # call (below, after ENTER) draws/logs the route for real.
                    draw_waypoints(world,map,spawn_data["waypoints"],True,"",verbose=False,draw_debug=False)
                except Exception as errMsg:
                    print("UNABLE TO FIND ROUTE")
                    print(errMsg)
                spawn_data["waypoints"].pop()
            elif len(spawn_data["waypoints"]) == 0 and not capturing and (now - last_draw_time) >= draw_loop_sleep:
                last_draw_time = now
                print(f"No waypoints yet. Press {CAPTURE_TOGGLE_KEY} to start capturing.")

            time.sleep(capture_poll_interval)

        # Recording finished (Enter was pressed) - draw + export the final route once,
        # using a real vehicle name so the export condition inside draw_waypoints
        # (`if args.export and veh_name`) actually triggers.
        export_name = args.output_name or args.follow_vehicle

        if len(spawn_data["waypoints"]) < 2:
            print(f"Not enough waypoints recorded ({len(spawn_data['waypoints'])}) to export a route.")
        else:
            print(f"\nFinalizing and exporting route as '{export_name}'...")
            try:
                waypoint_data = draw_waypoints(world, map, spawn_data["waypoints"], True, export_name)

                if args.export and len(waypoint_data["x"]) > 0:
                    df = pd.DataFrame(waypoint_data)
                    df = add_linear_distance(df)

                    df["y"] = -1 * df["y"]

                    df["roll"] = (180 + df["roll"]) % 360.0
                    df["road_grade"] = (-1 * df["road_grade"]) % 360.0
                    df["ltpENU_yaw"] = (-1 * df["carla_yaw"]) % 360.0
                    df["ltpENU_bearing_yaw"] = (-1 * df["carla_bearing_yaw"]) % 360.0

                    df = df.rename(columns={"road_grade": "pitch", "ltpENU_yaw": "yaw"})
                    df = df[["index", "x", "y", "z", "roll", "pitch", "yaw",
                             "latitude", "longitude", "altitude",
                             "segment_distance_m", "distance_traveled_m"]]

                    breadcrumbs_path = OUTPUT_DIR / f'{export_name}_breadcrumbs.csv'
                    try:
                        df.to_csv(breadcrumbs_path, index=False)
                        os.chmod(breadcrumbs_path, 0o666)
                        print(f"Wrote {len(df)} rows to {breadcrumbs_path}")
                    except PermissionError as errMsg:
                        print(f"ERROR: Permission denied writing to {breadcrumbs_path}: {errMsg}")
                    except OSError as errMsg:
                        print(f"ERROR: Unable to write {breadcrumbs_path}: {errMsg}")
            except Exception as errMsg:
                print("UNABLE TO FIND ROUTE FOR FINAL EXPORT")
                print(errMsg)
    else:
        
        waypoint_data = draw_waypoints(world,map,spawn_data["waypoints"],False,"")
        num_waypoints = len(waypoint_data["x"])
        print("num_waypoints: " + str(num_waypoints))
        new_spawns = []

        for i_v,veh_name in enumerate(spawn_data["veh_in_order"]):
            
            start_waypoint_index = 0 + (start_vehicle_wp_spacing * i_v)
            end_waypoint_index = (num_waypoints -1) - (end_vehicle_wp_spacing * (len(spawn_data["veh_in_order"]) - 1 - i_v))

            print(veh_name + " start_waypoint_index: " + str(start_waypoint_index))
            print(veh_name + " end_waypoint_index: " + str(end_waypoint_index))

            this_spawn = {
                "name" : veh_name,
                "line_order" : i_v,
                "waypoints" : []
            }

            for i_sp,this_waypoint in enumerate(spawn_data["waypoints"]):
                if i_sp == 0:
                    new_waypoint = carla.Location(
                        x=waypoint_data["x"][start_waypoint_index], 
                        y=waypoint_data["y"][start_waypoint_index], 
                        z=waypoint_data["z"][start_waypoint_index]
                    )

                elif i_sp == (len(spawn_data["waypoints"]) -1):
                    new_waypoint = carla.Location(
                        x=waypoint_data["x"][end_waypoint_index], 
                        y=waypoint_data["y"][end_waypoint_index], 
                        z=waypoint_data["z"][end_waypoint_index]
                    )
                
                else:
                    new_waypoint = this_waypoint

                this_spawn["waypoints"].append(new_waypoint)
                
            print(f'this_spawn: {this_spawn}')    

            new_spawns.append(this_spawn)


        for spawn in new_spawns:
            # world.debug.draw_string(spawn["spawn_point"], "o", draw_shadow=False,color = carla.Color(r=255, g=255, b=0), life_time=drawing_lifetime,persistent_lines=True)
            print("\nDrawing: " + spawn["name"])
            # world.debug.draw_string(spawn["spawn_point"], "     " + spawn["name"], draw_shadow=False,color = carla.Color(r=255, g=255, b=0), life_time=drawing_lifetime,persistent_lines=True)
            waypoint_data = draw_waypoints(world,map,spawn["waypoints"],True,spawn["name"])

            if args.export:
                df = pd.DataFrame(waypoint_data)
                df = add_linear_distance(df)

                df["y"] = -1 * df["y"]

                df["roll"] = (180 + df["roll"]) % 360.0
                df["road_grade"] = (-1 * df["road_grade"]) % 360.0
                df["ltpENU_yaw"] = (-1 * df["carla_yaw"]) % 360.0
                df["ltpENU_bearing_yaw"] = (-1 * df["carla_bearing_yaw"]) % 360.0

                breadcrumbs_path = OUTPUT_DIR / f'{spawn["name"]}_breadcrumbs.csv'
                try:
                    df.to_csv(breadcrumbs_path, index=False)
                    os.chmod(breadcrumbs_path, 0o666)
                except PermissionError as errMsg:
                    print(f"ERROR: Permission denied writing to {breadcrumbs_path}: {errMsg}")
                except OSError as errMsg:
                    print(f"ERROR: Unable to write {breadcrumbs_path}: {errMsg}")

            time.sleep(draw_loop_sleep)

except Exception as errMsg:
    print(f"ERROR: Failed to draw waypoints: {errMsg}")

finally:
    print('\nDone!')