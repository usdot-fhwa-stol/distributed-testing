#!/bin/bash 

docker exec --user root dt-core bash -c 'export HOME=/home && export VUG_CARLA_EGG_DIR=/home/CARLA/PythonAPI && cd $HOME/distributed-testing/scripts/carla_python_scripts/ && python3 stop_vehicles.py'