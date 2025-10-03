"""
    json_transmitter.py

    Template script demonstrating how to send and receive object SDOs in JSON format using threading for concurrent operations.
    This script is intended to serve as a starting point for distributed-testing event participants utilizing the JSON Tools applications
    to send and receive object SDOs.

    Configuration:
    - The script includes several global variables that can be customized to suit the user's environment and needs.
    
    Helper functions:
    - waypoint(): Reads a CSV file of breadcrumbs and creates a list of dictionary objects (waypoints) for determining location.
    - get_object_data_from_waypoints():
    - get_object_data_from_api():
    - wait_for_port():
    - transmit_object_json():

    Main threaded functions:
    - transmit_main(): Runs in a thread to continuously:
        1. Retrieve object data (via waypoints or API, depending on configuration)
        2. Package the data into SDOs in JSON format using json_templates
        3. Transmit the SDOs via REST API to the JSON Publisher
    - receive_main(): Runs in a thread to:
        1. Open a socket and bind to a specified host and port
        2. List for incoming SDOs from the JSON Streamer
        3. Print incoming SDOs to the console (From this point the user would modify this section to get the data into their application)

    Main features:
    - Supports multiple coordinate formats (e.g., geocentric, ltpENU)
    - Supports multiploe object types (e.g., LandVehicle, TrafficSignalController)
    - Concurrent transmission and reception using threading.
    - Configurable data source (Waypoints or API)

    Usage:
    - Configure global variables at the start of the script to match your enviornment
    - Customize or extend the helper functions to get object data to/from your application in the format expected by the script and templates.
    - Run the script using "python3 ~/distributed-testing/scripts/json_scripts/json_transmitter.py". Two threads will start:
        1. One for transmittion object SDOs to the JSON Publisher
        2. One for receiving object SDOs from the JSON Streamer
"""

import copy
import csv
import time
import math
import requests
import ast
import socket
import threading
import fake_api
import json_templates

# =================================
# Global configuration
# =================================
SELECTED_WAYPOINT_CSV = "Town04_breadcrumbs.csv" # CSV file containing breadcrumb/waypoint data
# TODO: Have these update based on the object being transmitted, support for transmitting both vehicles and traffic signal controllers
OBJECT_TYPE = 'VUG-LandVehicle-v1.1.0' # options are "VUG-LandVehicle-v1.1.0"
ENTITY_TYPE = 'VUG::Entities::LandVehicle'

GET_OBJECT_TYPE = "api"  # options are "waypoints" or "api"
COORDINATE_FORMAT = "ltpENU" # options are "geocentric" or "ltpENU"
PUBLISHER_IP = "127.0.0.1:8004" #IP for TENA Publisher connection
SOURCE_ID = "03:05" # TODO: Add description for what source_id is
VEHICLE_ROLENAME = "JSON-M-1" # Name of your vehicle following breadcrumbs, this should match "$VUG_MANUAL_VEHICLE_ID" in your_site.config file
VEHICLE_LIST = ["JSON-M-1","JSON-M-2","JSON-M-3","JSON-M-4","JSON-M-5"] # List of vehicles you will be providing updates for from the API
TRAFFICSIGNALCONTROLLER_LIST = [] # List of traffic signal controllers you will be providing updates for from the API

# =================================
# Helper functions
# =================================

def waypoint(waypoint_list):
    """
        Parses a CSV file containing breadcrumb/waypoint data and returns a list of waypoints.

        Parameters
        ----------
        waypoint_list : str
            Path to the CSV file containing breadcrumb/waypoint data.

        Returns
        -------
        list of dict
            List of waypoints, each represented as a dictionary

        Notes
        -----
        Dictionary values should be modified to match the headers in your CSV file
    """
    # Opens the passed in 'waypoint_list' CSV file
    with open(waypoint_list, mode='r', encoding='utf-8') as file:
        csv_reader = csv.DictReader(file)
        # Returns a list of dictionaries, where each row in 'waypoint_list' is an entry in the returned list
        return [
            {
                'total_distance_traveled': float(row['total_distance_traveled']),
                'x': float(row['x']),
                'y': float(row['y']),
                'z': float(row['z']),
                'vx': float(row['vx']),
                'vy': float(row['vy']),
                'vz': float(row['vz']),
                'yaw': float(row['yaw']),
                'pitch': float(row['pitch']),
                'roll': float(row['roll'])
            }
            for row in csv_reader
        ]

def get_object_data_from_waypoints(waypoint_data):
    """
        Generate object data based on waypoints and a system control algorithm

        This function takes a list of waypoint dictionaries (from waypoint()) and utilizes some custom progression algorithm
        to determine the object's current state. The algorithm should compute the total distance traveled by the object and then
        the function uses that to determine the object's location with respect to the provided waypoints.

        Users MUST modify this function to fit their simulation or real-world system.
        For example:
        - Use the nearest waypoint already passed (default example implementation)
        - Interpolate between waypoints for smoother motion
        - Apply a custom motion model for velocity/acceleration updates

        Parameters
        ----------
        waypoint_data : list of dict
            Waypoint data, typically loaded from a CSV file

        Returns
        -------
        list of dict
            A list with an object dictionary representing the current state of that object
            The dictionary keys should be those expected by the field mappings in json_templates.py

        Notes
        -----
        - The default implementation uses a simple distance accumulator to determine the total distance traveled
        - The default implementation rounds down to the nearest waypoint and sends that as the object's current location
    """

    # Determine current object state using the user's custom vehicle algorithm - this can include current location, speed, acceleration, update period (etc.).
    # User must determine and retrieve the total distance traveled by the object to determine where along the waypoints their object currently resides

    #----- Our Example Implementation -----
    total_distance = fake_api.vehicle_algorithm()
    #print("Total distance traveled: " + str(total_distance))

    # Once you find the distance traveled, you need to move that distance along the path created by the waypoints.
    # This will likely land you inbetween two waypoints.
    # Use this new_linear_distance to figure out which waypoints you fall between
    # Use the logic you decided on in the previous step to select/generate waypoint data for your new location


    #----- Our Example Implementation -----
    last_waypoint = waypoint_data[0]
    # to keep our place on the waypoints, we want to remove all waypoints before and including the selected waypoint
    while waypoint_data and total_distance > waypoint_data[0]['total_distance_traveled']:
        last_waypoint = waypoint_data.pop(0)
    # Because we remove the last waypoint before our current location, make sure to re-add it.
    #   otherwise element [0] will always be the next waypoint
    waypoint_data.insert(0, last_waypoint)


    # Pack object data into a dictionary, which will eventually be packed into a JSON
    # Dictionary keys should match those for the appropriate field_mapping object in json_templates.py
    # Not all fields are required, the json_templates will use default values for missing fields.
    # Role_name, (x,y,z) location, and (yaw,pitch,roll) orientation are minimum

    #----- Our Example Implementation -----
    object_data = last_waypoint
    object_data["role_name"] = VEHICLE_ROLENAME
    object_data["object_type"] = "LandVehicle"
    # print("Last waypoint passed: " + str(object_data))
    return [object_data]

def get_object_data_from_api(vehicle_list, trafficSignalController_list):
    """
        Generate object data using information pulled from your application's API

        This function will retrieve object data from your specific API. 
        This must include the object's role_name, (x,y,z) location, and (yaw,pitch,roll) orientation at a minimum.

        Users MUST modify this function to fit their API.

        Parameters
        ----------
        vehicle_list : list of str
            List of vehicle role_names the user is getting object data for
        trafficSignalController_list : list of str
            List of trafficSignalController role_names the user is getting object data for

        Returns
        -------
        object_data_list : list of dict
            A list with object dictionaries representing the current state of each object
            The dictionary keys should be those expected by the field mappings in json_templates.py

        Notes
        -----
        - The default implementation uses 'fake_api.py' to get a list of dictionaries containing vehicle information.
        - The default implementation performs some modification to ensure object data matches what is expected by the 
            field mappings in json_templates.py (e.g., re-naming dictionary keys with <object>.pop("<old_keyName>"), converting degrees to radians, etc.)
    """

    # Final list of objects to be returned
    object_data_list = []

    # Retrieve vehicle object data via API - ensure to get all required fields
    api_vehicle_data = fake_api.get_vehicles()
    
    # Modify vehicle object data to match the format expected by json_templates
    for vehicle in api_vehicle_data:
        if vehicle["vehicle_name"] in vehicle_list:
            vehicle["role_name"] = vehicle.pop("vehicle_name")
            vehicle["x"] = vehicle.pop("xPosition")
            vehicle["y"] = vehicle.pop("yPosition")
            vehicle["z"] = vehicle.pop("zPosition")
            vehicle["yaw"] = math.radians(vehicle.pop("yawDeg"))
            vehicle["pitch"] = math.radians(vehicle.pop("pitchDeg"))
            vehicle["roll"] = math.radians(vehicle.pop("rollDeg")) + math.pi
            vehicle["object_type"] = "LandVehicle"
            object_data_list.append(vehicle)
            # print(str(vehicle["role_name"]) + " current location: " + str(vehicle))

    # Retrieve traffic signal controller object data via API - ensure to get all required fields
    api_tsc_data = fake_api.get_trafficSignalControllers()

    # Modify traffic signal controller data to match the format expected by json_templates
    for tsc in api_tsc_data: 
        if tsc.id in trafficSignalController_list:
            tsc["object_type"] = "TrafficSignalController"
            object_data_list.append(tsc)

    return object_data_list

def wait_for_port(host, port, timeout=30):
    """
        Wait for a TCP port on a host to become available.

        This function repeatedly attempts to create a socket connection to the specified 
            host and port until it succeeds or the timeout is reached.
        It is used to wait for the REST API to come online before proceeding

        Parameters
        ----------
        host : str
            Hostname or IP address of the REST API
        port : int
            TCP port number to check
        timeout : int, optional
            Maximum time in seconds to wait before giving up (default is 30).

        Returns
        -------
        bool
            True if the connection was successful within the timeout period
            False if the timeout expired without success

        Notes
        -----
        - Uses a 2-second socket timeout for each connection attempt
        - Retries once per second until the total timeout is reached
    """
    # Gets the time that connection attempts begin
    start = time.time()
    # Determines if the timeout has been reached
    while time.time() - start < timeout:
        # Attempts to create a connection at the specified host:port
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except OSError:
            time.sleep(1)
    return False

def transmit_object_json(object_json_list, EntityMap):
    """
        Transmit object SDOs to the Publisher REST API.

        For each object SDO in the list:
        - If the object has not been seen before (not in 'EntityMap'), a POST request
            is made to create it on the publisher. The returned 'sdo_index' is used to 
            construct the unique object URL, which is stored in 'EntityMap'
        - If the object already exists (in 'EntityMap'), a PUT request is made to update
            it at its previously assigned URL

        A connection check ('wait_for_port') ensures the publisher service is available
            before any requests are sent

        Parameters
        ----------
        object_json_list : list of dict
            A list of JSON-compatible dictionaries representing object SDOs to transmit
        EntityMap : dict
            A dictionary mapping entity names to their publisher URLs
            Updated in-place as new entities are created

        Returns
        -------
        None

    """

    # Connection check to ensure REST API is available
    if not wait_for_port("127.0.0.1", 8004):
        # print("Server never came up")
        return
    else:
        time.sleep(1)
    

    for object_json in object_json_list:
        # Pulls the EntityName from the object
        EntityName = object_json["attributes"]["identifier"]
        tena_publisher_url = f"http://{PUBLISHER_IP}/v1/objects/{OBJECT_TYPE}/{ENTITY_TYPE}" # TODO: Adjust script to support for transmitting both vehicles and traffic signal controllers
        print('Sending '+str(EntityName)+' JSON:\n'+str(object_json))
        print()
        # Determines whether a new object (PUSH) request is being sent or update to existing object (PUT)
        if EntityName not in EntityMap.keys():
            initial_response = requests.post(tena_publisher_url, json=object_json)
            sdo_index = (ast.literal_eval(initial_response.text)).get("sdo_index")
            tena_publisher_url += "/" + str(sdo_index)
            EntityMap[EntityName] = tena_publisher_url
        else:
            update_response = requests.put(EntityMap[EntityName], json=object_json)

        # this will send to a speficied REST endpoint
    return

def transmit_main():
    """
        Main loop for transmitting object SDOs to the JSON Publisher

        This function continuously retrieves object data (either from waypoints or from an API, depending on configuration),
        converts it into JSON messages using the appropriate template, and transmits those SDOs to the Publisher REST API.
        It maintains an internal mapping ('EntityMap') of object IDs to publisher entity URLs so that new objects are 
        created with POST and existing objects are updated with PUT.

        Globals Used
        ------------
        These are set in the "Global configuration" section at the beginning of this script
        GET_OBJECT_TYPE : str
            Source of object data. Must be "waypoints" or "api"
        SELECTED_WAYPOINT_CSV : str
            Path to the CSV file containing waypoint data
        VEHICLE_LIST : list of str
            List of vehicles to pull object data from the API
        TRAFFICSIGNALCONTROLLER_LIST : list of str
            List of traffic signal controllers to pull object data from the API
        COORDINATE_FORMAT : str
            Coordinate system used for packaging object SDOs. Must be "geocentric" or "ltpENU"
        SOURCE_ID : str
            Identifier for the site and application ID sending the object SDOs

        Notes
        -----
        - Runs indefinitely until the script is terminated
    """

    # Hashmap of vehicle ID to entity ID and publisher URL
    EntityMap = {}

    # Period for retrieval of data (in seconds)
    data_update_period = 1

    # Set how object data will be retrieved, waypoints or api
    if GET_OBJECT_TYPE == "waypoints":
        object_json_list = waypoint(SELECTED_WAYPOINT_CSV)
        selectMethod = get_object_data_from_waypoints
        args = (object_json_list,) # always just one vehicle when using waypoints
    elif GET_OBJECT_TYPE == "api":
        selectMethod = get_object_data_from_api
        args = (VEHICLE_LIST,TRAFFICSIGNALCONTROLLER_LIST) # can be multiple vehicles and traffic signals when using API
    else:
        # print("Invalid getObjectDataType, must be 'waypoints' or 'api'")
        return

    while True: 

        ##### Step 1: Get object data
        # This can be from either
        #   - an application API or 
        #   - a list of waypoints
        object_data_list = selectMethod(*args)

        ##### Step 2: pack data into JSON
        object_json_list = json_templates.pack_object_data_into_json(object_data_list, COORDINATE_FORMAT, SOURCE_ID)
        
        ##### Step 3: transmit the JSON 
        transmit_object_json(object_json_list, EntityMap)

        ##### Step 4: wait for update period and repeat
        time.sleep(data_update_period)

def receive_main():
    """
        Start a TCP server to receive object SDOs in JSON format

        This function creates a TCP socket, binds it to a configurable host and port, and listens for incoming connections.
        When a client connects, it receives up to 1024 bytes of data, decodes it as UTF-8, and prints it to the console.

        Notes
        -----
        - Runs indefinitely until the script is terminated
        - Prints received data directly to the console
        - Assumes incoming data is UTF-8 encoded text.
        - It is up to the user to implement further processing of the received SDOs
    """

    # open a TCP socket at a configurable IP and port
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Define host and port
    HOST = '127.0.0.1'  # Listen on localhost
    PORT = 8004  # Choose an unused port

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    sock.bind((HOST, PORT))
    print(f"Server listening on {HOST}:{PORT} for UDP data...")

    # Listen for incoming connections (max 5 queued connections)
    print(f"Server listening on {HOST}:{PORT}")

    try:
        while True:
            # Accept a client connection
            client_socket, client_address = server_socket.accept()
            print(f"Connected to client: {client_address}")

            # Receive data (up to 1024 bytes)
            data = client_socket.recv(1024).decode('utf-8')  # Assuming text data
            print(f"Connected to client: {client_address}")
            if not data:
                print("No data received, closing connection")
                client_socket.close()
                continue

            print(f"Received data: {data}")


    except KeyboardInterrupt:
        print("Shutting down server")
    finally:
        server_socket.close()

    ### INSERT YOUR CUSTOM PROCESSING CODE HERE ###

def main():
    """
        Start the transmit and receive threads.

        This function creates and starts two threads:
        - One to handle receiving SDOs in JSON format from the JSON Streamer
        - One to handle sending SDOs in JSON format via REST API to the JSON Publisher

        Both threads are started and run concurrently. This function does not return until the script is terminated.
    """

    # Link the receive_thread to run the code in the receive_main() function
    #receive_thread = threading.Thread(target=receive_main)

    # Link the send_thread to run the code in the transmit_main() function
    send_thread = threading.Thread(target=transmit_main)

    # Start both threads
    #receive_thread.start()
    send_thread.start()


# Run the main function only if this script is executed directly
if __name__ == "__main__":
    main()
