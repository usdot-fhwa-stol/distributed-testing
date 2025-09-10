#!/bin/bash

docker exec -it --user root voices bash -c 'export HOME=/home && /home/distributed-testing/scripts/run_scripts/pilot2/src/start-tj2735-message-adapter-extra.sh'
