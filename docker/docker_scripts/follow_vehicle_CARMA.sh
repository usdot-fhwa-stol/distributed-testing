#!/bin/bash 

docker exec --user root voices bash -c 'export HOME=/home && export VUG_CARLA_EGG_DIR=/home/CARLA_0.9.10/PythonAPI && cd $HOME/voices-poc/scripts/carla_python_scripts/ && python3 manual_control_keyboard_virtual_pilot2.py --follow_vehicle carma_1'