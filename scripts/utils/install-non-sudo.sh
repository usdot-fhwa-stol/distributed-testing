#!/bin/bash

set -e

echo "Installing Distributed Testing software (non-root)..."

# Get the directory of the script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DT_SCRIPT="$SCRIPT_DIR/dt"
DT_AUTOCOMPLETE="$SCRIPT_DIR/__dt_autocomplete"

VUG_LOCAL_DT_PATH=$(echo "$SCRIPT_DIR" | sed -E 's|(/distributed-testing).*|\1|')

# User-local installation directories
INSTALL_BIN="$HOME/.local/bin"
COMPLETION_DIR="$HOME/.local/share/bash-completion/completions"

# Ensure required files exist
if [[ ! -f "$DT_SCRIPT" || ! -f "$DT_AUTOCOMPLETE" ]]; then
    echo "Error: Required files dt or __dt_autocomplete not found in $SCRIPT_DIR"
    exit 1
fi

# Create installation directories
mkdir -p "$INSTALL_BIN"
mkdir -p "$COMPLETION_DIR"

# Check for existing dt installation
if [[ -f "$INSTALL_BIN/dt" ]]; then
    if grep -qi "distributed testing" "$INSTALL_BIN/dt"; then
        echo "A previous version of the Distributed Testing script was found."
        read -r -p "Would you like to overwrite it? [y/N] " confirm

        if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
            echo "Installation aborted."
            exit 1
        fi
    else
        echo "Another application is using the name 'dt' in $INSTALL_BIN."
        echo "Please remove it manually before installing this script."
        exit 1
    fi
fi

# Install dt script
cp "$DT_SCRIPT" "$INSTALL_BIN/dt"
chmod u+x "$INSTALL_BIN/dt"

# Install autocomplete
cp "$DT_AUTOCOMPLETE" "$COMPLETION_DIR/dt"
chmod u+x "$COMPLETION_DIR/dt"

# Configure PATH if necessary
if [[ ":$PATH:" != *":$INSTALL_BIN:"* ]]; then
    echo "Adding $INSTALL_BIN to PATH..."

    if ! grep -qF 'export PATH="$HOME/.local/bin:$PATH"' "$HOME/.bashrc"; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
    fi

    export PATH="$INSTALL_BIN:$PATH"
fi

# Enable autocomplete for current session
if command -v complete >/dev/null 2>&1; then
    complete -r dt 2>/dev/null || true

    if [[ -f "$COMPLETION_DIR/dt" ]]; then
        source "$COMPLETION_DIR/dt"
    fi
fi

# Remove old configuration from previous versions
old_config_found=0

# Check for source lines
grep -q 'source ~/.voices_site_config' "$HOME/.bashrc" 2>/dev/null && old_config_found=1
grep -q 'source ~/.voices_scenario_config' "$HOME/.bashrc" 2>/dev/null && old_config_found=1

# Check for files
[[ -f "$HOME/.voices_site_config" ]] && old_config_found=1
[[ -f "$HOME/.voices_scenario_config" ]] && old_config_found=1

if [[ $old_config_found -eq 1 ]]; then
    echo "Old Distributed Testing configuration detected."

    read -r -p "Do you want to remove the old configuration? (y/n): " yn

    if [[ "$yn" =~ ^[Yy] ]]; then
        sed -i '/source ~\/\.voices_site_config/d' "$HOME/.bashrc"
        sed -i '/source ~\/\.voices_scenario_config/d' "$HOME/.bashrc"

        rm -f "$HOME/.voices_site_config" "$HOME/.voices_scenario_config"

        echo "Old configuration removed."
    else
        echo "Nothing removed."
    fi
fi

# Initialize Distributed Testing
dt init "$VUG_LOCAL_DT_PATH"

# Create logs directory
mkdir -p "$VUG_LOCAL_DT_PATH/logs"

echo "Setting permissions for log directory"

# Ensure current user owns the logs directory
chmod -R u+rwX "$VUG_LOCAL_DT_PATH/logs"

echo "Installation complete."
echo ""
echo "Installed dt to: $INSTALL_BIN/dt"
echo "Autocomplete installed to: $COMPLETION_DIR/dt"
echo ""
echo "If autocomplete or PATH is not available, restart your terminal."
