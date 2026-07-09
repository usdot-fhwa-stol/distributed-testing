import os
import sys
import re
import argparse
import json
import math
import socket
import J2735_201603_2023_06_22 as J2735
import binascii as ba
import pyproj

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
argparser.add_argument(
    '-f', '--file',
    metavar='f',
    type=str,
    help='Import file to read crossing data')
args = argparser.parse_args()


def decode_j2735(input_hex):
    print(f'input_hex:  {input_hex}')
    try:
        #specify message type inside J2735.py
        decoded_msg = J2735.DSRC.MessageFrame
        # print(f'decoded_msg:  {decoded_msg}')
        # convert from hex using unhexlify then from uper using library
        decoded_msg.from_uper(ba.unhexlify(input_hex))
        
        #format data into json
        decoded_msg_json = json.loads(decoded_msg.to_json())

        # print('')
        # print(decoded_msg_json)

        return decoded_msg_json
    except Exception as err:
        print(f"Unexpected {err=}, {type(err)=}")
        return "ERROR"
    


def lat_lon_alt_to_xyz(latitude, longitude, altitude):
    # Earth radius in meters (average value)
    earth_radius = 6371000.0

    # Convert latitude and longitude from degrees to radians
    lat_rad = math.radians(latitude)
    lon_rad = math.radians(longitude)

    # Calculate Cartesian coordinates
    x = (earth_radius + altitude) * math.cos(lat_rad) * math.cos(lon_rad)
    y = (earth_radius + altitude) * math.cos(lat_rad) * math.sin(lon_rad)
    z = (earth_radius + altitude) * math.sin(lat_rad)

    return { "x":x, "y": y, "z": z }

def lat_long_to_xyz_better(latitude, longitude, altitude):
    # WGS 84 parameters
    semi_major_axis = 6378137.0  # in meters
    flattening = 1 / 298.257223563

    # Convert latitude and longitude from degrees to radians
    lat_rad = latitude * (3.141592653589793 / 180.0)
    lon_rad = longitude * (3.141592653589793 / 180.0)

    # Calculate the radius of curvature in the prime vertical
    N = semi_major_axis / math.sqrt(1 - flattening * (2 - flattening) * math.sin(lat_rad)**2)

    # Calculate Cartesian coordinates
    x = (N + altitude) * math.cos(lat_rad) * math.cos(lon_rad)
    y = (N + altitude) * math.cos(lat_rad) * math.sin(lon_rad)
    z = ((1 - flattening)**2 * N + altitude) * math.sin(lat_rad)

    return { "x":x, "y": y, "z": z }

def GeodeticToEcef( latitude, longitude,altitude):
        # WGS-84 geodetic constants
        a = 6378137.0        # WGS-84 Earth semimajor axis (m)

        b = 6356752.314245;     # Derived Earth semiminor axis (m)
        f = (a - b) / a          # Ellipsoid Flatness
        f_inv = 1.0 / f      # Inverse flattening
        a_sq = a * a
        b_sq = b * b
        e_sq = f * (2 - f)    # Square of Eccentricity

        # Convert to radians in notation consistent with the paper:
        lambdaa = latitude * (3.141592653589793 / 180.0)
        phi = longitude * (3.141592653589793 / 180.0)
        s = math.sin(lambdaa)
        N = a / math.sqrt(1 - e_sq * s * s)

        sin_lambda = math.sin(lambdaa)
        cos_lambda = math.cos(lambdaa)
        cos_phi = math.cos(phi)
        sin_phi = math.sin(phi)

        x = (altitude + N) * cos_lambda * cos_phi
        y = (altitude + N) * cos_lambda * sin_phi
        z = (altitude + (1 - e_sq) * N) * sin_lambda

        return { "x":x, "y": y, "z": z }

def convert_lat_long_to_universal(lat, lon, alt=0):
    print(f'\nlat: {lat}, long: {lon}, elev: {alt}')

    # Define the WGS84 coordinate system
    wgs84 = pyproj.CRS('EPSG:4326')
    # Define the custom coordinate system using the provided parameters
    tcm_proj = pyproj.CRS('EPSG:3785')
    
    # Create a transformer object
    transformer = pyproj.Transformer.from_crs(wgs84, tcm_proj)

    # Perform the transformation
    tcm_refpoint_x, tcm_refpoint_y, tcm_refpoint_z   = transformer.transform(lat, lon, alt)

    print(f"tcm_refpoint_x {tcm_refpoint_x}, tcm_refpoint_y { tcm_refpoint_y}, tcm_refpoint_z {tcm_refpoint_z}")

    return { "x":tcm_refpoint_x, "y": tcm_refpoint_y, "z": tcm_refpoint_z }

def convert_universal_to_carla(x_u, y_u, z_u=0):

    tcm_proj = pyproj.CRS('EPSG:3785')

    custom_crs = pyproj.CRS.from_proj4(
        '+proj=tmerc +lat_0=38.9511644208721 +lon_0=-77.14905380821106 +k=1 '
        '+x_0=0 +y_0=0 +datum=WGS84 +units=m +vunits=m +no_defs'
    )
    

    # Create a transformer object
    tcm_to_carla_transformer = pyproj.Transformer.from_crs(tcm_proj, custom_crs)

    # Perform the transformation
    tcm_to_carla_refpoint_x, tcm_to_carla_refpoint_y, tcm_to_carla_refpoint_z, = tcm_to_carla_transformer.transform(x_u, y_u, z_u)
    
    
    return { "x":tcm_to_carla_refpoint_x, "y": -1*tcm_to_carla_refpoint_y, "z": tcm_to_carla_refpoint_z }

def calculate_bearing(x1, y1, x2, y2):
    """
    Calculate the bearing between two points (x1, y1) and (x2, y2).
    
    Parameters:
    x1, y1 -- coordinates of the first point
    x2, y2 -- coordinates of the second point
    
    Returns:
    Bearing in degrees from the first point to the second point
    """
    delta_x = x2 - x1
    delta_y = y2 - y1
    
    angle_rad = math.atan2(delta_y, delta_x)
    angle_deg = math.degrees(angle_rad)
    
    # Normalize the angle to be between 0 and 360 degrees
    bearing = (angle_deg + 360) % 360
    
    return bearing

def calculate_midpoint(x1, y1, z1, x2, y2, z2):
    """
    Calculate the midpoint between two points (x1, y1) and (x2, y2).
    
    Parameters:
    x1, y1 -- coordinates of the first point
    x2, y2 -- coordinates of the second point
    
    Returns:
    Midpoint between the first point to the second point
    """
    sum_x = x2 + x1
    sum_y = y2 + y1
    sum_z = z2 + z1
    
    midpoint_x = sum_x/2
    midpoint_y = sum_y/2
    midpoint_z = sum_z/2
    
    return { "x": midpoint_x, "y": midpoint_y, "z": midpoint_z }

def draw_tcm(tcm_json):

    # content of message is a couple levels deep
    msg_content = tcm_json["value"]["body"]["tcmV01"]
    print("Content " + str(msg_content))
    
    # get the ref lat and long which determine the starting point of the TCM definition
    ref_lat = msg_content["geometry"]["reflat"] / (10 ** 7)
    ref_long = msg_content["geometry"]["reflon"] / (10 ** 7)

    # convert the ref lat long from WGS84 to xyz coordinate system of TCM (EPSG:3785)
    msg_ref_pos = convert_lat_long_to_universal(ref_lat,ref_long,0)
    print(f'\nmsg_ref_pos: {msg_ref_pos}')
    
    # convert thie reference position from global XYZ to TFHRC CARLA 0,0,0 reference
    msg_ref_pos_carla = convert_universal_to_carla(msg_ref_pos["x"],msg_ref_pos["y"], msg_ref_pos["z"])
    print(f'\nmsg_ref_pos_carla: {msg_ref_pos_carla}')

    # draw the reference point for.....reference
    # world.debug.draw_string(
    #     carla.Location(x=msg_ref_pos_carla["x"], y=msg_ref_pos_carla["y"], z=draw_z_height), 
    #     "[R]", 
    #     draw_shadow=False,
    #     color=carla.Color(r=255, g=0, b=0), life_time=draw_lifetime,
    #     persistent_lines=True)

    # loop through the TCM nodes and 
    tcm_nodes = []

    for tcm_node in msg_content["geometry"]["nodes"]:
        
        node_universal = {
            "x": msg_ref_pos["x"] + tcm_node["x"]/100,
            "y": msg_ref_pos["y"] + tcm_node["y"]/100,
            "z": msg_ref_pos["z"],
        }

        node_carla = convert_universal_to_carla(node_universal["x"],node_universal["y"], node_universal["z"])

    
        tcm_nodes.append(node_carla)
        print(f'node_carla: {node_carla}')

    # tfhrc_0_0_0_via_carla = {
    #     "lat" : 38.951164,
    #     "long" : -77.149054,
    #     "elev" : 0.000000
    # }

    # tfhrc_0_0_0_global_xyz = convert_lat_long_to_universal(
    #     tfhrc_0_0_0_via_carla["lat"],
    #     tfhrc_0_0_0_via_carla["long"],
    #     tfhrc_0_0_0_via_carla["elev"])
    
    # print(f'\ntfhrc_0_0_0_global_xyz: {tfhrc_0_0_0_global_xyz}')

    
    # tfhrc_0_0_0_global_xyz_carla = convert_universal_to_carla(tfhrc_0_0_0_global_xyz["x"],tfhrc_0_0_0_global_xyz["y"], tfhrc_0_0_0_global_xyz["z"])
    
    # print(f'\tfhrc_0_0_0_global_xyz_carla: {tfhrc_0_0_0_global_xyz_carla}')


    for segment_start,segment_end in zip(tcm_nodes,tcm_nodes[1:]):
        draw_box_from_two_points_and_width(segment_start["x"],segment_start["y"],segment_start["z"],segment_end["x"],segment_end["y"],segment_end["z"],msg_content["geometry"]["refwidth"]/100)
        


def draw_box_from_two_points_and_width(start_point_x,start_point_y,start_point_z,end_point_x,end_point_y,end_point_z,box_width): 
    tcm_segment_bearing = calculate_bearing(start_point_x,start_point_y,end_point_x,end_point_y)

    print(f'tcm_segment_bearing: {tcm_segment_bearing}')

    tcm_segment_midpoint = calculate_midpoint(
        start_point_x,start_point_y,start_point_z,
        end_point_x,end_point_y,end_point_z
        )
    
    print(f'tcm_segment_midpoint: {tcm_segment_midpoint}')
    
    tcm_segment_width = box_width

    print(f'tcm_segment_width: {tcm_segment_width}')

    tcm_segment_length = math.sqrt(
        (start_point_x - end_point_x)**2 + 
        (start_point_y - end_point_y)**2
        )
    
    print(f'tcm_segment_length: {tcm_segment_length}')

    box_center = carla.Location(x=tcm_segment_midpoint["x"], y=tcm_segment_midpoint["y"], z=draw_z_height)

    msg_box = carla.BoundingBox(box_center,carla.Vector3D(tcm_segment_length/2,tcm_segment_width/2,0))

    world.debug.draw_box(
        msg_box, 
        carla.Rotation(0,0,tcm_segment_bearing),
        1,
        # draw_shadow=False,
        color=carla.Color(r=255, g=0, b=0),
        life_time=draw_lifetime,
        persistent_lines=True)


def draw_tcr(tcr_json):

    # content of message is a couple levels deep
    msg_content = tcr_json["value"]["body"]["tcrV01"]
    print("Content " + str(msg_content))
    
    # get the ref lat and long which determine the starting point of the TCR definition
    ref_lat = msg_content["bounds"][0]["reflat"] / (10 ** 7)
    ref_long = msg_content["bounds"][0]["reflon"] / (10 ** 7)

    # convert the ref lat long from WGS84 to xyz coordinate system of TCR (EPSG:3785)
    msg_ref_pos = convert_lat_long_to_universal(ref_lat,ref_long,0)
    print(f'\nmsg_ref_pos: {msg_ref_pos}')
    
    # convert thie reference position from global XYZ to TFHRC CARLA 0,0,0 reference
    msg_ref_pos_carla = convert_universal_to_carla(msg_ref_pos["x"],msg_ref_pos["y"], msg_ref_pos["z"])
    print(f'\nmsg_ref_pos_carla: {msg_ref_pos_carla}')

    # draw the reference point for.....reference
    # world.debug.draw_string(
    #     carla.Location(x=msg_ref_pos_carla["x"], y=msg_ref_pos_carla["y"], z=draw_z_height), 
    #     "[R]", 
    #     draw_shadow=False,
    #     color=carla.Color(r=255, g=0, b=0), life_time=draw_lifetime,
    #     persistent_lines=True)

    # loop through the tcr nodes and 
    tcr_nodes = []

    offsets_including_0_0 = msg_content["bounds"][0]["offsets"]
    offsets_including_0_0.append({"deltax": 0,"deltay": 0})

    for tcr_node in offsets_including_0_0:
        
        node_universal = {
            "x": msg_ref_pos["x"] + tcr_node["deltax"]/7,
            "y": msg_ref_pos["y"] + tcr_node["deltay"]/7,
        }

        node_carla = convert_universal_to_carla(node_universal["x"],node_universal["y"], 0)

    
        tcr_nodes.append(node_carla)
        # print(f'node_carla: {node_carla}')
        # world.debug.draw_string(
        #     carla.Location(x=node_carla["x"], y=node_carla["y"], z=draw_z_height), 
        #     "[O]", 
        #     draw_shadow=False,
        #     color=carla.Color(r=255, g=0, b=0), life_time=draw_lifetime,
        #     persistent_lines=True)

    print(f'tcr_nodes: {tcr_nodes}')

    # we know from definition that the nodes are in clockwise order, therefore node index 2 (prev 1 before we added 0,0) is opposite corner

    

    draw_box_from_opposite_corners(tcr_nodes[0],tcr_nodes[2])

    

def draw_box_from_opposite_corners(zero_corner,opposite_corner):

    box_midpoint = calculate_midpoint(
        zero_corner["x"],zero_corner["y"],0,
        opposite_corner["x"],opposite_corner["y"],0
        )
    
    print(f'box_midpoint: {box_midpoint}')
    
    tcr_segment_width = abs(zero_corner["y"] - opposite_corner["y"])

    print(f'tcr_segment_width: {tcr_segment_width}')

    tcr_segment_length = abs(zero_corner["x"] - opposite_corner["x"])
    
    print(f'tcr_segment_length: {tcr_segment_length}')

    box_center = carla.Location(x=box_midpoint["x"], y=box_midpoint["y"], z=draw_z_height)

    msg_box = carla.BoundingBox(box_center,carla.Vector3D(tcr_segment_length/2,tcr_segment_width/2,0))

    world.debug.draw_box(
        msg_box, 
        carla.Rotation(0,0,0),
        1,
        # draw_shadow=False,
        color=carla.Color(r=255, g=0, b=0),
        life_time=draw_lifetime,
        persistent_lines=True)

try:
    client = carla.Client(args.host, args.port)
    client.set_timeout(5.0)
    world = client.get_world()
    # map = world.get_map()

    draw_z_height = 39
    draw_lifetime = 5

    # mcity_origin = GeodeticToEcef(42.30059341574939,-83.69928318881136,0)

    mcity_origin = { 
                "x": 518508.658, 
                "y": -4696054.02, 
                "z": 0
            }
    
    print("mcity_origin: " + str(mcity_origin))

    receive_ip = "192.168.55.236"
    receive_port = 5397

    sock = socket.socket(   socket.AF_INET, # Internet
                            socket.SOCK_DGRAM) # UDP
    sock.bind((receive_ip, receive_port))

    print("Connected")

    while True:
        data, addr = sock.recvfrom(4096) # buffer size is 1024 bytes
        hex_data = data.hex()
        # print("received message: %s" % hex_data)

        if hex_data.lower().startswith("00f4"):
            print("\nReceived TCR")
            decoded_tcr = decode_j2735(hex_data)
            print(decoded_tcr)
            draw_tcr(decoded_tcr)

        elif hex_data.lower().startswith("00f5"):
            print("\nReceived TCM")
            decoded_tcm = decode_j2735(hex_data)
            print(decoded_tcm)
            draw_tcm(decoded_tcm)

        # elif hex_data.lower().startswith("0014"):
        #     print("\nReceived BSM")
        #     decoded_tcm = decode_j2735(hex_data)
        #     print(decoded_tcm)

finally:
    print('\nDone!')
