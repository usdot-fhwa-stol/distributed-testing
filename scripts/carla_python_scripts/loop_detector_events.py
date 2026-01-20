import sys
import argparse
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
args = argparser.parse_args()

LOOP_DETECTORS = {
    "LD_1_1": {
        "intersection_id": 1,
        "signal_id": 100,
        "phase_id": 2,
        "bbox": [
            carla.Location(x=-634.81,y=769.45,z=0.2),
            carla.Location(x=-634.81,y=776.45,z=0.2),
            carla.Location(x=-636.81, y=776.45, z=0.2),
            carla.Location(x=-636.81, y=769.45, z=0.2)
        ],
        "state": False,
        "prev_state": False
    },
    "LD_1_2": {
        "intersection_id": 1,
        "signal_id": 100,
        "phase_id": 2,
        "bbox": [
            carla.Location(x=-661.51,y=760.45,z=0.2),
            carla.Location(x=-664.01,y=767.05,z=0.2),
            carla.Location(x=-666.01, y=766.25, z=0.2),
            carla.Location(x=-663.51, y=759.65, z=0.2)
        ],
        "state": False,
        "prev_state": False
    },
    "LD_1_3": {
        "intersection_id": 1,
        "signal_id": 100,
        "phase_id": 2,
        "bbox": [
            carla.Location(x=-620.61,y=758.55,z=0.2),
            carla.Location(x=-624.21,y=760.15,z=0.2),
            carla.Location(x=-625.11, y=758.15, z=0.2),
            carla.Location(x=-621.51, y=756.55, z=0.2)
        ],
        "state": False,
        "prev_state": False
    },
    "LD_1_4": {
        "intersection_id": 1,
        "signal_id": 100,
        "phase_id": 2,
        "bbox": [
            carla.Location(x=-623.50,y=782.44,z=0.2),
            carla.Location(x=-620.99,y=782.44,z=0.2),
            carla.Location(x=-620.99, y=784.44, z=0.2),
            carla.Location(x=-623.60, y=784.44, z=0.2)
        ],
        "state": False,
        "prev_state": False
    },
    "LD_2_1": {
        "intersection_id": 2,
        "signal_id": 100,
        "phase_id": 2,
        "bbox": [
            carla.Location(x=-488.36,y=766.16,z=0.2),
            carla.Location(x=-488.36,y=773.15,z=0.2),
            carla.Location(x=-490.36, y=773.15, z=0.2),
            carla.Location(x=-490.36, y=766.16, z=0.2)
        ],
        "state": False,
        "prev_state": False
    },
    "LD_2_2": {
        "intersection_id": 2,
        "signal_id": 100,
        "phase_id": 2,
        "bbox": [
            carla.Location(x=-515.66,y=766.56,z=0.2),
            carla.Location(x=-515.66,y=773.65,z=0.2),
            carla.Location(x=-517.66, y=773.65, z=0.2),
            carla.Location(x=-517.66, y=766.44, z=0.2)
        ],
        "state": False,
        "prev_state": False
    },
    "LD_2_3": {
        "intersection_id": 2,
        "signal_id": 100,
        "phase_id": 2,
        "bbox": [
            carla.Location(x=-477.59,y=757.05,z=0.2),
            carla.Location(x=-483.29,y=757.65,z=0.2),
            carla.Location(x=-483.29, y=755.65, z=0.2),
            carla.Location(x=-477.59, y=755.05, z=0.2)
        ],
        "state": False,
        "prev_state": False
    },
    "LD_2_4": {
        "intersection_id": 2,
        "signal_id": 100,
        "phase_id": 2,
        "bbox": [
            carla.Location(x=-477.79,y=781.05,z=0.2),
            carla.Location(x=-471.59,y=780.85,z=0.2),
            carla.Location(x=-471.59, y=782.85, z=0.2),
            carla.Location(x=-477.79, y=783.05, z=0.2)
        ],
        "state": False,
        "prev_state": False
    },
    "LD_3_1": {
        "intersection_id": 3,
        "signal_id": 100,
        "phase_id": 2,
        "bbox": [
            carla.Location(x=-382.39,y=754.75,z=0.2),
            carla.Location(x=-381.59,y=761.95,z=0.2),
            carla.Location(x=-383.59, y=762.15, z=0.2),
            carla.Location(x=-384.39, y=755.05, z=0.2)
        ],
        "state": False,
        "prev_state": False
    },
    "LD_3_2": {
        "intersection_id": 3,
        "signal_id": 100,
        "phase_id": 2,
        "bbox": [
            carla.Location(x=-412.49,y=757.95,z=0.2),
            carla.Location(x=-411.79,y=764.95,z=0.2),
            carla.Location(x=-413.79, y=765.15, z=0.2),
            carla.Location(x=-414.49, y=758.05, z=0.2)
        ],
        "state": False,
        "prev_state": False
    },
    "LD_4_1": {
        "intersection_id": 4,
        "signal_id": 100,
        "phase_id": 2,
        "bbox": [
            carla.Location(x=-134.61,y=729.86,z=0.2),
            carla.Location(x=-134.00,y=736.83,z=0.2),
            carla.Location(x=-135.99, y=737.01, z=0.2),
            carla.Location(x=-136.60, y=730.03, z=0.2)
        ],
        "state": False,
        "prev_state": False
    },
    "LD_4_2": {
        "intersection_id": 4,
        "signal_id": 100,
        "phase_id": 2,
        "bbox": [
            carla.Location(x=-164.11,y=732.56,z=0.2),
            carla.Location(x=-163.50,y=739.53,z=0.2),
            carla.Location(x=-165.49, y=739.71, z=0.2),
            carla.Location(x=-166.10, y=732.73, z=0.2)
        ],
        "state": False,
        "prev_state": False
    },
    "LD_4_3": {
        "intersection_id": 4,
        "signal_id": 100,
        "phase_id": 2,
        "bbox": [
            carla.Location(x=-122.40,y=720.83,z=0.2),
            carla.Location(x=-128.40,y=720.83,z=0.2),
            carla.Location(x=-128.40, y=718.83, z=0.2),
            carla.Location(x=-122.40, y=718.83, z=0.2)
        ],
        "state": False,
        "prev_state": False
    },
    "LD_4_4": {
        "intersection_id": 4,
        "signal_id": 100,
        "phase_id": 2,
        "bbox": [
            carla.Location(x=-119.70,y=746.63,z=0.2),
            carla.Location(x=-125.70,y=746.63,z=0.2),
            carla.Location(x=-125.70, y=744.63, z=0.2),
            carla.Location(x=-119.70, y=744.63, z=0.2)
        ],
        "state": False,
        "prev_state": False
    },
}

def point_in_detector(location, bbox):
    """Evaluates if a point is within a loop detector"""
    def cross(a, b, p):
        # vector AB x AP
        return (b.x - a.x)*(p.y - a.y) - (b.y - a.y)*(p.x - a.x)
    
    signs = []
    for i in range(len(bbox)):
        a = bbox[i]
        b = bbox[(i + 1) % len(bbox)]
        signs.append(cross(a, b, location))

    all_positive = all(s > 0 for s in signs)
    all_negative = all(s < 0 for s in signs)

    return all_positive or all_negative

def draw_loop_detectors(dbg, detectors, life_time=0.0):
    """Draw loop detector bounding boxes"""
    for det in detectors.values():
        bbox = det["bbox"]

        for i in range (len(bbox)):
            start = bbox[i]
            end = bbox[(i+1) % len(bbox)]
            dbg.draw_line(start, end, life_time=life_time, thickness=0.1, color=carla.Color(0,255,0))

def on_state_change(detector_id, detector):
    """Dummy callback for something happening once the state has changed"""
    print(
        f"Loop Detector {detector_id} has changed state:"
        f"State Change: {'ON' if detector['prev_state']==True else 'OFF'} -> {'ON' if detector['state']==True else 'OFF'}"
    )

def update_loop_detectors(world, detectors):
    vehicles = world.get_actors().filter("vehicle.*")

    for det_id, det in detectors.items():
        det["prev_state"] = det["state"]
        det["state"] = False

        bbox = det["bbox"]

        for vehicle in vehicles:
            vehicle_loc = vehicle.get_location()
            if point_in_detector(vehicle_loc, bbox):
                det["state"] = True
                break
        
        if det["state"] != det["prev_state"]:
            on_state_change(det_id, det)


try:
    client = carla.Client(args.host, args.port)
    client.set_timeout(5.0)
    world = client.get_world()
    dbg = world.debug

    print("Loop detector event watcher running...")

    try:
        while True:
            draw_loop_detectors(dbg, LOOP_DETECTORS, 0.15)
            update_loop_detectors(world,LOOP_DETECTORS)

            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nShutting down loop detector event watcher.")
except Exception as e:
    print(f"\nError occurred while checking detectors: {e}")
finally:
    print('\nDone!')