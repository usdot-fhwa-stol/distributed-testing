# API Functions
# 
# These are the functions that the API should support

#TODO just have distance travel returned as some number in meters (0<x<2)

def vehicle_algorithm(waypoint_data):
    if len(waypoint_data) > 1:
        return waypoint_data[1]['linear_distance'] + 0.00001
    elif len(waypoint_data) > 0:
        return 1e9
    else:
        return None

def get_vehicles():
    return None

def get_trafficSignalControllers():
    return None
