import sys
import argparse
import os
import pygame

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

def draw_box(world, corners, thickness=0.1, life_time=0.1):
    """
    Draws lines between 4 corners creating a box
    """
    debug = world.debug

    for i in range (len(corners)):
        start = corners[i]
        end = corners[(i+1)% len(corners)]
        #print(f"Connecting: {start} and {end}")
        debug.draw_line(start, end, life_time=life_time, thickness=thickness, color=carla.Color(0,255,0))

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
    curr_loc.z = max(curr_loc.z, 0.5)

    move_step = INITIAL_STEP

    # Need to calculate geo_loc initially so 'P' works before moving
    geo_loc = carla_map.transform_to_geolocation(curr_loc)

    print("\nStarting Loop. Press ESC to quit.")

    corners = []
    
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
                    if move_step == 0.1:
                        move_step = 0.0
                    move_step += STEP_INCREMENT
                elif event.key == pygame.K_DOWN:
                    move_step = max(0.1, move_step - STEP_INCREMENT)

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
                    # print(f"\n--- Location Snapshot ---")
                    # print(f"CARLA (XYZ): {curr_loc.x:.4f}, {curr_loc.y:.4f}, {curr_loc.z:.4f}")
                    # print(f"GEO (Lat/Lon/Alt): {geo_loc.latitude:.8f}, {geo_loc.longitude:.8f}, {geo_loc.altitude:.4f}")
                    print(f"-------------------------")
                    if len(corners) == 4:
                        print(f"Clearing Corners")
                        corners = []
                        print(f"Corners: {corners}")
                    else:
                        corner = carla.Location(curr_loc.x, curr_loc.y, curr_loc.z)
                        corners.append(corner)
                        print(f"Current Corners: ")
                        print(f"-----------------")
                        for corner in corners:
                            print(f"\tx: {corner.x} y:{corner.y}")

        # -----------------------------
        # Visuals
        # -----------------------------
        # Draw axes at the current point
        draw_world_axes(world, curr_loc, length=2.0, thickness=0.08, arrow_size=0.15)
        draw_box(world,corners)
        
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
            f"  Alt: {geo_loc.altitude:.2f} m"
        ]

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
    
    args = argparser.parse_args()
    
    try:
        main(args)
    except KeyboardInterrupt:
        print('\nCancelled by user. Bye!')