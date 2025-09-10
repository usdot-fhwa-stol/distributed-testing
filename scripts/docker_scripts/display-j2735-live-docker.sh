#!/bin/bash 

docker exec -it --user root voices bash -c 'export HOME=/home && export VUG_CARLA_EGG_DIR=/home/CARLA_0.9.10/PythonAPI && cd $HOME/voices-poc/scripts/carla_python_scripts/ && python3 draw_j2735_live.py'