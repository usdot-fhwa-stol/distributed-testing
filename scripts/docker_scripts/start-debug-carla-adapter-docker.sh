#!/bin/bash

docker exec -it --user root dt-core bash -c 'export HOME=/home && export VUG_CARLA_EGG_DIR=/home/CARLA/PythonAPI && /home/distributed-testing/scripts/run_scripts/pilot2/src/start-debug-carla-adapter.sh > /tmp/tls.txt && cd /home/distributed-testing/scripts/carla_python_scripts/ && pwd && python3 /home/distributed-testing/scripts/carla_python_scripts/get_trafficSignal_actorID.py -f /tmp/tls.txt && python3 /home/distributed-testing/scripts/carla_python_scripts/draw_landmarks.py '
