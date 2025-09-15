#!/bin/bash

echo "Installing Distributed Testing software..."

# Get the directory of the script, no matter where it's called from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DT_SCRIPT="$SCRIPT_DIR/dt"
DT_AUTOCOMPLETE="$SCRIPT_DIR/__dt_autocomplete"

VUG_LOCAL_DT_PATH=$(echo "$SCRIPT_DIR" | sed -E 's|(/distributed-testing).*|\1|')

# Ensure required files exist
if [[ ! -f "$DT_SCRIPT" || ! -f "$DT_AUTOCOMPLETE" ]]; then
    echo "Error: Required files dt or __dt_autocomplete not found in $SCRIPT_DIR"
    exit 1
fi

# Check for existing dt in /usr/bin
if [[ -f /usr/bin/dt ]]; then
    if grep -qi "distributed testing" /usr/bin/dt; then
        echo "A previous version of the Distributed Testing script was found."
        read -p "Would you like to overwrite it? [y/N] " confirm
        if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
            echo "Installation aborted."
            exit 1
        fi
    else
        echo "Another application is using the name 'dt' in /usr/bin."
        echo "Please remove it manually before installing this script."
        exit 1
    fi
fi

# Install dt script
sudo cp "$DT_SCRIPT" /usr/bin/dt
sudo chmod ugo+x /usr/bin/dt

# Install autocomplete
sudo cp "$DT_AUTOCOMPLETE" /etc/bash_completion.d/__dt_autocomplete
sudo chmod ugo+x /etc/bash_completion.d/__dt_autocomplete

dt init $VUG_LOCAL_DT_PATH

# Create logs directory 

mkdir -p $VUG_LOCAL_DT_PATH/logs

echo "Setting permissions for log directory"

sudo chmod -R a+rw $VUG_LOCAL_DT_PATH/logs

echo "Installation complete. You may need to restart your terminal for autocomplete to take effect."
