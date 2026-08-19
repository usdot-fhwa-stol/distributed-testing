import os
import sys
import re
import argparse
import json
import math
import time
import pandas as pd
import numpy as np

from pynput import keyboard
from pynput.keyboard import Key

import carla
from agents.navigation.global_route_planner import GlobalRoutePlanner

argparser = argparse.ArgumentParser(description=__doc__)
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
    help='export waypoints to file (creates waypoint_files dir)')
argparser.add_argument(
    '-o', '--overlay',
    action='store_true',
    help='overlay all routes on top of each other')
argparser.add_argument(
    '--follow_vehicle',
    help='Vehicle to be used for the follow cam (default: "TFHRC-MANUAL-1")')
args = argparser.parse_args()

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
draw_arrow_z_offset = carla.Location(0, 0, 0)

EXPORT_DIR = "/home/dt_user/waypoint_files"


def on_press(key):
    global recording

    try:
        key_char = key.char
    except Exception:
        key_char = None

    if key == Key.space:
        follow_vehicle = get_veh_with_name(args.follow_vehicle)
        if follow_vehicle:
            loc = follow_vehicle.get_location()
            print(f"Adding waypoint: {loc}")
            spawn_data["waypoints"].append(loc)
    elif key == Key.delete:
        if len(spawn_data["waypoints"]) > 0:
            removed_wp = spawn_data["waypoints"].pop()
            print(f"Removed waypoint: {removed_wp}")
        else:
            print("No waypoints to remove")
    elif key == Key.enter:
        recording = False
        print("Done adding waypoints")
        print("Waypoints:")
        for waypoint in spawn_data["waypoints"]:
            print(f"\tx: {waypoint.x} y: {waypoint.y} z: {waypoint.z}")


def get_veh_with_name(veh_rolename):
    player = None
    carlaVehicles = world.get_actors().filter('vehicle.*')
    for vehicle in carlaVehicles:
        currentAttributes = vehicle.attributes
        if currentAttributes.get("role_name") == veh_rolename:
            player = vehicle
            break
    if not player:
        print("ERROR: Unable to find vehicle with rolename: " + str(veh_rolename))
        sys.exit(1)
    
    return player


def get_road_grade(start_point, end_point, mid_point):
    print(f'mid_point: {mid_point[0].transform}')
    run = math.sqrt((end_point[0].transform.location.x - start_point[0].transform.location.x)**2 + 
                    (end_point[0].transform.location.y - start_point[0].transform.location.y)**2)
    print(f'\nrun: {run}')
    rise = end_point[0].transform.location.z - start_point[0].transform.location.z
    print(f'rise: {rise}')

    grade = (rise / run * 100) if run != 0 else 0

    world.debug.draw_string(mid_point[0].transform.location, str(grade), draw_shadow=False, color=carla.Color(r=0, g=255, b=0), life_time=drawing_lifetime, persistent_lines=True)
    print(f'grade: {grade}')


def draw_waypoint_info(debug, w, lt=drawing_lifetime, x_offset=0, draw_data=False):
    w_loc = w.transform.location
    world.debug.draw_arrow(
        w.transform.location + draw_arrow_z_offset, 
        w.transform.location + w.transform.get_forward_vector() + draw_arrow_z_offset,
        thickness=draw_arrow_thickness, 
        arrow_size=draw_arrow_size, 
        color=red, 
        life_time=drawing_lifetime)
    if draw_data:
        debug.draw_string(w_loc + carla.Location(x=x_offset, z=0.5), f"lane: {w.lane_id}", False, yellow, lt)
        debug.draw_string(w_loc + carla.Location(x=x_offset, z=1.0), f"road: {w.road_id}", False, cyan, lt)
        debug.draw_string(w_loc + carla.Location(x=x_offset, z=1.5), f"lc: {w.lane_change}", False, red, lt)
        debug.draw_string(w_loc + carla.Location(x=x_offset, z=2.0), f"lt: {w.lane_type}", False, red, lt)
        debug.draw_string(w_loc + carla.Location(x=x_offset, y=0.5, z=2.0), f"x: {w.transform.location.x}", False, orange, lt)
        debug.draw_string(w_loc + carla.Location(x=x_offset, y=1.0, z=2.0), f"y: {w.transform.location.y}", False, orange, lt)


def draw_waypoint_union(debug, w0, w1, color=green, lt=drawing_lifetime):
    debug.draw_point(w1.transform.location + carla.Location(z=1), 0.1, color, lt, False)


def draw_waypoints(world, carla_map, waypoints, draw_arrows, veh_name):    
    print("SETTING UP MAP")
    sampling_resolution = 2.0
    grp = GlobalRoutePlanner(carla_map, sampling_resolution)
    print("FINISHED SETTING UP MAP")

    route_waypoints = []
    segment_endpoints = []

    carma_route = []
    general_route = []

    for i_sp in range(1, len(waypoints)):
        start_point = waypoints[i_sp-1]
        end_point = waypoints[i_sp]

        print(f"\nSegment {i_sp}")
        print("Start Point XYZ: " + str(start_point))
        start_point_geo = carla_map.transform_to_geolocation(start_point)
        print("Start Point Lat/Long: " + str(start_point_geo))
        print("End Point XYZ: " + str(end_point))
        end_point_geo = carla_map.transform_to_geolocation(end_point)
        print("End Point Lat/Long: " + str(end_point_geo))
        
        if i_sp == 1:
            general_route.append('index,x,y,z,latitide,longitude,altitude')
            general_route.append(f'0,{start_point.x},{start_point.y},{start_point.z},{start_point_geo.latitude},{start_point_geo.longitude},{start_point_geo.altitude}')
            general_route.append(f'{i_sp},{end_point.x},{end_point.y},{end_point.z},{end_point_geo.latitude},{end_point_geo.longitude},{end_point_geo.altitude}')
        else:
            general_route.append(f'{i_sp},{end_point.x},{end_point.y},{end_point.z},{end_point_geo.latitude},{end_point_geo.longitude},{end_point_geo.altitude}')

        if i_sp == len(waypoints)-1:
            carma_route.append(f'{end_point_geo.longitude},{end_point_geo.latitude},0,{veh_name}_route')
        else:
            carma_route.append(f'{end_point_geo.longitude},{end_point_geo.latitude},0,{veh_name}_route_waypoint_{i_sp}')
        
        try:
            segment_waypoints = grp.trace_route(start_point, end_point)
        except Exception as errMsg:
            print(f"Error generating route: {errMsg}")
            segment_waypoints = []

        num_segment_waypoints = len(segment_waypoints)
        print(f"Added {num_segment_waypoints} points")

        route_waypoints = route_waypoints + segment_waypoints

        if i_sp != (len(waypoints) - 1):
            segment_endpoints.append(len(route_waypoints))

    print('\n ~~~~~~~~~FINDING SEGMENTS~~~~~~~~~')
    print(f'num route waypoints: {len(route_waypoints)}')

    if not route_waypoints:
        return {}

    segment_list = []
    first_waypoint, _ = route_waypoints[0]
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

    for waypoint, road_option in route_waypoints:
        if (segment_list[-1]["road_id"] == waypoint.road_id and 
            segment_list[-1]["section_id"] == waypoint.section_id and 
            segment_list[-1]["lane_id"] == waypoint.lane_id
        ):
            continue
        else:
            print('finished current segment, found first wp of next')
            current_segment_end_wp = waypoint.next_until_lane_end(0.1)[-1]
            print("adding segment: ")
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
    
    # Filter non-vehicle lanes dynamically using CARLA's LaneType enum
    for segment in segment_list:
        wp = segment["starting_waypoint"]
        if wp.lane_type != carla.LaneType.Driving:
            print(f"Skipping segment on road {wp.road_id} (Lane Type: {wp.lane_type})")
            continue
        
        draw_waypoint_union(debug, segment["starting_waypoint"], segment["ending_waypoint"], green)
        draw_waypoint_info(debug, segment["starting_waypoint"], draw_data=True)
        draw_waypoint_info(debug, segment["ending_waypoint"], x_offset=1, draw_data=True)
        final_segment_list.append(segment)

    for segment in final_segment_list:
        print(f'start road: {segment["starting_waypoint"].road_id}')

    final_waypoints = []

    for i_seg, segment in enumerate(final_segment_list):
        final_waypoints.append(segment["starting_waypoint"])
        cur_wp = final_waypoints[-1]
        print(f'i_seg: {i_seg} road: {segment["starting_waypoint"].road_id}')

        reached_end = False
        visited_wp_keys = {(cur_wp.road_id, cur_wp.section_id, cur_wp.lane_id, round(cur_wp.s, 1))}
        # Safety cap: a normal segment shouldn't need more than a few thousand
        # 0.2m steps. If we ever hit this, something upstream is looping.
        MAX_STEPS_PER_SEGMENT = 20000
        steps = 0
        while True:
            steps += 1
            if steps > MAX_STEPS_PER_SEGMENT:
                print(f"WARNING: segment {i_seg} exceeded {MAX_STEPS_PER_SEGMENT} steps without reaching a road "
                      f"boundary - aborting this segment to avoid a runaway/looping walk.")
                break

            # Explicitly restrict search to Driving lanes
            next_wps = [w for w in cur_wp.next(waypoint_separation) if w.lane_type == carla.LaneType.Driving]
            
            if len(next_wps) == 0:
                print('no next wp found')
                reached_end = True
                break
            elif len(next_wps) == 1:
                next_wp = next_wps[0]
            else: 
                print('found fork...')
                next_wp = next_wps[0] # Default fallback
                if i_seg + 1 < len(final_segment_list):
                    target_road = final_segment_list[i_seg + 1]["ending_waypoint"].road_id
                    for fork_wp in next_wps:
                        print(f'fork_wp.road_id: {fork_wp.road_id} target road: {target_road}')
                        if fork_wp.road_id == target_road:
                            print(f'found next road in fork: {fork_wp.road_id}')
                            next_wp = fork_wp
                            break

            if next_wp.road_id != cur_wp.road_id:
                print('reached end of road')
                break

            # Known CARLA bug (present through at least 0.10.0): waypoint.next()
            # can bounce back and forth when two opposite-direction lanes run
            # alongside each other, handing back a waypoint that doesn't
            # actually progress. Detect a revisit (or a step that produced
            # essentially zero movement) and bail out of the segment instead
            # of grinding out duplicate/stuck points forever.
            next_key = (next_wp.road_id, next_wp.section_id, next_wp.lane_id, round(next_wp.s, 1))
            step_dist = cur_wp.transform.location.distance(next_wp.transform.location)
            if next_key in visited_wp_keys or step_dist < 1e-3:
                print(f"WARNING: detected a non-progressing/looping waypoint on road {next_wp.road_id} "
                      f"(known CARLA next()/previous() loop bug on opposite-direction lanes) - "
                      f"ending this segment early instead of producing duplicate points.")
                reached_end = True
                break
            visited_wp_keys.add(next_key)

            draw_waypoint_info(debug, cur_wp)
            final_waypoints.append(next_wp)
            cur_wp = next_wp

            if reached_end:
                print('reached end of route')
                break
            time.sleep(0.001)

    if args.export and veh_name:
        f_c = open(f'{EXPORT_DIR}/{veh_name}_carma_route', "w")
        print("\nCARMA ROUTE:")
        for route_line in carma_route:
            print(route_line)
            f_c.write(f'{route_line}\n')
        f_c.close()
        os.chmod(f'{EXPORT_DIR}/{veh_name}_carma_route', 0o666)

        f_g = open(f'{EXPORT_DIR}/{veh_name}_waypoints.csv', "w")
        print("\nGENERAL ROUTE:")
        for route_line in general_route:
            print(route_line)
            f_g.write(f'{route_line}\n')
        f_g.close()
        os.chmod(f'{EXPORT_DIR}/{veh_name}_waypoints.csv', 0o666)

    waypoint_data = {
        "index" : [],
        "x" : [],
        "y" : [],
        "z" : [],
        "pitch" : [],
        "yaw" : [],
        "carla_bearing_yaw" : [],
        "roll" : [],
        "latitude" : [],
        "longitude" : [],
        "altitude" : [],
        "road_grade" : [],
    }

    # --- Dedupe near-identical consecutive waypoints ---
    # In CARLA 0.10.0 (UE5) the road network is segmented differently than 0.9.15.
    # At segment/junction boundaries this code appends a fresh "starting_waypoint"
    # for the next segment right after the previous segment's walk already ended
    # at (essentially) the same spot, and cur_wp.next(waypoint_separation) can also
    # return a waypoint that hasn't actually moved at some junctions on the new
    # map data. Left alone, these zero/near-zero-distance points are exported as
    # real breadcrumbs, which is what makes several rows in the CSV identical and
    # makes the playback tool sit still / stutter on them.
    DEDUPE_DIST_M = 0.01
    deduped_waypoints = []
    for wp in final_waypoints:
        if deduped_waypoints:
            prev = deduped_waypoints[-1]
            dx = wp.transform.location.x - prev.transform.location.x
            dy = wp.transform.location.y - prev.transform.location.y
            dz = wp.transform.location.z - prev.transform.location.z
            if math.sqrt(dx * dx + dy * dy + dz * dz) < DEDUPE_DIST_M:
                continue
        deduped_waypoints.append(wp)

    num_dropped = len(final_waypoints) - len(deduped_waypoints)
    if num_dropped:
        print(f"Dropped {num_dropped} duplicate/near-duplicate waypoint(s)")
    final_waypoints = deduped_waypoints

    car_length = 3
    car_width = 2
    midpoint_count = 0

    for i, waypoint in enumerate(final_waypoints):
        if draw_arrows:
            if i == 0:
                start_box_center = final_waypoints[i].transform.location + draw_arrow_z_offset
                start_box = carla.BoundingBox(start_box_center, carla.Vector3D(car_length, car_width, 0))
                world.debug.draw_box(
                    start_box, 
                    final_waypoints[i].transform.rotation,
                    0.2,
                    color=carla.Color(r=0, g=255, b=0), 
                    life_time=drawing_lifetime,
                    persistent_lines=True)
                world.debug.draw_string(start_box_center, "        " + veh_name + ' START', draw_shadow=False, color=green, life_time=drawing_lifetime, persistent_lines=True)

            elif i == (len(final_waypoints) - 1):
                end_box_center = final_waypoints[i].transform.location + draw_arrow_z_offset
                end_box = carla.BoundingBox(end_box_center, carla.Vector3D(car_length, car_width, 0))
                world.debug.draw_box(
                    end_box, 
                    final_waypoints[i].transform.rotation,
                    0.2,
                    color=red, 
                    life_time=drawing_lifetime,
                    persistent_lines=True)
                world.debug.draw_string(end_box_center, "             " + veh_name + ' END', draw_shadow=False, color=red, life_time=drawing_lifetime, persistent_lines=True)

            elif i in segment_endpoints:
                mid_box_center = final_waypoints[i].transform.location + draw_arrow_z_offset
                mid_box = carla.BoundingBox(mid_box_center, carla.Vector3D(car_length/2, car_width/2, 0))
                this_color = carla.Color(r=255, g=50, b=0)

                world.debug.draw_box(
                    mid_box, 
                    final_waypoints[i].transform.rotation,
                    0.2,
                    color=this_color, 
                    life_time=drawing_lifetime,
                    persistent_lines=True)

                midpoint_count += 1
                world.debug.draw_string(mid_box_center, 'MID_' + str(midpoint_count), draw_shadow=False, color=this_color, life_time=drawing_lifetime, persistent_lines=True)
            
            elif i % 12 == 0:
                world.debug.draw_arrow(
                    waypoint.transform.location + draw_arrow_z_offset, 
                    waypoint.transform.location + waypoint.transform.get_forward_vector() + draw_arrow_z_offset,
                    thickness=draw_arrow_thickness, 
                    arrow_size=draw_arrow_size, 
                    color=blue, 
                    life_time=drawing_lifetime)
            elif i % 3 == 0:
                world.debug.draw_arrow(
                    waypoint.transform.location + draw_arrow_z_offset, 
                    waypoint.transform.location + waypoint.transform.get_forward_vector() + draw_arrow_z_offset,
                    thickness=draw_arrow_thickness, 
                    arrow_size=draw_arrow_size, 
                    color=carla.Color(r=0, g=50, b=255), 
                    life_time=drawing_lifetime)

        waypoint_data["index"].append(i)
        waypoint_data["x"].append(waypoint.transform.location.x)
        waypoint_data["y"].append(waypoint.transform.location.y)
        waypoint_data["z"].append(waypoint.transform.location.z)

        carla_pitch = waypoint.transform.rotation.pitch % 360
        waypoint_data["pitch"].append(carla_pitch)

        carla_yaw = waypoint.transform.rotation.yaw % 360
        waypoint_data["yaw"].append(carla_yaw)
        
        if i < len(final_waypoints) - 1:
            next_waypoint = final_waypoints[i+1]
            dx = next_waypoint.transform.location.x - waypoint.transform.location.x
            dy = next_waypoint.transform.location.y - waypoint.transform.location.y
            if dx == 0 and dy == 0:
                carla_bearing_yaw = waypoint_data["carla_bearing_yaw"][-1] if waypoint_data["carla_bearing_yaw"] else 0.0
            else:
                carla_bearing_yaw = math.degrees(math.atan2(dy, dx))
        else:
            carla_bearing_yaw = waypoint_data["carla_bearing_yaw"][-1] if waypoint_data["carla_bearing_yaw"] else 0.0

        waypoint_data["carla_bearing_yaw"].append(carla_bearing_yaw)
        waypoint_data["roll"].append(0)
        waypoint_data["road_grade"].append(waypoint.transform.rotation.pitch)

        w_geo = carla_map.transform_to_geolocation(waypoint.transform.location)
        waypoint_data["latitude"].append(w_geo.latitude)
        waypoint_data["longitude"].append(w_geo.longitude)
        waypoint_data["altitude"].append(w_geo.altitude)

    return waypoint_data


def add_linear_distance(df):
    coords = df[['x', 'y', 'z']].to_numpy()
    deltas = coords[1:] - coords[:-1]
    seg_dist = np.linalg.norm(deltas, axis=1)
    seg_dist = np.insert(seg_dist, 0, 0.0)

    df['segment_distance_m'] = seg_dist
    df['distance_traveled_m'] = seg_dist.cumsum()
    return df


def process_and_export_route(world, carla_map, waypoints, veh_name, draw_arrows=True):
    waypoint_data = draw_waypoints(world, carla_map, waypoints, draw_arrows, veh_name)

    if args.export and waypoint_data:
        df = pd.DataFrame(waypoint_data)
        df = add_linear_distance(df)

        df["y"] = -1 * df["y"]
        df["roll"] = (180 + df["roll"]) % 360.0

        # Follow-vehicle breadcrumb files must only contain these columns, in
        # this order - drop everything else (carla_bearing_yaw, road_grade,
        # any ltpENU_* helper columns, etc.) before writing.
        breadcrumb_columns = [
            "index", "x", "y", "z", "roll", "pitch", "yaw",
            "latitude", "longitude", "altitude",
            "segment_distance_m", "distance_traveled_m",
        ]
        df = df[breadcrumb_columns]

        out_file = os.path.join(EXPORT_DIR, f'{veh_name}_breadcrumbs.csv')
        df.to_csv(out_file, index=False)
        os.chmod(out_file, 0o666)
        print(f"Exported breadcrumbs CSV: {out_file}")

    return waypoint_data


try:
    client = carla.Client(args.host, args.port)
    client.set_timeout(10.0)
    world = client.get_world()
    carla_map = world.get_map()

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
        if not os.path.exists(EXPORT_DIR):
            os.makedirs(EXPORT_DIR, exist_ok=True)

    if args.follow_vehicle:
        listener = keyboard.Listener(on_press=on_press)
        print("Starting keyboard listener...")
        listener.start()
        print("Keyboard listener active. Press SPACE to place waypoints, DELETE to undo, ENTER to finish.")
        
        spawn_data["waypoints"] = []
        recording = True

        while recording:
            world = client.get_world()
            carla_map = world.get_map() 

            follow_vehicle = get_veh_with_name(args.follow_vehicle)
            
            if len(spawn_data["waypoints"]) > 0:
                spawn_data["waypoints"].append(follow_vehicle.get_location())
                try:
                    draw_waypoints(world, carla_map, spawn_data["waypoints"], True, args.follow_vehicle)
                except Exception as errMsg:
                    print("UNABLE TO FIND ROUTE")
                    print(errMsg)
                spawn_data["waypoints"].pop()
            else:
                print("No waypoints added. Add a new waypoint by pressing SPACE")

            time.sleep(draw_loop_sleep)

        listener.stop()

        # Generate and export final route upon exiting recording mode
        if len(spawn_data["waypoints"]) >= 2:
            print(f"\nProcessing recorded route for vehicle: {args.follow_vehicle}...")
            process_and_export_route(world, carla_map, spawn_data["waypoints"], args.follow_vehicle, draw_arrows=True)
        else:
            print("Insufficient waypoints recorded (minimum 2 required to draw and export route).")

    else:
        waypoint_data = draw_waypoints(world, carla_map, spawn_data["waypoints"], False, "")
        num_waypoints = len(waypoint_data.get("x", []))
        print("num_waypoints: " + str(num_waypoints))
        new_spawns = []

        for i_v, veh_name in enumerate(spawn_data["veh_in_order"]):
            start_waypoint_index = 0 + (start_vehicle_wp_spacing * i_v)
            end_waypoint_index = (num_waypoints - 1) - (end_vehicle_wp_spacing * (len(spawn_data["veh_in_order"]) - 1 - i_v))

            print(veh_name + " start_waypoint_index: " + str(start_waypoint_index))
            print(veh_name + " end_waypoint_index: " + str(end_waypoint_index))

            this_spawn = {
                "name" : veh_name,
                "line_order" : i_v,
                "waypoints" : []
            }

            for i_sp, this_waypoint in enumerate(spawn_data["waypoints"]):
                if i_sp == 0:
                    new_waypoint = carla.Location(
                        x=waypoint_data["x"][start_waypoint_index], 
                        y=waypoint_data["y"][start_waypoint_index], 
                        z=waypoint_data["z"][start_waypoint_index]
                    )
                elif i_sp == (len(spawn_data["waypoints"]) - 1):
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
            print("\nDrawing and exporting: " + spawn["name"])
            process_and_export_route(world, carla_map, spawn["waypoints"], spawn["name"], draw_arrows=True)
            time.sleep(draw_loop_sleep)

except Exception as errMsg:
    print(f"ERROR: Failed to draw waypoints: {errMsg}")

finally:
    print('\nDone!')