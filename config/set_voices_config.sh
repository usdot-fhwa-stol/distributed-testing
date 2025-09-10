#!/bin/bash

# Get the directory of the script, no matter where it's called from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Parse optional --site and --scenario arguments
site_arg=""
scenario_arg=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --site)
            if [[ -n "$2" && "$2" != --* ]]; then
                site_arg="$2"
                shift 2
            else
                echo "Error: --site requires a filename argument."
                exit 1
            fi
            ;;
        --scenario)
            if [[ -n "$2" && "$2" != --* ]]; then
                scenario_arg="$2"
                shift 2
            else
                echo "Error: --scenario requires a filename argument."
                exit 1
            fi
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--site site_config_file] [--scenario scenario_config_file]"
            exit 1
            ;;
    esac
done

# -------------------
# SITE CONFIG SECTION
# -------------------

cd site_config || exit 1

if [[ -n "$site_arg" ]]; then
    if [[ -f "$site_arg" ]]; then
        site_config_path=$(readlink -f "$site_arg")
    else
        echo "Provided site config file '$site_arg' not found."
        exit 1
    fi
else
    echo
    echo "Set your desired site config from the list below:"
    echo
    {
        ls ./*.config | xargs -n 1 basename
    } || {
        echo
        echo "No config files found in directory"
        exit 1
    }

    while true; do
        echo ""
        read -rep "-->: " site_config_file
        if [[ ! -f ./$site_config_file ]]; then
            echo "    File not found!"
        else
            site_config_path=$(readlink -f ./$site_config_file)
            break
        fi
    done
fi

ln -sf "$site_config_path" "$HOME/.dt_site_config"
source "$HOME/.dt_site_config"

# ------------------------
# SCENARIO CONFIG SECTION
# ------------------------

cd ../scenario_config || exit 1

if [[ -n "$scenario_arg" ]]; then
    if [[ -f "$scenario_arg" ]]; then
        scenario_config_path=$(readlink -f "$scenario_arg")
    else
        echo "Provided scenario config file '$scenario_arg' not found."
        exit 1
    fi
else
    echo
    echo "Set your desired scenario config from the list below:"
    echo
    {
        ls ./*.config | xargs -n 1 basename
    } || {
        echo
        echo "No scenario config files found in directory"
        exit 1
    }

    while true; do
        echo ""
        read -rep "-->: " scenario_config_file
        if [[ ! -f ./$scenario_config_file ]]; then
            echo "    File not found!"
        else
            scenario_config_path=$(readlink -f ./$scenario_config_file)
            break
        fi
    done
fi

ln -sf "$scenario_config_path" "$HOME/.dt_scenario_config"
source "$HOME/.dt_scenario_config"

# Clean up deprecated symlink if present
rm -f "$HOME/.voices_config"

# ---------------------
# Add sourcing to .bashrc
# ---------------------

if grep -qx "source ~/.dt_site_config" ~/.bashrc; then
    echo "Source site config command already exists in .bashrc"
else
    echo "Adding site config source command to .bashrc"
    echo "source ~/.dt_site_config" >> ~/.bashrc
fi

if grep -qx "source ~/.dt_scenario_config" ~/.bashrc; then
    echo "Source scenario config command already exists in .bashrc"
else
    echo "Adding scenario config source command to .bashrc"
    echo "source ~/.dt_scenario_config" >> ~/.bashrc
fi

echo
echo "Config successfully set. Please close and reopen the terminal or run:"
echo "    source ~/.bashrc"
