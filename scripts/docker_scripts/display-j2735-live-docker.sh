#!/bin/bash 

docker exec -it --user root dt-core bash -c 'export HOME=/home && export VUG_CARLA_EGG_DIR=/home/CARLA_0.9.10/PythonAPI && cd $HOME/distributed-testing/scripts/carla_python_scripts/ && python3 draw_j2735_live.py'