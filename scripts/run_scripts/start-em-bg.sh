#!/bin/bash

# Start Execution Manager

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

$VUG_EM_PATH/start.sh \
    -listenEndpoints $VUG_EM_ADDRESS:$VUG_EM_PORT \
    -logDir $VUG_EM_PATH/log \
    -recoveryDir $VUG_EM_PATH/save \
    -connectionTimeoutInMilliseconds 10000 -twowayTimeoutInMilliseconds 20000 \
    -transientCommunicationAttempts 3 -disconnectTimeoutInMilliseconds 5000 \
    -quiet -nonInteractive &
