#!/usr/bin/bash

# Confirm configs are the desired ones
voices_site_config=$HOME/.voices_site_config
voices_scenario_config=$HOME/.voices_scenario_config
if [ -L ${voices_site_config} ] && [ -L ${voices_scenario_config} ]; then
    if [ -e ${voices_site_config} ] && [ -e ${voices_scenario_config} ]; then
        site_config_link_dest=$(readlink -f $voices_site_config)
        site_link_base_name=$(basename ${site_config_link_dest})

        scenario_config_link_dest=$(readlink -f $voices_scenario_config)
        scenario_link_base_name=$(basename ${scenario_config_link_dest})
    fi
fi

#TODO:  
#       
#       This is cumbersome to give sudo all the time 
#       when you are not testing with a VPN. 
#       --> potentially find a way to not need sudo 
# Get output from openvpn3 sessions-list
echo "Checking for stale VPN connections..."
openvpn_sessions="$(sudo openvpn3 sessions-list)"
vpn_paths=()
path_regex='Path: (.*)'
vpn_statuses=()
status_regex='Status: (.*)'
has_stale_vpn_connections=false
has_active_vpn_connection=false
has_multiple_active_vpn_connections=false
vpn_start_times=()
start_time_regex='Created: (.*) PID: .*'
iterator=0
while read line; do
    if [[ $line =~ $path_regex ]]
    then # Grab VPN path
        vpn_paths+=("${BASH_REMATCH[1]}")
    elif [[ $line =~ $status_regex ]]
    then # Grab VPN status
        if [[ ${BASH_REMATCH[1]} = "Connection, Client connected" ]]
        then
            if $has_active_vpn_connection
            then
                has_multiple_active_vpn_connections=true
            fi
            vpn_statuses+=(1)
            has_active_vpn_connection=true
        else
            vpn_statuses+=(0)
            has_stale_vpn_connections=true
        fi
    elif [[ $line =~ $start_time_regex ]]
    then # Grab VPN start time and convert to unix timestamp
        vpn_start_times+=("$(date -d "${BASH_REMATCH[1]}" +"%s")")
    fi
done <<< "$openvpn_sessions"

if $has_stale_vpn_connections
then
    while true; do
        echo
        read -p "You have stale VPN connections. Would you like to remove them? [Y/n] " yn
        case $yn in
            [Yy]* | "") for i in $(seq 1 ${#vpn_statuses[@]}); do
                        if [[ ${vpn_statuses[i-1]} = 0 ]]
                        then
                            echo
                            echo "Removing "${vpn_paths[i-1]}
                            sudo openvpn3 session-manage --session-path ${vpn_paths[i-1]} --disconnect
                        fi
                    done; break;;
            [Nn]* ) echo; break;;
            * );;
        esac
    done
else
    echo
    echo "No stale VPN connections found."
fi


if $has_multiple_active_vpn_connections
then
    most_recent_start=0
    for i in $(seq 1 ${#vpn_start_times[@]}); do
        if [ ${vpn_start_times[i-1]} -gt $most_recent_start ] && [ ${vpn_statuses[i-1]} = 1 ]; then
            most_recent_start=${vpn_start_times[i-1]}
        fi
    done
    while true; do
        echo
        echo 'You have multiple active VPN connections.'
        read -p "Would you like to remove all but the most recent? [y/N] " yn
        case $yn in
            [Yy]*) for i in $(seq 1 ${#vpn_statuses[@]}); do
                        if [ ${vpn_statuses[i-1]} = 1 -a ${vpn_start_times[i-1]} != $most_recent_start ]
                        then
                            echo
                            echo "Removing "${vpn_paths[i-1]}
                            sudo openvpn3 session-manage --session-path ${vpn_paths[i-1]} --disconnect
                        fi
                    done; break;;
            [Nn]* | "") echo; break;;
            * );;
        esac
    done
elif $has_active_vpn_connection
then
    most_recent_start=0
    for i in $(seq 1 ${#vpn_start_times[@]}); do
        if [ ${vpn_start_times[i-1]} -gt $most_recent_start ] && [ ${vpn_statuses[i-1]} = 1 ]; then
            most_recent_start=${vpn_start_times[i-1]}
        fi
    done
    if [ $VUG_FORMAL_EVENT = false ]
    then
        while true; do
            echo
            read -p "You have an active VPN session but have set VUG_FORMAL_EVENT=false. Would you like to terminate the session? [y/N] " yn
            case $yn in
                [Yy]*)  for i in $(seq 1 ${#vpn_statuses[@]}); do
                            if [ ${vpn_statuses[i-1]} = 1 -a ${vpn_start_times[i-1]} = $most_recent_start ]
                            then
                                echo
                                echo "Removing "${vpn_paths[i-1]}
                                sudo openvpn3 session-manage --session-path ${vpn_paths[i-1]} --disconnect
                            fi
                        done; break;;
                [Nn]* | "") echo; break;;
                * );;
            esac
        done
    fi
else
    if [ $VUG_FORMAL_EVENT = true ]
    then
        echo
        echo "No active VPN connections found. Please connect to an openvpn3 session or set VUG_FORMAL_EVENT=false in your scenario config to continue."
        exit 1
    fi
fi