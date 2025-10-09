import glob
import os
import sys
import time
from collections import defaultdict

from find_carla_egg import find_carla_egg

carla_egg_file = find_carla_egg()
sys.path.append(carla_egg_file)

import carla

def traffic_light_state_name(state):
    try:
        return state.name
    except Exception:
        mapping = {
            carla.TrafficLightState.Red: "Red",
            carla.TrafficLightState.Yellow: "Yellow",
            carla.TrafficLightState.Green: "Green",
            carla.TrafficLightState.Off: "Off"
        }
        return mapping.get(state, str(state))

def print_trafficLight_info(tl):
    try:
        tl_id = tl.id
        tl_type = tl.type_id
        transform = tl.get_transform()
        state = tl.get_state()
        print(f"TL id={tl_id} type={tl_type}")
        print(f"    Transform: location=({transform.location.x:.2f}, {transform.location.y:.2f}, {transform.location.z:.2f})"
            f"rotation=({transform.rotation.pitch:.1f},{transform.rotation.yaw:.1f},{transform.rotation.roll:.1f})")
        print(f"    State: {traffic_light_state_name(state)}")

    except Exception as e:
        print(f"    (error reading traffic light info: {e})")

def main(host='127.0.0.1', port=2000, timeout=10.0):
    client = carla.Client(host,port)
    client.set_timeout(timeout)

    world = client.get_world()
    print("Connected to CARLA world:",world)

    try:
        traffic_lights = world.get_actors().filter('traffic.traffic_light*')
    except Exception:
        all_actors = world.get_actors()
        traffic_lights = [a for a in all_actors if 'traffic_light' in a.type_id]

    for tl in traffic_lights:
        print_trafficLight_info(tl)
        print('')

if __name__ == '__main__':
    main()