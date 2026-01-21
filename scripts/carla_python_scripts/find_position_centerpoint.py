import sys
import argparse
import os
import pygame
import math

# ------------------------------------------------------------------------------
# 1. CARLA Import Setup (User Specified)
# ------------------------------------------------------------------------------
try:
    from find_carla_egg import find_carla_egg
    carla_egg_file = find_carla_egg()
    sys.path.append(carla_egg_file)
except ImportError:
    print("Warning: 'find_carla_egg' module not found. Assuming standard carla install or pythonpath.")

import carla

# ------------------------------------------------------------------------------
# Constants & Settings
# ------------------------------------------------------------------------------
START_X, START_Y, START_Z = 0.0, 0.0, 2.0
INITIAL_STEP = 1.0         # Meters per key press
STEP_INCREMENT = 0.5       # Step adjustment size
ROTATION_INCREMENT = 5.0   # Degrees per key press

# Pygame Window Settings
SCREEN_WIDTH = 300
SCREEN_HEIGHT = 500
FONT_SIZE = 20

def draw_world_axes(world, location, length=1.0, thickness=0.05, arrow_size=0.1, life_time=0.1):
    """
    Draws a small coordinate system at the specified 'location'.
    """
    debug = world.debug
    
    end_x = carla.Location(location.x + length, location.y, location.z)
    end_y = carla.Location(location.x, location.y + length, location.z)
    end_z = carla.Location(location.x, location.y, location.z + length)

    debug.draw_arrow(location, end_x, thickness=thickness, arrow_size=arrow_size, color=carla.Color(255, 0, 0), life_time=life_time)
    debug.draw_arrow(location, end_y, thickness=thickness, arrow_size=arrow_size, color=carla.Color(0, 255, 0), life_time=life_time)
    debug.draw_arrow(location, end_z, thickness=thickness, arrow_size=arrow_size, color=carla.Color(0, 0, 255), life_time=life_time)

def main(args):
    # -----------------------------
    # 2. Initialize CARLA
    # -----------------------------
    print(f"Connecting to CARLA at {args.host}:{args.port}...")
    try:
        client = carla.Client(args.host, args.port)
        client.set_timeout(5.0)
        world = client.get_world()
        carla_map = world.get_map()
        spectator = world.get_spectator()
        print("Connected successfully.")
    except Exception as e:
        print(f"Error connecting to CARLA: {e}")
        return

    # -----------------------------
    # 3. File Handling (Placeholder)
    # -----------------------------
    if args.file:
        if os.path.exists(args.file):
            print(f"File provided: {args.file} (Custom loading logic goes here)")
        else:
            print(f"Warning: File {args.file} not found.")

    # -----------------------------
    # 4. Initialize Pygame
    # -----------------------------
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("CARLA Point Locator")
    font = pygame.font.SysFont("monospace", FONT_SIZE, bold=True)
    clock = pygame.time.Clock()

    # -----------------------------
    # 5. State Setup
    # -----------------------------
    # Initialize cursor at spectator position or default
    start_tf = spectator.get_transform()
    curr_loc = start_tf.location
    
    # Push cursor forward slightly so it's visible
    fwd = start_tf.get_forward_vector()
    curr_loc.x += fwd.x * 5
    curr_loc.y += fwd.y * 5
    curr_loc.z = 0.5

    move_step = INITIAL_STEP
    
    box_width = 2.5 # Default width
    box_length = args.box_length
    box_rotation_yaw = 0.0

    # Need to calculate geo_loc initially so 'P' works before moving
    geo_loc = carla_map.transform_to_geolocation(curr_loc)

    print("\nStarting Loop. Press ESC to quit.")
    
    running = True
    while running:
        clock.tick(30) # Limit FPS

        # Update geolocation based on current position
        geo_loc = carla_map.transform_to_geolocation(curr_loc)

        # -----------------------------
        # Input Handling
        # -----------------------------
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                return

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False

                # --- Step Size Control ---
                elif event.key == pygame.K_UP:
                    move_step += STEP_INCREMENT
                elif event.key == pygame.K_DOWN:
                    move_step = max(0.1, move_step - STEP_INCREMENT)
                
                # --- Box Width Control ---
                elif args.box and event.key == pygame.K_RIGHT:
                    box_width += STEP_INCREMENT
                elif args.box and event.key == pygame.K_LEFT:
                    box_width = max(0.1, box_width - STEP_INCREMENT)

                # --- Box Rotation Control ---
                elif args.box and event.key == pygame.K_RIGHTBRACKET:
                    box_rotation_yaw = (box_rotation_yaw + ROTATION_INCREMENT) % 360
                elif args.box and event.key == pygame.K_LEFTBRACKET:
                    box_rotation_yaw = (box_rotation_yaw - ROTATION_INCREMENT) % 360

                # --- Movement Control ---
                elif event.key == pygame.K_w: # North (-Y)
                    curr_loc.y -= move_step
                elif event.key == pygame.K_s: # South (+Y)
                    curr_loc.y += move_step
                elif event.key == pygame.K_a: # West (-X)
                    curr_loc.x -= move_step
                elif event.key == pygame.K_d: # East (+X)
                    curr_loc.x += move_step
                elif event.key == pygame.K_e: # Up (+Z)
                    curr_loc.z += move_step
                elif event.key == pygame.K_q: # Down (-Z)
                    curr_loc.z -= move_step

                # --- Camera Control (Manual) ---
                elif event.key == pygame.K_c:
                    # Move camera to point, Top Down (Pitch -90), Facing North (Yaw 0)
                    cam_loc = carla.Location(curr_loc.x, curr_loc.y, curr_loc.z + 50.0)
                    cam_rot = carla.Rotation(pitch=-90, yaw=0, roll=0)
                    spectator.set_transform(carla.Transform(cam_loc, cam_rot))

                # --- Print Coordinates (New) ---
                elif event.key == pygame.K_p:
                    print(f"\n--- Location Snapshot ---")
                    print(f"CARLA (XYZ): {curr_loc.x:.4f}, {curr_loc.y:.4f}, {curr_loc.z:.4f}")
                    print(f"GEO (Lat/Lon/Alt): {geo_loc.latitude:.8f}, {geo_loc.longitude:.8f}, {geo_loc.altitude:.4f}")
                    if args.box:
                        print(f"Box Length: {box_length:.2f} m, Width: {box_width:.2f} m")
                        print(f"Box Rotation (Yaw): {box_rotation_yaw:.2f} degrees")
                        
                        # Calculate 4 corners (2D)
                        # Order: Front-Left, Front-Right, Back-Right, Back-Left (Clockwise)
                        half_l = box_length / 2.0
                        half_w = box_width / 2.0
                        corners_local = [
                            (half_l, -half_w),  # Front-Left
                            (half_l, half_w),   # Front-Right
                            (-half_l, half_w),  # Back-Right
                            (-half_l, -half_w)  # Back-Left
                        ]
                        yaw_rad = math.radians(box_rotation_yaw)
                        cos_yaw = math.cos(yaw_rad)
                        sin_yaw = math.sin(yaw_rad)
                        
                        print("Box Vertices (Clockwise): [")
                        for dx, dy in corners_local:
                            vx = curr_loc.x + (dx * cos_yaw - dy * sin_yaw)
                            vy = curr_loc.y + (dx * sin_yaw + dy * cos_yaw)
                            print(f"    carla.Location(x={vx:.2f}, y={vy:.2f}, z={curr_loc.z:.2f}),")
                        print("]")
                    print(f"-------------------------")

        # -----------------------------
        # Visuals
        # -----------------------------
        # Draw axes at the current point
        if args.box:
            # Draw 2D rectangle (Length along X, Width along Y)
            extent = carla.Vector3D(box_length / 2.0, box_width / 2.0, 0.0)
            box_rotation = carla.Rotation(yaw=box_rotation_yaw)
            world.debug.draw_box(carla.BoundingBox(curr_loc, extent), box_rotation, thickness=0.1, color=carla.Color(255,0,0), life_time=0.1)
        else:
            draw_world_axes(world, curr_loc, length=2.0, thickness=0.08, arrow_size=0.15)
        
        # -----------------------------
        # HUD / Data Display
        # -----------------------------
        
        screen.fill((20, 20, 20)) # Dark gray background

        info_text = [
            f"CONTROLS",
            f"  Move X/Y : WASD",
            f"  Move Z   : Q (Down) / E (Up)",
            f"  Camera   : 'C' (Snap Top-Down)",
            f"  Print    : 'P' (to terminal)",
            f"  Box Width: LEFT / RIGHT" if args.box else "",
            f"  Box Rotate: [ / ]" if args.box else "",
            f"  Step Size: UP / DOWN arrows",
            f"",
            f"SETTINGS",
            f"  Step Dist: {move_step:.2f} meters",
            f"",
            f"LOCATION (CARLA)",
            f"  X: {curr_loc.x:.2f}",
            f"  Y: {curr_loc.y:.2f}",
            f"  Z: {curr_loc.z:.2f}",
            f"",
            f"LOCATION (GEO)",
            f"  Lat: {geo_loc.latitude:.8f}",
            f"  Lon: {geo_loc.longitude:.8f}",
            f"  Alt: {geo_loc.altitude:.2f} m",
        ]
        
        if args.box:
            info_text.extend([
                f"",
                f"BOX DIMENSIONS",
                f"  Length: {box_length:.2f} m",
                f"  Width : {box_width:.2f} m",
                f"  Yaw   : {box_rotation_yaw:.2f} deg"
            ])

        y_pos = 20
        for line in info_text:
            if "CONTROLS" in line or "LOCATION" in line or "SETTINGS" in line:
                color = (255, 255, 0)
            else:
                color = (0, 255, 0)
            
            surface = font.render(line, True, color)
            screen.blit(surface, (20, y_pos))
            y_pos += 25

        pygame.display.flip()

    pygame.quit()

if __name__ == '__main__':
    argparser = argparse.ArgumentParser(description=__doc__)
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
        '-f', '--file',
        metavar='f',
        type=str,
        help='Import file to read crossing data') 
    argparser.add_argument(
        '--box', action='store_true', help='Draw a box instead of a point')
    argparser.add_argument(
        '--box_length', type=float, default=2.0, help='Length of the box (X-axis)')
    
    args = argparser.parse_args()
    
    try:
        main(args)
    except KeyboardInterrupt:
        print('\nCancelled by user. Bye!')