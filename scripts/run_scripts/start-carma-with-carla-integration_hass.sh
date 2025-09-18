#!/bin/bash
trap cleanup SIGINT

function cleanup {
    echo "----- STOPPING CARMA PLATFORM -----"
	sudo -u carma carma stop all
}

function print_help {
	echo
	echo "Pilot 1 Test 4 usage: --map smart_intersection --no_tick"
	echo
	echo "usage: start-carla.sh [--no_tick] [--low_quality] [--help]"
	echo
	echo "Start CARLA Simulator for Distributed Testing"
	echo
	echo "optional arguments:"
	echo "    --help             show help"
	echo
}

dt_site_config=$HOME/.dt_site_config
dt_scenario_config=$HOME/.dt_scenario_config

dt_site_config_docker=$HOME/.dt_site_config_docker
dt_scenario_config_docker=$HOME/.dt_scenario_config_docker

if [ -L ${dt_site_config} ] && [ -L ${dt_scenario_config} ]; then
    if [ -e ${dt_site_config} ] && [ -e ${dt_scenario_config} ]; then
        site_config_link_dest=$(readlink -f $dt_site_config)
        site_link_base_name=$(basename ${site_config_link_dest})

        scenario_config_link_dest=$(readlink -f $dt_scenario_config)
        scenario_link_base_name=$(basename ${scenario_config_link_dest})

        source $HOME/.dt_site_config

		# if dt config docker exists, then source it to overwrite docker specific vars
		if [ -e ${dt_site_config_docker} ]; then
			source $HOME/.dt_site_config_docker
		fi

		source $HOME/.dt_scenario_config

		if [ -e ${dt_scenario_config_docker} ]; then
			source $HOME/.dt_scenario_config_docker
		fi

        echo "Site Config: "$site_link_base_name
        echo "Scenario Config: "$scenario_link_base_name
    else
        echo "[!!!] .dt_site_config or .dt_scenario_config link is broken"
        echo "Site Config: "$(readlink -f $site_link_base_name)
        echo "Scenario Config: "$(readlink -f $scenario_link_base_name)
        exit 1
   fi
elif [ -e ${dt_site_config} ] || [ -e ${dt_site_config} ]; then
    echo "[!!!] .dt_site_config or .dt_scenario_config file is not a symbolic link"
    echo "Site Config: "$(readlink -f $site_link_base_name)
    echo "Scenario Config: "$(readlink -f $scenario_link_base_name)
    exit 1
else
    echo "[!!!] .dt_site_config or .dt_scenario_config symbolic link does not exist"
    echo "Site Config: "$(readlink -f $site_link_base_name)
    echo "Scenario Config: "$(readlink -f $scenario_link_base_name)
    exit 1
fi

mkdir -p $VUG_CARMA_SIM_LOG_PATH

CARLA_LOG=$VUG_CARMA_SIM_LOG_PATH/dt_carla_simulator.log
SIM_LOG=$VUG_CARMA_SIM_LOG_PATH/dt_carla_carma_integration.log
SET_TIME_MODE_LOG=$VUG_CARMA_SIM_LOG_PATH/set_time_mode.log

echo "" >> $CARLA_LOG
echo "<< ***** New Session **** >>" >> $CARLA_LOG
date >> $CARLA_LOG
echo "" >> $SIM_LOG
echo "<< ***** New Session **** >>" >> $SIM_LOG
date >> $SIM_LOG


no_tick_enabled=false
timeSyncEnabled=false
low_quality_flag=""
next_flag_is_map=false
carla_map=""


for arg in "$@"
do

	if [[ $arg == "--help" ]]; then
		
		print_help
		exit

	elif [[ $arg != "" ]]; then
		
		echo
		echo "Invalid argument: $arg"
		print_help
		exit

	fi
done

echo "----- STARTING VEHICLE E-BRAKE SCRIPT -----"

$VUG_LOCAL_DT_PATH/scripts/docker_scripts/stop_all_vehicles.sh &> /dev/null &

echo "----- STARTING CARMA PLATFORM -----"

sudo -u carma carma start all -d

echo "----- WAITING FOR CARMA PLATFORM TO STARTUP -----"

sleep 10

echo "----- STARTING CARLA-CARMA INTEGRATION TOOL -----"

$VUG_LOCAL_DT_PATH/scripts/run_scripts/pilot2/src/start-carma-carla-integration_hass.sh

cleanup
