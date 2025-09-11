#!/bin/bash

# set -e

function print_help {
	echo
	echo "usage: start-carla.sh [--no_tick] [--low_quality] [--help]"
	echo
	echo "Start CARLA Simulator for Distributed Testing"
	echo
	echo "optional arguments:"
	echo "    -d --debug         enable debug mode and step through each iteration"
	echo "    -v --verbose       enable verbose output"
	echo "    -h --help          show help"
	echo
}

debug_enabled=false
verbose_enabled=false

for arg in "$@"
do
	if [[ $arg == "-d" ]] || [[ $arg == "--debug" ]]; then
		
		debug_enabled=true

	elif [[ $arg == "-v" ]] || [[ $arg == "--verbose" ]]; then
		
		verbose_enabled=true

	elif [[ $arg == "-h" ]] || [[ $arg == "--help" ]]; then
		
		print_help
		exit

	elif [[ $arg != "" ]]; then
		
		echo
		echo "Invalid argument: $arg"
		print_help
		exit

	fi
done


# Find the default_site.config file
site_config_folder="./site_config"
default_site_config="$site_config_folder/default_site.config"

# Find the default_site.config file
scenario_config_folder="./scenario_config"
default_scenario_config="$scenario_config_folder/default_scenario.config"


check_configs () {

    config_folder=$1
    default_config=$2


    # Check if default_site.config exists
    if [ -e "$default_config" ]; then
        # Loop through all .config files in the config folder
        for other_config in "$config_folder"/*.config; do
            # Skip the default_site.config file itself
            if [ "$other_config" != "$default_config" ]; then
                # Compare files and print differences

                other_config_basename=$(basename $other_config)

                echo
                echo 'Comparing: '$other_config_basename

                # other file must have new line at end of file, add it if it doesnt exist
                # this part removes all newlines
                while [[ -s "$other_config" && -z "$(tail -c 1 "$other_config")" ]]; do
                    truncate -s -1 $other_config
                    other_last_char=$(tail -c 1 "$other_config")
                done

                # this one adds one back
                sed -i -e '$a\' $other_config            

                default_line_count=$(wc -l < "$default_config")
                other_line_count=$(wc -l < "$other_config")

                echo
                echo "default_site.config lines: "$default_line_count
                echo $other_config_basename "lines: "$other_line_count

                # Find the maximum
                if [ "$default_line_count" -gt "$other_line_count" ]; then
                    max_line_count="$default_line_count"
                else
                    max_line_count="$other_line_count"
                fi

                mapfile -t default_lines < "$default_config"
                mapfile -t other_lines < "$other_config"

                [ "$verbose_enabled" = true ] && echo

                line_index=0
                while (( $line_index <= max_line_count )); do

                    if [ "$debug_enabled" = true ]; then
                        echo
                        read -p "[PRESS ENTER TO CONTINUE] " test
                    fi
                    
                    [ "$verbose_enabled" = true ] && echo Checking Line: $((line_index + 1))

                    mapfile -t default_lines < "$default_config"
                    mapfile -t other_lines < "$other_config"

                    default_line_count=$(wc -l < "$default_config")
                    other_line_count=$(wc -l < "$other_config")

                    # Find the maximum
                    if [ "$default_line_count" -gt "$other_line_count" ]; then
                        max_line_count="$default_line_count"
                    else
                        max_line_count="$other_line_count"
                    fi


                    default_index=$((line_index))
                    other_index=$((line_index))

                    default_line=${default_lines[default_index]}
                    other_line=${other_lines[other_index]}

                    if [[ $default_line != $other_line ]]; then

                        if [[ $default_line == "#"* ]] || [[ $default_line == "" ]]; then
                            stripped_default_line=$default_line
                        else
                            stripped_default_line=$(echo $default_line | grep -oP "export \K.*(?==)")
                        fi

                        if [[ $other_line == "#"* ]] || [[ $other_line == "" ]]; then
                            stripped_other_line=$other_line
                        else
                            stripped_other_line=$(echo $other_line | grep -oP "export \K.*(?==)")
                            
                            # if stripped returns nothing, must be some weird non-matching line
                            # return the original line as we likely want to remove it
                            if [[ $stripped_other_line == "" ]]; then
                                stripped_other_line=$other_line
                            fi
                        fi

                        [ "$verbose_enabled" = true ] && echo $'\t[XXX] Config Lines do not Match: '

                        [ "$verbose_enabled" = true ] && echo $'\t\tDefault Line '"$((default_index + 1)): $default_line"
                        [ "$verbose_enabled" = true ] && echo $'\t\tOther Line '"$((other_index + 1)): $other_line"
                        [ "$verbose_enabled" = true ] && echo $'\t\tStripped Default Line '"$((default_index + 1)): $stripped_default_line"
                        [ "$verbose_enabled" = true ] && echo $'\t\tStripped Other Line '"$((other_index + 1)): $stripped_other_line"

                        if [[ $stripped_default_line == $stripped_other_line ]]; then
                            [ "$verbose_enabled" = true ] && echo $'\t\t[~~~] Default and other have same config param but different values'
                            ((line_index+=1))
                            continue
                        fi

                        # Check if the param exists in the other file but on a different line
                        # if it does, move on, if it doesnt, we need to add it
                        prev_other_line=${other_lines[other_index -1]}

                        if [[ $((other_index +1)) -lt $other_line_count ]] && [[ $other_line == "" ]]; then
                            [ "$verbose_enabled" = true ] && echo $'\t\t'"[---] Double newline was found in '$other_config', removing one."
                            other_index_d=$((other_index + 1))"d"
                            sed -i $other_index_d $other_config
                            continue
                        fi

                        if [[ $default_line == "" ]]; then
                            # if we are passed the length of the file, delte the extra lines
                            if [[ $line_index -ge $default_line_count ]]; then
                                [ "$verbose_enabled" = true ] && echo $'\t\t'"[---] Current line is past the length of default file, deleting line."
                                sed -i '$ d' $other_config
                                continue
                            else
                                [ "$verbose_enabled" = true ] && echo $'\t\t'"[+++] Inserting newline from default into file"
                                insert_index=$((other_index + 1))
                                sed -i "${insert_index}  i\\"$'\n'"" $other_config
                                continue
                            fi
                        fi

                        matching_line_in_other=$(grep "$stripped_default_line" "$other_config")

                        if [ -n "$matching_line_in_other" ]; then
                            
                            # remove line

                            matching_line_in_default=$(grep "$stripped_other_line" "$default_config")
                            
                            # if not in default, remove it
                            if [ ! -n "$matching_line_in_default" ]; then
                                [ "$verbose_enabled" = true ] && echo $'\t\t'"[---] The param '$stripped_other_line' was found in '$other_config' but not in default, removing it."
                                other_index_d=$((other_index + 1))"d"
                                sed -i $other_index_d $other_config
                            
                            # if it is in default, but in wrong place, remove the line with 
                            else
                                [ "$verbose_enabled" = true ] && echo $'\t\t'"The param '$stripped_default_line' was found in '$other_config' on a different line, moving it"
                                # delete found line in wrong place
                                sed -i "/$matching_line_in_other/d" $other_config
                                
                                # insert same line back
                                insert_index=$((other_index + 1))
                                sed -i "$insert_index i $matching_line_in_other" $other_config

                            fi
                        else
                            [ "$verbose_enabled" = true ] && echo $'\t\t'"The param '$stripped_default_line' exists in the default but was not found in '$other_config'."
                            
                            # to get the line into the same place as the default, 
                            # we need to add the other_index, 
                            # plus 1 to get to the line below
                            # plus however many lines we added above it
                            insert_index=$((other_index + 1))
                            
                            # get a new line count to see if we are past the end of the other file
                            other_line_count=$(wc -l < "$other_config")

                            if [[ $insert_index -gt $other_line_count ]]; then
                                
                                [ "$verbose_enabled" = true ] && echo $'\t\t'"[+++] Adding line from default to end of file"

                                prev_default_line=${default_lines[default_index -1]}

                                if [[ $prev_default_line == "" ]]; then

                                    echo $'\n'$default_line >> $other_config
                                else
                                    echo $default_line >> $other_config
                                fi

                            else
                                [ "$verbose_enabled" = true ] && echo $'\t\t'"[+++] Inserting line from default into file"
                                sed -i "$insert_index i $default_line" $other_config
                            fi                        
                        fi
                    else
                            [ "$verbose_enabled" = true ] && echo $'\t[OOO] Config Lines Match: '$default_line
                            ((line_index+=1))
                    fi

                done

                echo
                echo "FINISHED CHECKING CONFIG: $other_config_basename"
            fi
            
        done

    else
        echo "Error: default config not found in $config_folder."
    fi

}

echo 
echo "----------------- CHECKING SITE CONFIG -----------------"

check_configs $site_config_folder $default_site_config

echo
echo "----------- FINISHED CHECKING ALL SITE CONFIG ----------"

echo 
echo "--------------- CHECKING SCENARIO CONFIG ---------------"

check_configs $scenario_config_folder $default_scenario_config

echo
echo "----------- FINISHED CHECKING ALL SITE CONFIG ----------"

