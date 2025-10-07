"""
    fake_api.py

    This module is only provided as an example. It emulates a simplified API for demonstration purposes.
    It provides functions to retrieve LandVehicle and TrafficSignalController objects.
    It also includes a 'vehicle_algorithm' to use as an example for breadcrumb/waypoint following.

    Functions:
    - vehicle_algorithm(): Simulates a distrance-tracking function by returning a cumulative distance traveled
    - get_vehicles(): Returns a list of example vehicle objects
    - get_trafficSignalControllers(): Returns a list of example traffic signal controller objects
"""

import random

#TODO just have distance travel returned as some number in meters (0<x<2)

def vehicle_algorithm():
    """
        Simulates a total distance traveled by a vehicle.

        Uses a function attribute 'previous_distance' to track cumulative distance across calls.
        Each call increases the distance by a random float between 0 and 2

        Returns
        -------
        vehicle_algorithm.previous_distance: float
            The total distance traveled
    """

    # Initializes the previous distance if not present
    if not hasattr(vehicle_algorithm, "previous_distance"):
        vehicle_algorithm.previous_distance = 0.0

    # Add a random float increment between 0 and 2
    increment = random.uniform(0,2)
    vehicle_algorithm.previous_distance += increment

    return vehicle_algorithm.previous_distance

def get_vehicles():
    """
        Simulates retrieving a list of vehicle objects from an API.

        Returns a list of dictionaries, where each dictionary represents a vehicle object with example attributes.
        Used to demonstrate the JSON creation and publishing.
        In this example, there are 5 vehicles platooning down a straightaway

        Returns
        -------
        vehicle_list: list of dict
            Example list of vehicle objects
    """
    vehicle_list = []
    # Initializes the previous distance of the tail vehicle in this example
    if not hasattr(get_vehicles, "previous_distance"):
        get_vehicles.previous_distance = 37.893444
    
    # Creates the vehicle object for each of the 5 vehicles
    for x in range(0,5):
        vehicle_info = {
            "vehicle_name":"JSON-M-" + str(x + 1),
            "xPosition":get_vehicles.previous_distance + (26 * x),
            "yPosition":169.453527,
            "zPosition":0.188207,
            "yawDeg":0.431426,
            "pitchDeg":0.062462,
            "rollDeg":-0.000031
        }
        vehicle_list.append(vehicle_info)
    
    # Updates the tail vehicles position for the next call of this functino
    get_vehicles.previous_distance += 5

    return vehicle_list

def get_trafficSignalControllers():
    """
        Simulates retrieving a list of traffic signal controller objects from an API.

        Returns a list of dictionaries, where each dictionary represents a traffic signal controller object with example attributes.
        Used to demonstrate the JSON creation and publishing.

        Returns
        -------
        trafficSignalController_list: list of dict
            Example list of traffic signal controller objects
    """
    trafficSignalController_list = []
    return trafficSignalController_list
