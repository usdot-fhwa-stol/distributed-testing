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
        "bbox": {
            "min": carla.Location(x=-636.800781,y=769.605347,z=0.2),
            "max": carla.Location(x=-634.800781,y=776.605347,z=0.2),
        },
        "state": False,
        "prev_state": False
    }
}

def point_in_detector(location, bbox):
    """Evaluates if a point is within a loop detector"""
    return (
        bbox["min"].x <= location.x <= bbox["max"].x and
        bbox["min"].y <= location.y <= bbox["max"].y
        #bbox["min"].z <= location.z <= bbox["max"].z
    )

def draw_loop_detectors(dbg, detectors, life_time=0.0):
    """Draw loop detector bounding boxes"""
    for det in detectors.values():
        bbox = det["bbox"]

        center = (bbox["min"] + bbox["max"]) * 0.5
        extent = (bbox["max"] - bbox["min"]) * 0.5

        dbg.draw_box(
            box=carla.BoundingBox(center, extent),
            rotation=carla.Rotation(),
            thickness=0.1,
            color=carla.Color(0, 255, 0),
            life_time=life_time
        )

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

    draw_loop_detectors(dbg, LOOP_DETECTORS)

    print("Loop detector event watcher running...")

    try:
        while True:
            update_loop_detectors(world,LOOP_DETECTORS)

            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nShutting down loop detector event watcher.")
except Exception as e:
    print(f"\nError occurred while checking detectors: {e}")
finally:
    print('\nDone!')