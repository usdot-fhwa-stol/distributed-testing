#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Script to build all TENA adapters in numerical order
# This script calls buildTenaAdapters.sh for each application

# ---------------- Configuration ----------------

# Path to the main build script (assumed to be in the same directory)
BUILD_SCRIPT_PATH="$(dirname "$0")/buildTenaAdapters.sh"

# Build Mode: 'release' or 'debug'
BUILD_MODE="release"

# Branch Configuration for each Adapter
# You can modify these variables to change the target branch for each adapter, or
# override them from the environment (e.g. in CI) without editing this file.
# ADAPTER_BRANCH sets the default for every adapter; BRANCH_APP_<n> overrides one.
ADAPTER_BRANCH="${ADAPTER_BRANCH:-event/hass_dt_develop}"

# [1] vug-threads-library
BRANCH_APP_1="${BRANCH_APP_1:develop}"

# [2] vug-udp-protocolio
BRANCH_APP_2="${BRANCH_APP_2:-develop}"

# [3] scenario-publisher
BRANCH_APP_3="${BRANCH_APP_3:-$ADAPTER_BRANCH}"

# [4] vug-carla-adapter
BRANCH_APP_4="${BRANCH_APP_4:-$ADAPTER_BRANCH}"

# [5] tena-v2x-adapter
BRANCH_APP_5="${BRANCH_APP_5:-$ADAPTER_BRANCH}"

# [6] tena-entity-generator
BRANCH_APP_6="${BRANCH_APP_6:-$ADAPTER_BRANCH}"

# [7] v2xhub-tena-v2x-plugin
BRANCH_APP_7="${BRANCH_APP_7:-$ADAPTER_BRANCH}"

# -----------------------------------------------

# Check if build script exists
if [ ! -f "$BUILD_SCRIPT_PATH" ]; then
    echo "Error: Build script not found at $BUILD_SCRIPT_PATH"
    exit 1
fi

# Function to perform the build for a specific index
run_build() {
    local index=$1
    local branch=$2
    local name=$3

    echo "================================================================================"
    echo "Building [$index] $name"
    echo "Branch: $branch | Mode: $BUILD_MODE"
    echo "================================================================================"

    "$BUILD_SCRIPT_PATH" --app_index "$index" --branch "$branch" --"$BUILD_MODE" --auto_download
    echo ""
}

# Execute builds in order
run_build 1 "$BRANCH_APP_1" "vug-threads-library"
run_build 2 "$BRANCH_APP_2" "vug-udp-protocolio"
run_build 3 "$BRANCH_APP_3" "scenario-publisher"
run_build 4 "$BRANCH_APP_4" "vug-carla-adapter"
run_build 5 "$BRANCH_APP_5" "tena-v2x-adapter"
run_build 6 "$BRANCH_APP_6" "tena-entity-generator"
# run_build 7 "$BRANCH_APP_7" "v2xhub-tena-v2x-plugin"

echo "================================================================================"
echo "All adapters built successfully!"
echo "================================================================================"
