## CARLA Python Scripts
These scripts are used to interact with the CARLA Python API in a CARLA simulation.

## Prerequisites
The use of these scripts requires a Python3 installation and the carla Python package available. For the scripts to use the carla Python package you must either:

- Copy the script to the PythonAPI folder.

  or

 - Have a built version of the Python API located at `~/carla/PythonAPI`. Instructions for building the API can be found [here](https://carla.readthedocs.io/en/0.9.15/build_linux/#carla-build).

## Executing Scripts
Scripts are executed using python3:

`python3 manual_control_steeringwheel_ff.py`

NOTE: The CARLA Simulator must be running to execute these scripts. 

## Script Details

 **manual_control_steeringwheel_ff.py**
 Spawns a vehicle and allows the user to manually control a vehicle using a steering wheel including force feedback. Must have wheel_config.ini in the same directory in order to import the steering wheel config. The included wheel_config.ini was configured for the G29 Racing Wheel.

**list_maps.py**
Lists all available maps in the CARLA simulator.

**spawn_npc.py**
Spawns npc vehicles and pedestrians.

**get_signals.py**
Lists all traffic signals in the CARLA simulator.

**destroy_signals.py**
Destroys all traffic signals in the CARLA simulator.

## Ubuntu Desktop Shortcuts
Desktop shortcuts for Ubuntu 20.04 are included in the `ubuntu_desktop_shortcuts` directory. To use the shortcuts, copy them to the desktop or create symbolic links on the desktop. The path in each file will need to be modified to match the username as well as the location of the CARLA simulator. Finally, right click on the shortcuts from the desktop and click `Allow Launching`. 


