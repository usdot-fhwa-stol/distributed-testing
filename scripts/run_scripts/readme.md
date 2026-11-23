## Run Scripts
These scripts are used to execute TENA adapters. Parameters for each script can be found at the top of each file and should be modified for your execution. Run scripts are divided into folders based on the node where they should be executed.

## CARLA Node
**runCarlaAdapter.sh**
This script runs the TENA CARLA adapter. 

## TENA Node
**runEntityGenerator.sh**
This script runs the TENA Entity Generator.

**runScenarioPublisher.sh**
This script runs the TENA Scenario Publisher

## V2X Node
**runTenaspatplugin_east.sh**
This script runs the TENA SPaT Plugin for the TFHRC East Intersection.

**runTenaspatplugin_west.sh**
This script runs the TENA SPaT Plugin for the TFHRC West Intersection.

NOTE: The above scripts for the TENA SPaT Plugin assume the V2X Hub docker container name is `v2xhub` and the instructions for Installing Multiple tenaspatplugins were followed. 

