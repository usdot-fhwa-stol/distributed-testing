import carla
import cv2
import numpy as np
import queue
import time
import os

### CARLA Connection Defaults
CARLA_HOST = os.getenv("VUG_LOCAL_ADDRESS")
CARLA_PORT = 2000
CARLA_TIMEOUT = 10.0

### CARLA Camera Settings
CAMERA_WIDTH = 1920
CAMERA_HEIGHT = 1080
CAMERA_FOV = 70
CAMERA_POSTPROCESS = True
CAMERA_SENSOR_TICK = 0.0

# Maximum number of frames buffered per camera. Older frames are discarded to keep the display responsive
IMAGE_QUEUE_SIZE = 2

### Camera Configurations
# One camera is spawned for every entry in this list
# location: (x,y,z)
# rotation: (pitch, yaw, roll)
# TODO: Add, remove, or modify entries to configure your camera
CAMERA_CONFIGS = [
    {
        "name": "Camera 1 - Top Down (Town10)",
        "location": (-41.353390,73.122391,100.442856),
        "rotation": (-87.815765,-89.706406,0.0),
    },
    {
        "name": "Camera 2 - Street View (Town10)",
        "location": (-51.879086,24.768240,3.243282),
        "rotation": (-5.975470,79.513199,0.0),
    },
]

### Image Callback
def make_image_callback(image_queue):
    """
    Create an independent callback for a camera's image queue.

    CARLA invokes this asynchronously. OpenCV GUI operations are intentionally kept out of this callback.
    """

    def on_image(image):
        try:
            # Discard an older frame if the queue is full
            if image_queue.full():
                try:
                    image_queue.get_nowait()
                except queue.Empty:
                    pass

            image_queue.put_nowait(image)

        except queue.Full:
            pass

    return on_image


def main():

    if not CARLA_HOST:
        raise RuntimeError(
            "Environment variable VUG_LOCAL_ADDRESS is not set."
            "Set it to the CARLA server hostname or IP address."
        )

    if not CAMERA_CONFIGS:
        raise RuntimeError(
            "CAMERA_CONFIGS is empty. Configure at least one camera."
        )

    client = carla.Client(CARLA_HOST, CARLA_PORT)
    client.set_timeout(CARLA_TIMEOUT)

    world = client.get_world()

    print(f"Connected to CARLA at {CARLA_HOST}:{CARLA_PORT}")
    print(f"Map: {world.get_map().name}")
    print(f"Configured cameras: {len(CAMERA_CONFIGS)}")

    # Prepare Camera Blueprint
    blueprint_library = world.get_blueprint_library()
    camera_bp = blueprint_library.find("sensor.camera.rgb")

    camera_bp.set_attribute("image_size_x", str(CAMERA_WIDTH))
    camera_bp.set_attribute("image_size_y", str(CAMERA_HEIGHT))
    camera_bp.set_attribute("fov", str(CAMERA_FOV))
    camera_bp.set_attribute("enable_postprocess_effects", str(CAMERA_POSTPROCESS))
    camera_bp.set_attribute("sensor_tick", str(CAMERA_SENSOR_TICK))

    # Camera State
    cameras = []
    try:
        #Spawn Cameras
        for config in CAMERA_CONFIGS:
            camera_name = config["name"]

            location = carla.Location(
                x=config["location"][0],
                y=config["location"][1],
                z=config["location"][2]
            )

            rotation = carla.Rotation(
                pitch=config["rotation"][0],
                yaw=config["rotation"][1],
                roll=config["rotation"][2]
            )

            transform = carla.Transform(location, rotation)

            image_queue = queue.Queue(maxsize=IMAGE_QUEUE_SIZE)
            
            print(f"\nSpawning {camera_name}...")
            camera = world.spawn_actor(camera_bp, transform)
            camera_state = {
                "name": camera_name,
                "window_name": camera_name,
                "actor": camera,
                "image_queue": image_queue,
                "image_count": 0,
                "last_image_time": time.monotonic(),
                "last_warning_time": 0.0,
            }
            cameras.append(camera_state)
            print(f"\tActor ID: {camera.id}")
            print(f"\tLocation: {camera.get_location()}")
            print(f"\tRotation: {camera.get_transform().rotation}")

            camera.listen(make_image_callback(image_queue))

            # Create OpenCV Window
            cv2.namedWindow(
                camera_state["window_name"],
                cv2.WINDOW_NORMAL
            )

        print(f"\nSuccessfully spawned {len(cameras)} camera(s).")
        print("Waiting for camera images...")
        print("Press Q or ESC to exit.\n")

        # Video Streaming Loop
        while True:
            current_time = time.monotonic()
            for camera_state in cameras:
                image_queue = camera_state["image_queue"]
                latest_image = None

                # Retrieve the newest available frame, draining older frames to minimize latency
                while True:
                    try:
                        latest_image = image_queue.get_nowait()
                    except queue.Empty:
                        break

                if latest_image is not None:
                    image = latest_image
                    # CARLA camera data is BGRA, first three channels are BGR, expected by OpenCV
                    array = np.frombuffer(
                        image.raw_data,
                        dtype=np.uint8
                    ).reshape(
                        (image.height, image.width, 4)
                    )

                    frame = array[:,:,:3].copy()

                    cv2.imshow(
                        camera_state["window_name"],
                        frame
                    )

                    camera_state["image_count"] += 1
                    camera_state["last_image_time"] = current_time

                    image_count = camera_state["image_count"]

                    if image_count == 1:
                        print(
                            f"[{camera_state['name']}] "
                            f"First image received! "
                            f"Frame={image.frame}, "
                            f"Resolution="
                            f"{image.width}x{image.height}"
                        )

                    if image_count % 100 == 0:
                        print(
                            f"[{camera_state['name']}] "
                            f"Received {image_count} images."
                        )

                elif (current_time - camera_state["last_image_time"] > 5.0) and (current_time - camera_state["last_warning_time"] > 5.0):
                    print(
                        f"[{camera_state['name']}] "
                        "Still waiting for camera images. "
                        "Check the camera configuration and "
                        "whether the CARLA simulation is advancing."
                    )

                    camera_state["last_warning_time"] = current_time
            
            # Process GUI events on the main thread.
            key = cv2.waitKey(1) & 0xFF

            if key == ord("q") or key == 27: #ESC
                print("\nExit requested.")
                break
    except Exception as exc:
        print(f"Error: {exc}")
        raise

    finally:
        # Cleanup
        print("\nCleaning up cameras...")
        for camera_state in cameras:
            camera = camera_state["actor"]

            try:
                if camera.is_alive:
                    camera.stop()
            except Exception as e:
                print(f"Warning: Could not stop {camera_state['name']}: {e}")

            try:
                if camera.is_alive:
                    camera.destroy()
                    print(f"Destroyed {camera_state['name']}.")
            except Exception as e:
                print(f"Warning: Could not destroy {camera_state['name']}: {e}")

        cv2.destroyAllWindows()

        print("Camera cleanup complete")

if __name__ == "__main__":
    main()