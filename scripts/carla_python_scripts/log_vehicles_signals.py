#!/usr/bin/env python3

# Copyright (c) 2019 University of Leicester
# Copyright (c) 2019 University of Sao Paulo
#
# This work is licensed under the terms of the MIT license.
# For a copy, see <https://opensource.org/licenses/MIT>.

# Allows controlling a vehicle with a keyboard and steering wheel. For a simpler and more
# documented example, please take a look at tutorial.py.

"""
Welcome to CARLA manual control with steering wheel Logitech G29.

To drive start by pressing the brake pedal.
Change your wheel_config.ini according to your steering wheel.

To find out the values of your steering wheel use jstest-gtk in Ubuntu.

"""

from __future__ import print_function


# ==============================================================================
# -- find carla module ---------------------------------------------------------
# ==============================================================================


import glob
import os
import sys
import evdev
from evdev import ecodes, InputDevice, ff

from find_carla_egg import find_carla_egg

carla_egg_file = find_carla_egg()

sys.path.append(carla_egg_file)

# ==============================================================================
# -- imports -------------------------------------------------------------------
# ==============================================================================


import carla

from carla import ColorConverter as cc

#from srunner.scenariomanager.atomic_scenario_criteria import ScenarioInfo
#from srunner.scenariomanager.timer import ScenarioTimer


import argparse
import collections
import datetime
import logging
import math
import time
import random
import re
import weakref

import json
import csv

if sys.version_info >= (3, 0):

    from configparser import ConfigParser

else:

    from ConfigParser import RawConfigParser as ConfigParser

try:
    import pygame
    from pygame.locals import KMOD_CTRL
    from pygame.locals import KMOD_SHIFT
    from pygame.locals import K_0
    from pygame.locals import K_9
    from pygame.locals import K_BACKQUOTE
    from pygame.locals import K_BACKSPACE
    from pygame.locals import K_COMMA
    from pygame.locals import K_DOWN
    from pygame.locals import K_ESCAPE
    from pygame.locals import K_F1
    from pygame.locals import K_LEFT
    from pygame.locals import K_PERIOD
    from pygame.locals import K_RIGHT
    from pygame.locals import K_SLASH
    from pygame.locals import K_SPACE
    from pygame.locals import K_TAB
    from pygame.locals import K_UP
    from pygame.locals import K_a
    from pygame.locals import K_c
    from pygame.locals import K_d
    from pygame.locals import K_h
    from pygame.locals import K_m
    from pygame.locals import K_p
    from pygame.locals import K_q
    from pygame.locals import K_r
    from pygame.locals import K_s
    from pygame.locals import K_w
    from pygame.locals import K_KP_ENTER
except ImportError:
    raise RuntimeError('cannot import pygame, make sure pygame package is installed')

try:
    import numpy as np
except ImportError:
    raise RuntimeError('cannot import numpy, make sure numpy package is installed')


# ==============================================================================
# -- Global functions ----------------------------------------------------------
# ==============================================================================


def find_weather_presets():
    rgx = re.compile('.+?(?:(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|$)')
    name = lambda x: ' '.join(m.group(0) for m in rgx.finditer(x))
    presets = [x for x in dir(carla.WeatherParameters) if re.match('[A-Z].+', x)]
    return [(getattr(carla.WeatherParameters, x), name(x)) for x in presets]


def get_actor_display_name(actor, truncate=250):
    name = ' '.join(actor.type_id.replace('_', '.').title().split('.')[1:])
    return (name[:truncate - 1] + u'\u2026') if len(name) > truncate else name


# ==============================================================================
# -- World ---------------------------------------------------------------------
# ==============================================================================


class World(object):
    def __init__(self, carla_world):
        
        self.world = carla_world
        self.player = None
        self.map = self.world.get_map()
        
    def tick(self, clock):
        if len(self.world.get_actors()) < 1:
            print("No actors -- waiting for actors to join")
            return True
        return True

    #def tick(self, world, clock):
        #self._notifications.tick(world, clock)

        #t = world.player.get_transform()
        #v = world.player.get_velocity()
        #c = world.player.get_control()


        #heading = 'N' if abs(t.rotation.yaw) < 89.5 else ''
        #heading += 'S' if abs(t.rotation.yaw) > 90.5 else ''
        #heading += 'E' if 179.5 > t.rotation.yaw > 0.5 else ''
        #heading += 'W' if -0.5 > t.rotation.yaw > -179.5 else ''
        




# ==============================================================================
# -- game_loop() ---------------------------------------------------------------
# ==============================================================================


def game_loop(args):
    pygame.init()
    pygame.font.init()
    world = None
    try:
        client = carla.Client(args.host, args.port)
        client.set_timeout(2.0)

        _failed = True
        num_of_attempts = 0
        while _failed:
            try:
                client = carla.Client(args.host, int(args.port))
                client.set_timeout(2.0)
                client.get_world()
                _failed = False
            except Exception as err:
                # print(err)
                num_of_attempts+=1
                print("Attempting to connect to carla: Test {}".format(num_of_attempts))
                time.sleep(1)
                continue

        print("Connected to CARLA server!")
        

        world = World(client.get_world())
        clock = pygame.time.Clock()
        
        
        csvout=open(args.outfile,'w')
        csv_w = csv.writer(csvout)
        
        headers = ["OS Timestamp","CARLA Timestamp","Vehicle Lat","Vehicle Long","Vehicle Heading"]
        csv_w.writerow(headers)
	
        initialVehicles = world.world.get_actors().filter('vehicle.*')
        print("Current Actors: " + str(initialVehicles))
        initialVehicleId = initialVehicles[0].id
        print("Logging data for vehicle: " + str(initialVehicleId))
	
	
        while True:
            clock.tick_busy_loop(60)
            
            currentRow = []
            
            osTimestamp = time.time()
            currentRow.append(osTimestamp)
            
            currentWorldSnapshot = world.world.get_snapshot()
            
            currentSimTimestamp = currentWorldSnapshot.timestamp
            currentRow.append(currentSimTimestamp.platform_timestamp)
            
            currentVehicleSnapshot = currentWorldSnapshot.find(initialVehicleId)
            #print("currentVehicleSnapshot: " + str(currentVehicleSnapshot))
            
            currentVehicleTransform = currentVehicleSnapshot.get_transform()
            print("currentVehicleTransform: " + str(currentVehicleTransform))
            #print("currentVehicleTransform: " + str(currentVehicleTransform.location))
            
            currentVehicleGeolocation = world.map.transform_to_geolocation(currentVehicleTransform.location)
            print("currentVehicleGeolocation: " + str(currentVehicleGeolocation))
            #print("currentVehicleGeolocation_location_to_gps: " + str(_location_to_gps(currentVehicleTransform.location)))
            currentVehicleLat = currentVehicleGeolocation.latitude
            currentRow.append(currentVehicleLat)
            
            currentVehicleLong = currentVehicleGeolocation.longitude
            currentRow.append(currentVehicleLong)
            currentVehicleHeading = currentVehicleTransform.rotation.yaw
            currentRow.append(currentVehicleHeading)          
            
            
            #currentActorSnapshot = currentWorldSnapshot.ActorSnapshot
            
            
            
            csv_w.writerow(currentRow)
            
            
            if not world.tick(clock):
                break
            
            
            
            print(" ")


    finally:
        pygame.quit()
        csvout.close()


def _location_to_gps(location):
    """
    Convert from world coordinates to GPS coordinates
    :param lat_ref: latitude reference for the current map
    :param lon_ref: longitude reference for the current map
    :param location: location to translate
    :return: dictionary with lat, lon and height
    """
    lat_ref = 38.954976 
    lon_ref = -77.148030
    
    EARTH_RADIUS_EQUA = 6378137.0   # pylint: disable=invalid-name
    scale = math.cos(lat_ref * math.pi / 180.0)
    mx = scale * lon_ref * math.pi * EARTH_RADIUS_EQUA / 180.0
    my = scale * EARTH_RADIUS_EQUA * math.log(math.tan((90.0 + lat_ref) * math.pi / 360.0))
    mx += location.x
    my -= location.y

    lon = mx * 180.0 / (math.pi * EARTH_RADIUS_EQUA * scale)
    lat = 360.0 * math.atan(math.exp(my / (EARTH_RADIUS_EQUA * scale))) / math.pi - 90.0
    z = location.z

    return {'lat': lat, 'lon': lon, 'z': z}


# ==============================================================================
# -- main() --------------------------------------------------------------------
# ==============================================================================


def main():
    argparser = argparse.ArgumentParser(
        description='CARLA Manual Control Client')
    argparser.add_argument(
        '-v', '--verbose',
        action='store_true',
        dest='debug',
        help='print debug information')
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
        '-a', '--autopilot',
        action='store_true',
        help='enable autopilot')
    argparser.add_argument(
        '--res',
        metavar='WIDTHxHEIGHT',
        default='1920x1080',
        help='window resolution (default: 1920x1080)')
    argparser.add_argument(
        '--filter',
        metavar='PATTERN',
        default='vehicle.*',
        help='actor filter (default: "vehicle.*")')
    argparser.add_argument(
        '--fullscreen',
        action='store_true',
        help='enable fullscreen mode')
    argparser.add_argument(
        '-o', '--outfile',
        metavar='P',
        default='carla_out.csv',
        help='CSV output filename (default: carla_out.csv)')
    args = argparser.parse_args()

    args.width, args.height = [int(x) for x in args.res.split('x')]

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(format='%(levelname)s: %(message)s', level=log_level)

    logging.info('listening to server %s:%s', args.host, args.port)

    print(__doc__)

    try:

        game_loop(args)

    except KeyboardInterrupt:
        print('\nCancelled by user. Bye!')


if __name__ == '__main__':

    main()
