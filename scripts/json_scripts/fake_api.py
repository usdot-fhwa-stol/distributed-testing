# API Functions
# 
# These are the functions that the API should support

import random

#TODO just have distance travel returned as some number in meters (0<x<2)

def vehicle_algorithm():
    if not hasattr(vehicle_algorithm, "previous_distance"):
        vehicle_algorithm.previous_distance = 0.0
    increment = random.uniform(0,2)
    print(increment)
    vehicle_algorithm.previous_distance += increment
    print(vehicle_algorithm.previous_distance)
    return vehicle_algorithm.previous_distance

def get_vehicles():
    return None

def get_trafficSignalControllers():
    return None
