#!/usr/bin/env python3

# Copyright (c) 2019 Computer Vision Center (CVC) at the Universitat Autonoma de
# Barcelona (UAB).
#
# This work is licensed under the terms of the MIT license.
# For a copy, see <https://opensource.org/licenses/MIT>.

"""Spawn NPCs into the simulation"""

import glob
import os
import sys
import time
from find_carla_egg import find_carla_egg

carla_egg_file = find_carla_egg()

sys.path.append(carla_egg_file)
    
    
import carla

from carla import VehicleLightState as vls

import argparse
import logging
from numpy import random

def main():
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
        '-n', '--number-of-vehicles',
        metavar='N',
        default=0,
        type=int,
        help='number of vehicles (default: 10)')
    argparser.add_argument(
        '-w', '--number-of-walkers',
        metavar='W',
        default=0,
        type=int,
        help='number of walkers (default: 50)')
    argparser.add_argument(
        '--safe',
        action='store_true',
        help='avoid spawning vehicles prone to accidents')
    argparser.add_argument(
        '--filterv',
        metavar='PATTERN',
        default='vehicle.*',
        help='vehicles filter (default: "vehicle.*")')
    argparser.add_argument(
        '--filterw',
        metavar='PATTERN',
        default='walker.pedestrian.*',
        help='pedestrians filter (default: "walker.pedestrian.*")')
    argparser.add_argument(
        '--tm-port',
        metavar='P',
        default=8000,
        type=int,
        help='port to communicate with TM (default: 8000)')
    argparser.add_argument(
        '--sync',
        action='store_true',
        help='Synchronous mode execution')
    argparser.add_argument(
        '--hybrid',
        action='store_true',
        help='Enanble')
    argparser.add_argument(
        '-s', '--seed',
        metavar='S',
        type=int,
        help='Random device seed')
    argparser.add_argument(
        '--car-lights-on',
        action='store_true',
        default=False,
        help='Enanble car lights')
    args = argparser.parse_args()

    logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)

    vehicles_list = []
    walkers_list = []
    all_id = []
    client = carla.Client(args.host, args.port)
    client.set_timeout(10.0)
    synchronous_master = False
    random.seed(args.seed if args.seed is not None else int(time.time()))

    try:
        world = client.get_world()

        traffic_manager = client.get_trafficmanager(args.tm_port)
        traffic_manager.set_global_distance_to_leading_vehicle(1.0)
        if args.hybrid:
            traffic_manager.set_hybrid_physics_mode(True)
        if args.seed is not None:
            traffic_manager.set_random_device_seed(args.seed)


        if args.sync:
            settings = world.get_settings()
            traffic_manager.set_synchronous_mode(True)
            if not settings.synchronous_mode:
                synchronous_master = True
                settings.synchronous_mode = True
                settings.fixed_delta_seconds = 0.05
                world.apply_settings(settings)
            else:
                synchronous_master = False

        blueprints = world.get_blueprint_library().filter(args.filterv)
        blueprintsWalkers = world.get_blueprint_library().filter(args.filterw)

        if args.safe:
            blueprints = [bp for bp in blueprints if bp.has_attribute('number_of_wheels') and int(bp.get_attribute('number_of_wheels')) == 4]

        excluded_ids = ['isetta', 'carlacola', 'cybertruck', 't2']
        blueprints = [bp for bp in blueprints if not any(bp.id.endswith(x) for x in excluded_ids)]

        blueprints = sorted(blueprints, key=lambda bp: bp.id)

        spawn_points = world.get_map().get_spawn_points()
        number_of_spawn_points = len(spawn_points)

        if args.number_of_vehicles > number_of_spawn_points:
            logging.warning("Requested %d vehicles, but only %d spawn points available", args.number_of_vehicles, available_spawns)
            args.number_of_vehicles = available_spawns

        random.shuffle(spawn_points)

        vls = carla.VehicleLightState
        light_state = vls.NONE
        if args.car_lights_on:
            light_state = vls.Position | vls.LowBeam | vls.LowBeam

        # ---------------------------
        # Spawn vehicles individually
        # --------------------------

        spawned_vehicles = []

        for n in range(args.number_of_vehicles):
            transform = spawn_points[n]
            blueprint = random.choice(blueprints)
            
            if blueprint.has_attribute('color'):
                values = blueprint.get_attribute('color').recommended_values
                if values:
                    blueprint.set_attribute('color', random.choice(values))

            if blueprint.has_attribute('driver_id'):
                values = blueprint.get_attribute('driver_id').recommended_values
                if values:
                    blueprint.set_attribute('driver_id', random.choice(values))

            blueprint.set_attribute('role_name', 'autopilot')

            vehicle = world.try_spawn_actor(blueprint, transform)
            if vehicle is not None:
                vehicles_list.append(vehicle.id)
                spawned_vehicles.append(vehicle)
                logging.info(f"Spawned vehicle {vehicle.id}")
                time.sleep(0.1)

            for _ in range(5):
                world.wait_for_tick()

            for vehicle in spawned_vehicles:
                try:
                    vehicle.set_autopilot(True, traffic_manager.get_port())
                except Exception as e:
                    logging.warning(f"Failed to set autopilot for vehicle {vehicle.id}: {e}")

        # -------------
        # Spawn Walkers
        # -------------
        # some settings
        percentagePedestriansRunning = 0.0      # how many pedestrians will run
        percentagePedestriansCrossing = 0.0     # how many pedestrians will walk through the road
        # 1. take all the random locations to spawn
        spawn_points = []
        for i in range(args.number_of_walkers):
            loc = world.get_random_location_from_navigation()
            if (loc != None):
                spawn_point = carla.Transform(loc)
                spawn_points.append(spawn_point)
            else:
                logging.warning("No navigation point found for walker %d", i)
        # 2. we spawn the walker object
        for spawn_point in spawn_points:
            walker_bp = random.choice(blueprintsWalkers)
            # set as not invincible
            if walker_bp.has_attribute('is_invincible'):
                walker_bp.set_attribute('is_invincible', 'false')
            # set the max speed
            if walker_bp.has_attribute('speed'):
                if (random.random() > percentagePedestriansRunning):
                    # walking
                    walker_speed.append(walker_bp.get_attribute('speed').recommended_values[1])
                else:
                    # running
                    walker_speed.append(walker_bp.get_attribute('speed').recommended_values[2])
            else:
                print("Walker has no speed")
                walker_speed.append(0.0)
            
            walker = world.try_spawn_actor(walker_bp, spawn_point)
            if walker is None:
                logging.warning(f"Failed to spawn walker at {spawn_point.location}")
                continue
            
            walkers_list.append({"id": walker.id})
            time.sleep(0.1)

        
        # 3. we spawn the walker controller
        walker_controller_bp = world.get_blueprint_library().find('controller.ai.walker')
        
        for i in range(len(walkers_list)):
            controller = world.try_spawn_actor(walker_controller_bp, carla.Transform(), walkers_list[i]["id"])
            if controller is None:
                logging.warning(f"Failed to spawn controller for walker {walkers_list[i]['id']}")
                continue

            walkers_list[i]["con"] = controller.id
            time.sleep(0.1)

        # 4. we put altogether the walkers and controllers id to get the objects from their id
        for i in range(len(walkers_list)):
            all_id.append(walkers_list[i]["con"])
            all_id.append(walkers_list[i]["id"])
        all_actors = world.get_actors(all_id)

        # wait for a tick to ensure client receives the last transform of the walkers we have just created
        if not args.sync or not synchronous_master:
            world.wait_for_tick()
        else:
            world.tick()

        # 5. initialize each controller and set target to walk to (list is [controler, actor, controller, actor ...])
        # set how many pedestrians can cross the road
        world.set_pedestrians_cross_factor(percentagePedestriansCrossing)
        for i in range(0, len(all_id), 2):
            # start walker
            all_actors[i].start()
            # set walk to random point
            all_actors[i].go_to_location(world.get_random_location_from_navigation())
            # max speed
            all_actors[i].set_max_speed(float(walker_speed[int(i/2)]))

        print('spawned %d vehicles and %d walkers, press Ctrl+C to exit.' % (len(vehicles_list), len(walkers_list)))

        # example of how to use parameters
        traffic_manager.global_percentage_speed_difference(30.0)

        while True:
            if args.sync and synchronous_master:
                world.tick()
            else:
                world.wait_for_tick()

            for vehicle_id in vehicles_list:
                actor = world.get_actor(vehicle_id)
                if actor is not None:
                    loc = actor.get_location()
                    alive = actor.is_alive
                    logging.info(f"Vehicle {vehicle_id} isAlive:{alive} at ({loc.x:.2f}, {loc.y:.2f}, {loc.z:.2f})")
                else:
                    logging.warning(f"Vehicle {vehicle_id} no longer exists")

    finally:

        if args.sync and synchronous_master:
            settings = world.get_settings()
            settings.synchronous_mode = False
            settings.fixed_delta_seconds = None
            world.apply_settings(settings)

        print('\ndestroying %d vehicles' % len(vehicles_list))
        client.apply_batch([carla.command.DestroyActor(x) for x in vehicles_list])

        # stop walker controllers (list is [controller, actor, controller, actor ...])
        for i in range(0, len(all_id), 2):
            all_actors[i].stop()

        print('\ndestroying %d walkers' % len(walkers_list))
        client.apply_batch([carla.command.DestroyActor(x) for x in all_id])

        time.sleep(0.5)

if __name__ == '__main__':

    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        print('\nDONE SPAWNING NPCS')
