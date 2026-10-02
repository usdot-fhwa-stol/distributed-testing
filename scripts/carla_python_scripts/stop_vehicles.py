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



import carla

from carla import VehicleLightState as vls

import argparse
import logging
from numpy import random

def safe_control(vehicle, hand_brake):
    try:
        if not vehicle.is_alive:
            return False
        ctrl = carla.VehicleControl()
        ctrl.hand_brake = hand_brake
        vehicle.apply_control(ctrl)
        return True
    except Exception as e:
        print(f'\tWARNING: could not control {vehicle.id}: {e}')
        return False

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
        '-v','--verbose',
        action='store_true',
        help='Enable verbose logging')
    argparser.add_argument(
        '-e', '--exclude',
        metavar='VEHICLE_NAME',
        type=str,
        help='Exclude these vehicles when stopping (comma separated, Ex: VW-MAN-1,ECON-MAN-1)')
    args = argparser.parse_args()

    logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)

    client = carla.Client(args.host, args.port)
    client.set_timeout(20.0)

    try:

        already_stopped_once = set()

        if args.exclude:
            vehicles_to_exclude = (args.exclude).split(",")
        else:
            vehicles_to_exclude = []

        max_checks = 60


        for i in range(max_checks):

            try:
                world = client.get_world()
                vehicles = world.get_actors().filter('vehicle.*')
            except Exception as e:
                print(f'WARNING: could not fetch actors: {e}')
                time.sleep(1)
                continue

            if args.verbose: print(f"Checking for new vehicles to stop [{max_checks - i}]")

            for vehicle in vehicles:
                
                role = vehicle.attributes.get("role_name", "")
                if role in vehicles_to_exclude:
                    if args.verbose:
                        print("\tSkipping: " + role)
                    continue
                if vehicle.id in already_stopped_once:
                    if args.verbose:
                        print("\tAlready stopped: " + (role or str(vehicle.id)))
                    continue

                print(f'\tStopping vehicle: {role or vehicle.id}')
                if safe_control(vehicle, True):
                    stopped_vehicles.append(vehicle)
                    already_stopped_once.add(vehicle.id)

            if stopped_vehicles:
                time.sleep(5)
                for vehicle in stopped_vehicles:
                    safe_control(vehicle, False)

            time.sleep(1)
    except Exception as errMsg:
        print(f'ERROR: {errMsg}')
        
    finally:

        time.sleep(0.5)

if __name__ == '__main__':

    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        print('\nDONE STOPPING VEHICLES')
