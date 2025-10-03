"""
    json_templates.py

    This module provides templates, field maps, and helper functions for creating landVehicle JSON messages with different coordinate formats.

    Contents:
    - Templates:
        1. base_landVehicle_template: common fields shared by all messages.
        2. ltpENU_tspi_template: tspi fields in ltpENU coordinate format.
        3. geocentric_tspi_template: tspi fields in geocentric coordinate format.
    - Field maps:
        1. ltpENU_field_mappings: maps API or waypoint object data keys to paths in ltpENU_tspi_template.
        2. geocentric_field_mappings: maps API or waypoint object data keys to paths in geocentric_tspi_template.
    - Helper functions:
        1. set_nested(d, path, value): safely sets a value in a nested dict.
        2. pack_object_data_into_json(object_data_list, coordinate_format, source_id): populates templates using a list
            of objects and your specified coordinate format.
"""

import json
import time
import copy

# ================
# Templates
# ================

# Base LandVehicle Template: contains shared fields except for tspi information
base_landVehicle_template = {
    "attributes": {
        "identifier": "JSON-M-1",
        "designation": "Unset",
        "sourceIdentifier": "CARLA-JSON-1",
        "entityID": {
            "attributes": {
                "siteID": 0, 
                "applicationID": 0, 
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
        "sensorPedigree": [],
        "trackPedigree": [],
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

# ltpENU tspi template: 
ltpENU_tspi_template = {
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
                        "vxInMetersPerSecond": 0.0,
                        "vyInMetersPerSecond": 0.0,
                        "vzInMetersPerSecond": 0.0
                    }
                }
            }
        },
        "acceleration": {
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
                        "axInMetersPerSecondSquared": 0.0,
                        "ayInMetersPerSecondSquared": 0.0,
                        "azInMetersPerSecondSquared": 0.0
                    }
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
}

# geocentric tspi template
geocentric_tspi_template = {
    "attributes": {
        "time": {
            "attributes": {
                "nanosecondsSince1970": 0
            }
        },
        "position": {
            "attributes": {
                "geocentric_asTransmitted": {
                    "attributes": {
                        "srf": {
                            "attributes": {
                                "rtCode": "TENA::RTCODE_WGS_1984_IDENTITY"
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
                "geocentric_asTransmitted": {
                    "attributes": {
                        "srf": {
                            "attributes": {
                                "rtCode": "TENA::RTCODE_WGS_1984_IDENTITY"
                            }
                        },
                        "vxInMetersPerSecond": 0.0,
                        "vyInMetersPerSecond": 0.0,
                        "vzInMetersPerSecond": 0.0
                    }
                }
            }
        },
        "acceleration": {
            "attributes": {
                "geocentric_asTransmitted": {
                    "attributes": {
                        "srf": {
                            "attributes": {
                                "rtCode": "TENA::RTCODE_WGS_1984_IDENTITY"
                            }
                        },
                        "axInMetersPerSecondSquared": 0.0,
                        "ayInMetersPerSecondSquared": 0.0,
                        "azInMetersPerSecondSquared": 0.0
                    }
                }
            }
        },
        "orientation": {
            "attributes": {
                "frdWRTgeocentricBodyFixedZYX_asTransmitted": {
                    "attributes": {
                        "srf": {
                            "attributes": {
                                "rtCode": "TENA::RTCODE_WGS_1984_IDENTITY"
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
}

# TODO: Base Traffic Signal Controller Template
base_trafficSignalController_template =  {
    "attributes": {
        "identifier": "Unset",
        "designation": "Unset",
        "sourceIdentifier": "",
        "tspi": {"attributes": {
                "time": {"attributes": {"nanosecondsSince1970": time.time_ns()}},
                "position": {"attributes": {"geodetic_asTransmitted": {"attributes": {"srf": {"attributes": {"rtCode": "TENA::RTCODE_WGS_1984_IDENTITY"}}, "latitudeInDegrees": 0.0, "longitudeInDegrees": 0.0, "heightAboveEllipsoidInMeters": 0.0}}}},
                "orientation": {"attributes": {"frdWRTltpENUbodyFixedZYX_asTransmitted": {"attributes": {"srf": {"attributes": {"rtCode": "TENA::RTCODE_WGS_1984_IDENTITY", "latitudeInDegrees": 0.0, "longitudeInDegrees": 0.0, "heightAboveEllipsoidInMeters": 0.0, "azimuthInRadians": 0.0, "xFalseOriginInMeters": 0.0, "yFalseOriginInMeters": 0.0}}, "rotZinRadians": 0.0, "rotYinRadians": 0.0, "rotXinRadians": 0.0}}}}}},
        "entityID": {"attributes": {"siteID": 0, "applicationID": 0, "objectID": None}},
        "lvcIndicator": "TENA::LVC::LVCindicator_Virtual",
        ###TODO need to figuire out this entity type from siso standard: https://www.sisostandards.org/resource/resmgr/reference_documents_/siso-ref-010-v35.zip
        "entityType": {"attributes": {"kind": 1, "domain": 2, "country": 225, "category": 220, "subcategory": 220, "specific": 220, "extra": 220}},
        "affiliation": "TENA::LVC::Affiliation_Friendly",
        "damageState": "TENA::LVC::DamageState_NoDamage",
        "deadReckoningAlgorithm": "TENA::LVC::DeadReckoningAlgorithm_RVW",
        "appearance": {"attributes": {"EntityKindDomain": "TENA::LVC::EntityKindDomain_AirPlatform"}}
    }
}

# ================
# Field Maps
# ================

# Maps object data keys to paths in the ltpENU tspi template
ltpENU_field_mappings = {
    "x":["attributes", "tspi", "attributes", "position", "attributes", "ltpENU_asTransmitted", "attributes","xInMeters"],
    "y":["attributes", "tspi", "attributes", "position", "attributes", "ltpENU_asTransmitted", "attributes","yInMeters"],
    "z":["attributes", "tspi", "attributes", "position", "attributes", "ltpENU_asTransmitted", "attributes","zInMeters"],
    "vx":["attributes", "tspi", "attributes", "velocity", "attributes", "ltpENU_asTransmitted", "attributes","vxInMetersPerSecond"],
    "vy":["attributes", "tspi", "attributes", "velocity", "attributes", "ltpENU_asTransmitted", "attributes","vyInMetersPerSecond"],
    "vz":["attributes", "tspi", "attributes", "velocity", "attributes", "ltpENU_asTransmitted", "attributes","vzInMetersPerSecond"],
    "ax":["attributes", "tspi", "attributes", "acceleration", "attributes", "ltpENU_asTransmitted", "attributes","axInMetersPerSecondSquared"],
    "ay":["attributes", "tspi", "attributes", "acceleration", "attributes", "ltpENU_asTransmitted", "attributes","ayInMetersPerSecondSquared"],
    "az":["attributes", "tspi", "attributes", "acceleration", "attributes", "ltpENU_asTransmitted", "attributes","azInMetersPerSecondSquared"],
    "yaw":["attributes", "tspi", "attributes", "orientation", "attributes", "frdWRTltpENUbodyFixedZYX_asTransmitted", "attributes","rotZinRadians"],
    "pitch":["attributes", "tspi", "attributes", "orientation", "attributes", "frdWRTltpENUbodyFixedZYX_asTransmitted", "attributes","rotYinRadians"],
    "roll":["attributes", "tspi", "attributes", "orientation", "attributes", "frdWRTltpENUbodyFixedZYX_asTransmitted", "attributes","rotXinRadians"]
}

# Maps object data keys to paths in the geocentric tspi template
geocentric_field_mappings = {
    "x":["attributes", "tspi", "attributes", "position", "attributes", "geocentric_asTransmitted", "attributes","xInMeters"],
    "y":["attributes", "tspi", "attributes", "position", "attributes", "geocentric_asTransmitted", "attributes","yInMeters"],
    "z":["attributes", "tspi", "attributes", "position", "attributes", "geocentric_asTransmitted", "attributes","zInMeters"],
    "vx":["attributes", "tspi", "attributes", "velocity", "attributes", "geocentric_asTransmitted", "attributes","vxInMetersPerSecond"],
    "vy":["attributes", "tspi", "attributes", "velocity", "attributes", "geocentric_asTransmitted", "attributes","vyInMetersPerSecond"],
    "vz":["attributes", "tspi", "attributes", "velocity", "attributes", "geocentric_asTransmitted", "attributes","vzInMetersPerSecond"],
    "ax":["attributes", "tspi", "attributes", "acceleration", "attributes", "geocentric_asTransmitted", "attributes","axInMetersPerSecondSquared"],
    "ay":["attributes", "tspi", "attributes", "acceleration", "attributes", "geocentric_asTransmitted", "attributes","ayInMetersPerSecondSquared"],
    "az":["attributes", "tspi", "attributes", "acceleration", "attributes", "geocentric_asTransmitted", "attributes","azInMetersPerSecondSquared"],
    "yaw":["attributes", "tspi", "attributes", "orientation", "attributes", "frdWRTgeocentricBodyFixedZYX_asTransmitted", "attributes","rotZinRadians"],
    "pitch":["attributes", "tspi", "attributes", "orientation", "attributes", "frdWRTgeocentricBodyFixedZYX_asTransmitted", "attributes","rotYinRadians"],
    "roll":["attributes", "tspi", "attributes", "orientation", "attributes", "frdWRTgeocentricBodyFixedZYX_asTransmitted", "attributes","rotXinRadians"]
}

# Maps TrafficSignalController specific data keys to paths in the base_trafficSignalController_template
trafficSignalController_field_mappings = {}

# ================
# Helper Functions
# ================

def set_nested(d, path, value):
    """
        Set a value in a nested dictionary at a location specified by a list of keys.

        Walks through the nested dictionary 'd' following the sequence of keys in 'path'.
        If intermediate dictionaries do not exist, they are created.
        The final key in 'path' is assigned the given 'value'

        Parameters
        ----------
        d : dict
            The dictionary to modify.
        path : list of str
            A list of keys specifying the path where the value should be set.
            The last key in the list is the target key for 'value'.
        value : any
            The value to set at the specified location.

        Returns
        -------
        None
            The dictionary 'd' is modified in place.
    """
    # Traverse the path, creating intermediate dictionaries if needed
    for key in path[:-1]:
        #If the key doesn't exist, set it to an empty dict; then move into it
        d = d.setdefault(key,{})
    # Set the final key to the given value
    d[path[-1]] = value


def pack_object_data_into_json(object_data_list, coordinate_format, source_id):
    """
        Create JSON messages for a list of objects using the templates defined above

        For each object in 'object_data_list' this function:
        - Determines the type of object: (LandVehicle, or TrafficSignalController)
        - Selects the appropriate templates based on 'coordinate_format'
        - Populates the template fields with data from the object and the provided source_id
        - Returns a list of fully populated JSON dictionaries

        Parameters
        ----------
        object_data_list : list of dict
            List of objects to create JSON messages for. Each object is expected to
            contain fields corresponding to the chosen coordinate format.
        coordinate_format : str
            The coordinate format to use. Must be either "ltpENU" or "geocentric"
        source_id : str
            The identifier of the source sending the JSON messages

        Returns
        -------
        object_data_json_list : list of dict
            A list of populated JSON dictionaries, one per object in 'object_data_list'
    """
    # Create the list of JSON objects to be returned
    object_data_json_list = []

    # Determines which tspi template to use based on 'coordinate_format'
    if coordinate_format == "geocentric":
        tspi_template = geocentric_tspi_template
        tspi_field_map = geocentric_field_mappings
    elif coordinate_format == "ltpENU":
        tspi_template = ltpENU_tspi_template
        tspi_field_map = ltpENU_field_mappings
    else:
        raise ValueError(f"Unknown coordinate format: {coordinate_format}")

    # Create a JSON for each object in 'object_data_list', then appends it to our list
    for object_data in object_data_list:
        object_type = object_data["object_type"]
        
        # Determines which object template to use for the current object
        if object_type == "LandVehicle":
            object_data_json = copy.deepcopy(base_landVehicle_template)
        elif object_type == "TrafficSignalController":
            object_data_json = copy.deepcopy(base_trafficSignalController_template)

            # Populate TrafficSignalController specific fields using the current object data
            for key, path in trafficSignalController_field_mappings.items():
                if key in object_data:
                    set_nested(object_data_json, path, object_data[key])
        else:
            raise ValueError(f"Unknown object type: {object_type}")

        # Populate common fields of the object templates
        object_data_json["attributes"]["identifier"] = object_data["role_name"] #This will need to be in object data
        object_data_json["attributes"]["entityID"]["attributes"]["siteID"] = int(source_id.split(':')[0])
        object_data_json["attributes"]["entityID"]["attributes"]["applicationID"] = int(source_id.split(':')[1])
        # Insert the tspi template to our base template and begin populating the values
        object_data_json["attributes"]["tspi"] = copy.deepcopy(ltpENU_tspi_template)
        object_data_json["attributes"]["tspi"]["attributes"]["time"]["attributes"]["nanosecondsSince1970"] = time.time_ns()

        # Populate existing tspi fields using the current object data
        for key, path in tspi_field_map.items():
            if key in object_data:
                set_nested(object_data_json, path, object_data[key])

        # Add the current object JSON to the list
        object_data_json_list.append(object_data_json)

    return object_data_json_list

