import carla
import cv2
import numpy as np
import queue
import time


def main():
    client = carla.Client("localhost", 2000)
    client.set_timeout(10.0)

    world = client.get_world()

    print(f"Connected to CARLA. Map: {world.get_map().name}")

    # Create the RGB camera
    blueprint_library = world.get_blueprint_library()
    camera_bp = blueprint_library.find("sensor.camera.rgb")

    camera_bp.set_attribute("image_size_x", "1920")
    camera_bp.set_attribute("image_size_y", "1080")
    camera_bp.set_attribute("fov", "70")
    camera_bp.set_attribute("enable_postprocess_effects", "True")

    # Fixed world position: adjust these coordinates for your map
    
    ## RFS spectator location
    # transform = carla.Transform(
    #     carla.Location(x=219.0, y=131.0, z=169.0),
    #     carla.Rotation(pitch=-33.0, yaw=236.0, roll=0.0)
    # )

    ## RFS zoomed location
    transform = carla.Transform(
        carla.Location(x=9.1715, y=-70.0701, z=39.8687),
        carla.Rotation(pitch=-25.0499, yaw=-37.5619, roll=0.0)
    )

    camera = None
    image_queue = queue.Queue(maxsize=2)
    image_count = 0

    try:
        camera = world.spawn_actor(camera_bp, transform)

        print(f"Camera spawned: {camera}")
        print(f"Camera location: {camera.get_location()}")
        print("Waiting for camera images...")

        # This callback runs asynchronously.
        # Do not call cv2.imshow() here.
        def on_image(image):
            try:
                if image_queue.full():
                    try:
                        image_queue.get_nowait()
                    except queue.Empty:
                        pass

                image_queue.put_nowait(image)

            except queue.Full:
                pass

        camera.listen(on_image)

        # OpenCV GUI operations run on the main thread.
        cv2.namedWindow("CARLA Fixed Camera", cv2.WINDOW_NORMAL)

        start_time = time.time()

        while True:
            try:
                # Get the latest available camera image.
                image = image_queue.get(timeout=0.1)

                # CARLA camera data is BGRA.
                array = np.frombuffer(
                    image.raw_data,
                    dtype=np.uint8
                ).reshape((image.height, image.width, 4))

                frame = array[:, :, :3].copy()

                cv2.imshow("CARLA Fixed Camera", frame)

                image_count += 1

                if image_count == 1:
                    print(
                        f"First image received! "
                        f"Frame={image.frame}, "
                        f"Resolution={image.width}x{image.height}"
                    )

                if image_count % 100 == 0:
                    print(f"Received {image_count} camera images.")

            except queue.Empty:
                # Tell us if no image has arrived.
                if time.time() - start_time > 5:
                    print(
                        "Still waiting for camera images. "
                        "Check whether the CARLA simulation is advancing."
                    )
                    start_time = time.time()

            # Process GUI events on the main thread.
            key = cv2.waitKey(1) & 0xFF

            if key == ord("q") or key == 27:
                break

    except Exception as exc:
        print(f"Error: {exc}")
        raise

    finally:
        if camera is not None:
            camera.stop()
            camera.destroy()

        cv2.destroyAllWindows()
        print("Camera cleaned up.")


if __name__ == "__main__":
    main()