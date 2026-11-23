## Scripts
The following directories contain scripts which are used to build, install, and/or run TENA adapters. More information for each directory can be found in the sections below. 
This branch contain scripts that decode either a single payload or an entire pcap file. More information for each script can be found in below.

## build_tena_adapters
The buildTenaAdapters.sh automates the build process for TENA adapters which require a build container. Currently
 the script can be used to build the following adapters: 

 - Carla Adapter
 - TENA V2X Gateway
 - TENA SPaT Plugin

## carla_python_scripts
These scripts are used to interact with the CARLA Python API in a CARLA simulation.

## install_spat_plugins
This script and instructions help install multiple SPaT and TENA SPaT plugins. 

## run_scripts
These scripts are used to execute TENA adapters. 

## Updates to this branch

 - DecodeSinglePCAP -- This simple decoder will prompt the user to input a single J2735 payload. A decoded output will be displayed. 

 - J2735_pcap_decoder -- This decoder consists of multiple scripts that extract payloads from a give pcap file, parces and decodes the output, then further parces the decoded message into separate fields in a csv file. 
PCAP files must be placed in the data directory. 
To run the script within the src directory: bash J2735_pcap_decoder.sh
Fix needed for Traffic Control message IDs