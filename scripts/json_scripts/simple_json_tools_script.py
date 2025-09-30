# JSON Tools Script Template
# 
# This will be a starting point and the most basic example of a script which will send/receive JSON to/from the JSON Tools application. 

import copy
import csv
import time
import fake_api
import requests
import ast
import socket
import threading
import json

#If you are using waypoints, this is the CSV file containing the waypoint data
SELECTED_WAYPOINT_CSV = "Town04_breadcrumbs.csv"
OBJECT_TYPE = 'VUG-LandVehicle-v1.1.1'
ENTITY_TYPE = 'VUG::Entities::LandVehicle'
GET_OBJECT_TYPE = "waypoints"  # options are "waypoints" or "api"
PUBLISHER_IP = "127.0.0.1:8004" #IP for TENA Publisher connection
source_id = "03:05"

# this template needs to be updated for land vehicle (currently entity)
# andrew to provide
landVehicle_json_template =  {
    "metadata": {
        "type": "sdo",
        "tdl_file":"VUG-LandVehicle-v1.1.0",
        "type_name":"VUG::Entities::LandVehicle",
        "type_id":"0x409db0a9",
        "event_type":"",
        "state_version":1,
        "is_removed":False,
        "time_of_commit":"",
        "time_of_receipt":""
    },
    "attributes": {
        "identifier": "Unset",
        "designation": "Unset",
        "sourceIdentifier": source_id,
        "tspi": {
            "attributes": {
                "time": {
                    "attributes": {
                        "nanosecondsSince1970": time.time_ns()
                    }
                },
                "position": {
                    "attributes": {
                        "ltpENU_asTransmitted": {
                            "attributes": {
                                "srf": {
                                    "attributes": {
                                        "rtCode": "TENA::RTCODE_WGS_1984_IDENTITY",
                                        "latitudeInDegrees": 0.0, 
                                        "longitudeInDegrees": 0.0, 
                                        "heightAboveEllipsoidInMeters": 0.0,
                                        "azimuthInRadians": 0.0,
                                        "xFalseOriginInMeters": 0.0,
                                        "yFalseOriginInMeters": 0.0
                                    }
                                }, 
                                "xInMeters": 0.0,
                                "yInMeters": 0.0,
                                "zInMeters": 0.0
                            }
                        }
                    }
                },
                "velocity": {
                    "attributes": {
                        "ltpENU_asTransmitted": {
                            "srf": {
                                "attributes": {
                                    "rtCode": "TENA::RTCODE_WGS_1984_IDENTITY",
                                    "latitudeInDegrees": 0.0,
                                    "longitudeInDegrees": 0.0,
                                    "heightAboveEllipsoidInMeters": 0.0,
                                    "azimuthInRadians": 0.0,
                                    "xFalseOriginInMeters": 0.0,
                                    "yFalseOriginInMeters": 0.0
                                }
                            },
                            "vxInMetersPerSecond": 0.0,
                            "vyInMetersPerSecond": 0.0,
                            "vzInMetersPerSecond": 0.0
                        }
                    }
                },
                "orientation": {
                    "attributes": {
                        "frdWRTltpENUbodyFixedZYX_asTransmitted": {
                            "attributes": {
                                "srf": {
                                    "attributes": {
                                        "rtCode": "TENA::RTCODE_WGS_1984_IDENTITY", 
                                        "latitudeInDegrees": 0.0, 
                                        "longitudeInDegrees": 0.0, 
                                        "heightAboveEllipsoidInMeters": 0.0, 
                                        "azimuthInRadians": 0.0, 
                                        "xFalseOriginInMeters": 0.0, 
                                        "yFalseOriginInMeters": 0.0
                                    }
                                }, 
                                "rotZinRadians": 0.0, 
                                "rotYinRadians": 0.0, 
                                "rotXinRadians": 0.0
                            }
                        }
                    }
                }
            }
        },
        "entityID": {
            "attributes": {
                "siteID": int(source_id.split(':')[0]), 
                "applicationID": int(source_id.split(':')[1]), 
                "objectID": 0
            }
        },
        "lvcIndicator": "TENA::LVC::LVCindicator_Virtual",
        "entityType": {
            "attributes": {
                "kind": 0, 
                "domain": 0, 
                "country": 81, 
                "category": 0, 
                "subcategory": 0, 
                "specific": 0, 
                "extra": 0
            }
        },
        "affiliation": "TENA::LVC::Affiliation_Friendly",
        "damageState": "TENA::LVC::DamageState_NoDamage",
        "deadReckoningAlgorithm": "TENA::LVC::DeadReckoningAlgorithm_RVW",
        "landVehicleData" : {
            "attributes" : {
                "exteriorLights" : {
                    "attributes" : {
                        "HeadlightsOn" : False, 
                        "leftTurnSignalOn" : False, 
                        "rightTurnSignalOn" : False, 
                        "hazardSignalOn" : False, 
                        "brakeLightsOn" : False, 
                        "parkingLightsOn" : False, 
                        "specialLightsOn" : False
                    }
                }
            }
        }
    }
}

# this template needs to be updated for traffic signal controller (currently entity)
# andrew to provide
trafficSignalController_json_template =  {
    "attributes": {
        "identifier": "Unset",
        "designation": "Unset",
        "sourceIdentifier": source_id,
        "tspi": {"attributes": {
                "time": {"attributes": {"nanosecondsSince1970": time.time_ns()}},
                "position": {"attributes": {"geodetic_asTransmitted": {"attributes": {"srf": {"attributes": {"rtCode": "TENA::RTCODE_WGS_1984_IDENTITY"}}, "latitudeInDegrees": 0.0, "longitudeInDegrees": 0.0, "heightAboveEllipsoidInMeters": 0.0}}}},
                "orientation": {"attributes": {"frdWRTltpENUbodyFixedZYX_asTransmitted": {"attributes": {"srf": {"attributes": {"rtCode": "TENA::RTCODE_WGS_1984_IDENTITY", "latitudeInDegrees": 0.0, "longitudeInDegrees": 0.0, "heightAboveEllipsoidInMeters": 0.0, "azimuthInRadians": 0.0, "xFalseOriginInMeters": 0.0, "yFalseOriginInMeters": 0.0}}, "rotZinRadians": 0.0, "rotYinRadians": 0.0, "rotXinRadians": 0.0}}}}}},
        "entityID": {"attributes": {"siteID": int(source_id.split(':')[0]), "applicationID": int(source_id.split(':')[1]), "objectID": None}},
        "lvcIndicator": "TENA::LVC::LVCindicator_Virtual",
        ###TODO need to figuire out this entity type from siso standard: https://www.sisostandards.org/resource/resmgr/reference_documents_/siso-ref-010-v35.zip
        "entityType": {"attributes": {"kind": 1, "domain": 2, "country": 225, "category": 220, "subcategory": 220, "specific": 220, "extra": 220}},
        "affiliation": "TENA::LVC::Affiliation_Friendly",
        "damageState": "TENA::LVC::DamageState_NoDamage",
        "deadReckoningAlgorithm": "TENA::LVC::DeadReckoningAlgorithm_RVW",
        "appearance": {"attributes": {"EntityKindDomain": "TENA::LVC::EntityKindDomain_AirPlatform"}}
    }
}

#This function parses a CSV file containing waypoint data and returns a list of waypoints
#if you have different data, you will need to modify this function
def waypoint(waypoint_list):
    with open(waypoint_list, mode='r', encoding='utf-8') as file:
        csv_reader = csv.DictReader(file)
        return [
            {
                'index': int(row['index']),
                'x': float(row['x']),
                'y': float(row['y']),
                'z': float(row['z']),
                'carla_heading': float(row['carla_heading']),
                'geo_heading': float(row['geo_heading']),
                'latitude': float(row['latitude']),
                'longitude': float(row['longitude']),
                'altitude': float(row['altitude']),
                'linear_distance': float(row['linear_distance'])
            }
            for row in csv_reader
        ]

# get next waypoints based on system control algorithm how far you advance should be determined
def get_object_data_from_waypoints(waypoint_data):
    # from here, it is up to the end user to determine what how to proceed
    # and generate the next location along the waypoint track.
    # this will likely involve using the current location, speed, acceleration,
    # then make a determination on whether to accelerate, decelerate, or stay at current speed.
    # then, using that speed and the chosen data_update_period, you can determine how far along
    # the waypoints the vehicle should advance over that time period.
    # this could also take into account the location of other vehicles or traffic signal state
    # based on the received JSON data

    # distance traveled per time interval
    total_distance = fake_api.vehicle_algorithm(waypoint_data)
    # once you find the distance traveled, you need to move that distance along the path created by the waypoints.
    # this will likely land you inbetween two waypoints.
    # you may decide how to handle this:
    #   - round down the the nearest waypoint (shown below)
    #   - interpolate between the two waypoints you land between
    #       (linear distance between two waypoints should be less than 1 foot/0.3 meters)
    #   - something else

    # use this new_linear_distance to figure out which waypoints you fall between
    # use the logic you decided on in the previous step to select/generate waypoint data for your new location

    last_waypoint = waypoint_data[0]
    # to keep our place on the waypoints, we want to remove all waypoints before and including the selected waypoint
    while waypoint_data and total_distance > waypoint_data[0]['linear_distance']:
        last_waypoint = waypoint_data.pop(0)

    # finally we can pack the location data into an object which will eventually be packed into a JSON
    # fields should match the final destination fields in the JSON
    # it is not required, but helpful to include velocity and acceleration
    # TODO note required and optional (useful) fields here for each object model
    object_data = last_waypoint
    return [object_data]

def get_object_data_from_api(vehicle_list, trafficSignalController_list):

    # this will retrieve object data from a specific API
    # make sure to get all required fields for the desired objects
    # this data must include the desired object model name
    
    object_data_list = []

    api_vehicle_data = fake_api.get_vehicles()
    
    for vehicle in api_vehicle_data: 
        if vehicle.id in vehicle_list:
            object_data_list.append( "LandVehicle",vehicle ) 

    api_tsc_data = fake_api.get_trafficSignalControllers()

    for tsc in api_tsc_data: 
        if tsc.id in trafficSignalController_list:
            object_data_list.append( "TrafficSignalController",tsc )


    return object_data_list

def pack_object_data_into_json(object_data_list): 

    # take the data retrieved from the waypoints and pack into JSON format
    object_data_json_list = []

    # loop through data list and pack each object data into JSON
    for object_data in object_data_list:
        object_data_json = copy.deepcopy(landVehicle_json_template)

        object_data_json["attributes"]["identifier"] = "test_vehicle"
        object_data_json["attributes"]["designation"] = "test_vehicle"
        object_data_json["attributes"]["tspi"]["attributes"]["time"]["attributes"]["nanosecondsSince1970"] = time.time_ns()
        object_data_json["attributes"]["tspi"]["attributes"]["position"]["attributes"]["geodetic_asTransmitted"]["attributes"]["latitudeInDegrees"] = object_data['latitude']
        object_data_json["attributes"]["tspi"]["attributes"]["position"]["attributes"]["geodetic_asTransmitted"]["attributes"]["longitudeInDegrees"] = object_data['longitude']
        object_data_json["attributes"]["tspi"]["attributes"]["position"]["attributes"]["geodetic_asTransmitted"]["attributes"]["heightAboveEllipsoidInMeters"] = object_data['altitude']
        object_data_json["attributes"]["tspi"]["attributes"]["orientation"]["attributes"]["frdWRTltpENUbodyFixedZYX_asTransmitted"]["attributes"]["srf"]["attributes"]["latitudeInDegrees"] = object_data['latitude']
        object_data_json["attributes"]["tspi"]["attributes"]["orientation"]["attributes"]["frdWRTltpENUbodyFixedZYX_asTransmitted"]["attributes"]["srf"]["attributes"]["longitudeInDegrees"] = object_data['longitude']
        object_data_json["attributes"]["tspi"]["attributes"]["orientation"]["attributes"]["frdWRTltpENUbodyFixedZYX_asTransmitted"]["attributes"]["srf"]["attributes"]["heightAboveEllipsoidInMeters"] = object_data['altitude']
        object_data_json_list.append(object_data_json)

    return object_data_json_list

def transmit_object_json(object_json_list, EntityName, EntityMap):
    for object_json in object_json_list:
        tena_publisher_url = f"http://{PUBLISHER_IP}/v1/objects/{OBJECT_TYPE}/{ENTITY_TYPE}"
        if EntityName not in EntityMap.keys():
            # print(json.dumps(object_json, indent=2))
            initial_response = requests.post(tena_publisher_url, json=object_json)
            sdo_index = (ast.literal_eval(initial_response.text)).get("sdo_index")
            tena_publisher_url += "/" + str(sdo_index)
            EntityMap[EntityName] = tena_publisher_url
            print('sent creation')
        else:
            update_response = requests.put(EntityMap[EntityName], json=object_json)
            print('sent update')

    return


## TODO - set this up such that if someone wants to send multiple vehicles or traffic signals, they can
def transmit_main():

    #this is a list of vehicles and traffic signals to track in the scenario
    vehicle_list = []
    trafficSignalController_list = []

    #hashmap of vehicle ID to entity ID and
    EntityMap = {}

    # period for retrieval of data (in seconds)
    data_update_period = 1

    # give them an option to choose at runtime to use waypoints or API
    
    if GET_OBJECT_TYPE == "waypoints":
        # retrieve waypoints from CSV instead of hardcoded list, ideall from runtime arg
        object_json_list = waypoint(SELECTED_WAYPOINT_CSV)
        selectMethod = get_object_data_from_waypoints
        args = (object_json_list,) # always just one vehicle when using waypoints
    elif GET_OBJECT_TYPE == "api":
        selectMethod = get_object_data_from_api
        args = (vehicle_list,trafficSignalController_list) # can be multiple vehicles and traffic signals when using API
    else:
        print("Invalid getObjectDataType, must be 'waypoints' or 'api'")
        return

    while True: 

        ##### Step 1: Get object data
        # This can be from either
        #   - an application API or 
        #   - a list of waypoints

        # if using waypoints, you must utilize your control algorithm 
        # to determine how far to advance down the waypoint track at each step
        # we send the first item in the list becuase, if we are using waypoints, 
        # our list will always contain just a single entry, our vehicle
        # OR
        # if using an API, the environment you are interfacing with is assumed to be advancing the vehicle
        # so we can simply retrieve the current location of the vehicle at this time
        # object_data_list = get_object_data_from_api(vehicle_list,trafficSignalController_list)
        object_data_list = selectMethod(*args)

        ##### Step 2: pack data into JSON
        # This 
        object_json_list = pack_object_data_into_json(object_data_list)
        EntityName = "test_vehicle" # TODO get this from the object data
        ##### Step 3: transmit the JSON 
        # This 
        # TODO adapt code such that the transmitter can handle multiple objects from the provided lists
        #      this includes capturing the entity_index and url and other properties
        #      you can pack these into the dictionaries provided
        transmit_object_json(object_json_list,EntityName, EntityMap)

        time.sleep(data_update_period)

# this will open a UDP socket to receive JSON
def receive_main():

    # open a UDP socket at a configurable IP and port
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Define host and port
    HOST = '127.0.0.1'  # Listen on all interfaces
    PORT = 9000  # Choose an unused port

    # Bind the socket
    server_socket.bind((HOST, PORT))
    server_socket.listen(1)

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

    # this will recieve JSON data from JSON Tools

    # it is up to the end user to decide what to do with it
    #   this could be simply including 

# TODO make this actually functional
def main():

    receive_thread = threading.Thread(target=receive_main)
    send_thread = threading.Thread(target=transmit_main)
    receive_thread.start()
    send_thread.start()

if __name__ == "__main__":
    main()
