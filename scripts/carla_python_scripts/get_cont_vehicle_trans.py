import glob
import os
import sys
import time

from find_carla_egg import find_carla_egg

carla_egg_file = find_carla_egg()

sys.path.append(carla_egg_file)

import carla

actor_list=[]
try:
    client = carla.Client('localhost', 2000)
    client.set_timeout(5.0)
    world = client.get_world()
    # map = world.get_map()
    # Get actor information (Vehicles)
    vehicle_list = world.get_actors().filter('vehicle.*')
    # Print all index corresponding to all traffic vehicles in scene (CarlaUE4)
    for index, vehicle in enumerate(vehicle_list, start=1):
        print(str(vehicle.attributes))

        if vehicle.attributes["role_name"] == "TFHRC-MANUAL-2":
            while(True):
                cur_trans = vehicle.get_transform()
                print(str(cur_trans))
                time.sleep(0.1)


        world.debug.draw_string(vehicle.get_location(), str(vehicle.attributes["role_name"]), draw_shadow=False,
                                             color=carla.Color(r=255, g=0, b=0), life_time=30,
                                             persistent_lines=True)
    ################################################################################################
    # Once you see all index number, you can manually change its states and timimg.
    # Your signal control scripts.
finally:
    print('Cleaning up actors...')
    for actor in actor_list:
        actor.destroy()
    print('Done, Actors cleaned-up successfully!')