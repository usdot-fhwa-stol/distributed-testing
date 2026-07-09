import glob
import os
import sys
import time
import argparse
import pygame
import json
import numpy as np
import pandas as pd

from find_carla_egg import find_carla_egg

carla_egg_file = find_carla_egg()

sys.path.append(carla_egg_file)

import carla

def get_dist_3d_vectors(start_vector,vehicle_vector):
    return np.dot(start_vector,vehicle_vector)/(np.linalg.norm(start_vector))


def get_actor_by_location(world,location_array,filter):
    carla_actors = world.get_actors().filter( filter + "*")
    for actor in carla_actors:
        actor_loc = actor.get_location()
        actor_loc_array = [actor_loc.x, actor_loc.y, actor_loc.z]
        dist_from_target_loc = abs(get_dist_3d_pythag(actor_loc_array,location_array))
        if dist_from_target_loc < 5:
            return actor
        

def get_dist_3d_pythag(start_point,end_point):
    return ((end_point[0]-start_point[0])**2 + (end_point[1]-start_point[1])**2 + (end_point[2]-start_point[2])**2) ** 0.5

def read_json(json_path):
    try:
        file = open(json_path)
        return json.load(file)
    except:
        print("Config file could not be opened: " + json_path)
        sys.exit()

def spawn_vehicle(world, blueprint_name,role_name, x, y, z, yaw):
    blueprint = world.get_blueprint_library().find(blueprint_name)
    spawn_point = carla.Transform(
        carla.Location(x=x, y=y, z=z),
        carla.Rotation(yaw=yaw)
    )

    blueprint.set_attribute("role_name",role_name)
    vehicle = world.try_spawn_actor(blueprint, spawn_point)
    if vehicle is None:
        print("Error: Vehicle could not be spawned!")
        exit()
    vehicle.set_autopilot(False)
    return vehicle

def move_vehicle_with_point(world, vehicle, end_point, velocity):
    
    vehicle.enable_constant_velocity(carla.Vector3D(x=velocity, y=0.0, z=0.0))
    
    location = vehicle.get_location()
    velocity = vehicle.get_velocity()
    current_speed = 2.23694 * (velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2) ** 0.5
    # convert end point to float array
    end_point = [float(i) for i in end_point]
    current_loc = [location.x, location.y, location.z]

    dist_from_end = get_dist_3d_pythag(current_loc,end_point)

    print("-" * 10)

    print(f"Distance to end point: {dist_from_end:.2f} meter")
    print(f"Simulation time: {world.get_snapshot().timestamp.elapsed_seconds:.2f} seconds")
    print("Vehicle location: x={}, y={}, z={}".format(location.x, location.y, location.z))
    print("Vehicle speed: {:.2f} mph".format(current_speed))

    # if reached within 2m of end point quit
    if dist_from_end <= 2:
        print("REACHED END")
        return True
    else:
        return False
    

def move_vehicle_with_duration(world, vehicle, duration, velocity):
    vehicle.enable_constant_velocity(carla.Vector3D(x=velocity, y=0.0, z=0.0))
    start_time = world.get_snapshot().timestamp.elapsed_seconds
    curr_time = world.get_snapshot().timestamp.elapsed_seconds
    while curr_time - start_time < duration:
        location = vehicle.get_location()
        velocity = vehicle.get_velocity()
        current_speed = 3.6 * (velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2) ** 0.5
        curr_time = world.get_snapshot().timestamp.elapsed_seconds

        print("-" * 10)
        print(f"Simulation time: {curr_time:.2f} seconds")
        print("Vehicle location: x={}, y={}, z={}".format(location.x, location.y, location.z))
        print("Vehicle speed: {:.2f} km/h".format(current_speed))
        time.sleep(0.1)
    vehicle.enable_constant_velocity(carla.Vector3D(x=0.0, y=0.0, z=0.0))
    time.sleep(3)


if __name__ == '__main__':
    # Set up argument parsing
    parser = argparse.ArgumentParser()
    parser.add_argument('--x', type=float, default=0, help='x coordinate of the spawn point')
    parser.add_argument('--y', type=float, default=0, help='y coordinate of the spawn point')
    parser.add_argument('--z', type=float, default=0, help='z coordinate of the spawn point')
    parser.add_argument('--yaw', type=float, default=0, help='yaw orientation of the vehicle')
    parser.add_argument('--velocity', type=float, default=25, help='velocity of the vehicle in km/h')
    parser.add_argument('--stop', type=str, default="point", help='enter stop condition by duration or point')
    parser.add_argument('--duration', type=float, default=15, help='vehilce running duration')
    parser.add_argument('--config', type=str, help='config file to import')
    parser.add_argument('--point', nargs='+', default=[255, -130, 0], help='enter an end point')
    parser.add_argument('--svm_vehicle_name',default="NISSAN-SVM",help='Vehicle to be used for the simple vehicle model (default: "NISSAN-SVM"')
    parser.add_argument('--spawn_vehicle', action='store_true', help='adding this flag will spawn the vehicle as opposed to letting the carla adapter spawning the vehicle')
    args = parser.parse_args()
    
    # if config file is passed, use that for running vehicle
    if args.config:

        config = read_json(args.config)
        # Connect to the simulator and retrieve the world
        client = carla.Client(config["CARLAIp"], config["CARLAPort"])
        client.set_timeout(2.0)
        world = client.get_world()

        # Set CARLA simulator as wall clock
        settings = world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = None # Set a variable time-step
        world.apply_settings(settings)

        # Set up the Pygame window and clock
        pygame.init()
        # Set the font and text for the message
        font = pygame.font.SysFont("monospace", 30)
        screen_width = 950
        screen_height = 350

        screen = pygame.display.set_mode((screen_width, screen_height))

        clock = pygame.time.Clock()
        
        started = False

        for cfg_i,vehicle_cfg in enumerate(config["vehicles"]):
            x_pt = vehicle_cfg["startPt"][0]
            y_pt = vehicle_cfg["startPt"][1]
            z_pt = vehicle_cfg["startPt"][2]
            yaw = vehicle_cfg["yaw"]

            vehicle = None

            # find the vehicle based on the desired rolename
            carlaVehicles = world.get_actors().filter('vehicle.*')
            for current_vehicle in carlaVehicles:
                currentAttributes = current_vehicle.attributes
                if currentAttributes["role_name"] == args.svm_vehicle_name:
                        vehicle = current_vehicle
            
            # if we choose to spawn the vehicle and this is the first run, spawn the vehicle
            # we want to use the same vehicle for all runs and not spawn new ones
            if args.spawn_vehicle and cfg_i == 0:
                
                # if we found a vehicle with the same name, destroy it so we can recreate it in the right spot 
                if vehicle != None:
                    vehicle.destroy()
                
                # Spawn the vehicle at the specified location with the initial speed
                vehicle = spawn_vehicle(world, vehicle_cfg["vehicleModel"], config["role_name"], x_pt, y_pt, z_pt, yaw)
            
            
            
            # if we still cant find the vehicle, exit
            if not vehicle:
                print("SVM VEHICLE NOT FOUND")
                sys.exit()
            
            # set initial location for vehicle for this scenario 
            vehicle.set_transform(carla.Transform(carla.Location(x_pt,y_pt,z_pt),carla.Rotation(0,yaw,0)))
            
            running = False
            reached_end = False
            fresh_desired_phase = False
            desired_phase_start = 0
            dist_from_int_exit_at_red = "########"


            print("\nSTARTING SCENARIO " + str(cfg_i + 1))
            
            start_point = np.array(vehicle_cfg['startPt'])
            opp_stop_bar_point = np.array(vehicle_cfg['oppositeStopBar'])

            start_vector = opp_stop_bar_point - start_point

            scenario_results_header = pd.DataFrame([],columns=["Scenario_#","initial_distance_to_entry_lane_stop_bar","speed (mph)","Dist_at_red (m)"])

            scenario_results_header.to_csv("test.csv")

            try:
                while reached_end == False:
                    world.tick()
                    
                    text_list = []

                    text_list.append(font.render(     "-"*20, True, (255, 255, 255)))
                    text_list.append(font.render(     "|" + ("SCENARIO " + str(cfg_i + 1)).center(20) + "|", True, (255, 255, 255)))
                    text_list.append(font.render(     "-"*20, True, (255, 255, 255)))
                    
                    # get scenario params
                    scenario_dist_to_stopbar = int(round(get_dist_3d_pythag(vehicle_cfg['startPt'],vehicle_cfg['stopBar']),0))

                    text_list.append(font.render(     "Distance to Entry Lane Stop Bar = " + str(scenario_dist_to_stopbar) + "m ", True, (255, 255, 255)))
                    text_list.append(font.render(     "Speed = " + str(vehicle_cfg["targetSpeedMPH"]) + " mph", True, (255, 255, 255)))
                    
                    # get traffic light state
                    tl_actor = get_actor_by_location(world,config["tl_location"],"traffic.traffic_light")
                    
                    if not tl_actor:
                        print("Traffic Light actor not found...")
                        sys.exit()
                    
                    tl_state = tl_actor.state

                    text_list.append(font.render(     "Desired Traffic Light State = " + str(vehicle_cfg["targetTrafficLightState"]), True, (255, 255, 255)))
                    text_list.append(font.render(     "Current Traffic Light State = " + str(tl_state).ljust(6), True, (255, 255, 255)))
                    
                    # get distance to opposite stop bar

                    # find the vehicle based on the desired rolename
                    carlaVehicles = world.get_actors().filter('vehicle.*')
                    for current_vehicle in carlaVehicles:
                        currentAttributes = current_vehicle.attributes
                        if currentAttributes["role_name"] == args.svm_vehicle_name:
                                vehicle = current_vehicle

                    cur_vehicle_loc = vehicle.get_location()
                    cur_vehicle_loc_array = np.array([cur_vehicle_loc.x, cur_vehicle_loc.y, cur_vehicle_loc.z])

                    cur_vehicle_vector = opp_stop_bar_point - cur_vehicle_loc_array

                    dist_from_int_exit = round(get_dist_3d_vectors(start_vector,cur_vehicle_vector),3)
                    
                    
                    text_list.append(font.render(     ("Current Distance to Exit Intersection = ").rjust(42) + str(dist_from_int_exit).ljust(8) + " m", True, (255, 255, 255)))
                    text_list.append(font.render(     ("Distance to Exit Intersection at Red = ").rjust(42) + str(dist_from_int_exit_at_red).ljust(8) + " m", True, (255, 255, 255)))

                    text_list.append(font.render(     "-"*20, True, (255, 255, 255)))

                    if running:
                        text_list.append(font.render(     "----- RUNNING -----", True, (255, 255, 255)))
                    elif not started:
                        text_list.append(font.render(     "Press SPACE to Start", True, (255, 255, 255)))
                    else:
                        text_list.append(font.render(     "----- WAITING FOR SIGNAL -----", True, (255, 255, 255)))

                    # text_list.append(font.render(     "started = " + str(started), True, (255, 255, 255)))
                    # text_list.append(font.render(     "fresh_desired_phase = " + str(fresh_desired_phase), True, (255, 255, 255)))
                    # text_list.append(font.render(     "desired_phase_start = " + str(desired_phase_start), True, (255, 255, 255)))
                    # text_list.append(font.render(     "running = " + str(running), True, (255, 255, 255)))

                    # Draw the message on the screen
                    screen.fill(pygame.Color("black"))
                    
                    text_y_start = 20
                    text_y_diff = 30

                    for i_t,text in enumerate(text_list):
                        text_center = text.get_rect(center=(screen_width/2,text_y_start + text_y_diff *i_t))
                        screen.blit(text, text_center)
                        # screen.blit(text, (10, text_y_start + text_y_diff *i_t))

                    pygame.display.flip()

                    for event in pygame.event.get():
                        if event.type == pygame.QUIT:
                            # if we spawned the vehicle, destroy the vehicle after
                            if args.spawn_vehicle:
                                vehicle.destroy()
                            
                            pygame.quit()
                            sys.exit()
                        elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                            started = True

                    if started == True:
                        
                        if started == True and running == True:
                            print("RUNNING SCENARIO")
                            reached_end = move_vehicle_with_point(world, vehicle, vehicle_cfg['endPt'], vehicle_cfg['targetSpeedMPH'] / 2.23694)

                            if str(tl_state) == "Red" and dist_from_int_exit_at_red == "########":
                                dist_from_int_exit_at_red = dist_from_int_exit
                                

                        # need to make sure to start counting the start of the desired phase and no when script starts (in case of starting during desired phase)
                        elif str(tl_state) != vehicle_cfg["targetTrafficLightState"] and not fresh_desired_phase:
                            print("STARTED FRESH DESIRED PHASE")
                            fresh_desired_phase = True
                            desired_phase_start = 0

                        # once we are ensured we have a "fresh" desired phase, record time so we can determine how long the desired phase lasts 
                        # we need to do this because to protect against the default carla phase sequence which will flicker the traffic lights every so often
                        elif str(tl_state) == vehicle_cfg["targetTrafficLightState"] and fresh_desired_phase and desired_phase_start == 0:
                                print("IS DESIRED PHASE AND FRESH AND NO START")
                                
                                desired_phase_start = world.get_snapshot().timestamp.elapsed_seconds
                        
                        elif desired_phase_start != 0:
                            print("CHECKING DESIRED PHASE DURATION")
                            
                            current_time = world.get_snapshot().timestamp.elapsed_seconds

                            if current_time - desired_phase_start > 0.01:
                                print("DESIRED PHASE DURATION MET!")
                                running = True


                            
                vehicle.enable_constant_velocity(carla.Vector3D(x=0.0, y=0.0, z=0.0))

                print("Writing results to csv")
                scenario_results = {
                    "Scenario_#": [str(cfg_i + 1)],
                    "initial_distance_to_entry_lane_stop_bar": [str(scenario_dist_to_stopbar)],
                    "speed (mph)": [str(vehicle_cfg["targetSpeedMPH"])],
                    "Dist_at_red (m)": [str(dist_from_int_exit_at_red)]
                }

                df = pd.DataFrame(scenario_results)

                df.to_csv("test.csv", mode="a", index=False, header=False)


                time.sleep(3)
            except  KeyboardInterrupt:
                print('\nCancelled by user. Bye!')
                break

            except Exception as err_msg:
                print(err_msg)
                


        # if we spawned the vehicle, destroy the vehicle after
        if args.spawn_vehicle:
            vehicle.destroy()

        settings.synchronous_mode = False
        world.apply_settings(settings)

    # if x,y,z is passed, use those values for single run
    elif args.x and args.y and args.z:
        
        config = read_json(args.config)
        # THIS FUNCTIONALITY NEEDS WORK - CURRENTLY NOT NEEDED

        client = carla.Client(config["CARLAIp"], config["CARLAPort"])
        client.set_timeout(2.0)
        world = client.get_world()

        # Spawn the vehicle at the specified location with the initial speed
        vehicle = spawn_vehicle(world, 'vehicle.nissan.micra', config["vehicleModel"], args.x, args.y, args.z, args.yaw)
        print("Press SPACE key to start the vehicle")
        running = False

        # Set CARLA simulator as wall clock
        settings = world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = None # Set a variable time-step
        world.apply_settings(settings)

        # Set up the Pygame window and clock
        pygame.init()
        # Set the font and text for the message
        font = pygame.font.SysFont("monospace", 30)
        screen = pygame.display.set_mode((700, 500))

        clock = pygame.time.Clock()

        # Set up the Pygame window and clockstart vehicle movement", True, (255, 255, 255))

        text = font.render("Press SPACE to start vehicle movement", True, (255, 255, 255))

        # Draw the message on the screen
        screen.blit(text, (10, 10))
        pygame.display.flip()

        clock = pygame.time.Clock()

        # Game loop
        while True:
            world.tick()
            # Handle events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                    running = True

            # Clear the screen
            screen.fill((255, 255, 255))
            # If the vehicle is running,  move it and draw the speed on the screen
            if running:
                if args.stop == "time":
                    move_vehicle_with_duration(world, vehicle, args.duration, args.velocity / 3.6)
                elif args.stop == "point":
                    print("STOP POINT: " + str(args.point))
                    move_vehicle_with_point(world, vehicle, args.point, args.velocity / 3.6)

                settings.synchronous_mode = False
                world.apply_settings(settings)
                break
    
        settings.synchronous_mode = False
        world.apply_settings(settings)
    else:
        print("\nNo config file or x,y,z set. Please set a config file or x,y,z")
