#!/usr/bin/env bash
# postinst baked dt-build-general's own /home/dt_user path into TENA's scripts (e.g. tenaenv.sh
# hardcodes and re-exports TENA_HOME="/home/dt_user/TENA" regardless of what's already set) --
# repoint them so TENA_HOME resolves correctly here too, then build TENA against V2X-Hub's SDK.
set -euo pipefail

grep -rlZ '/home/dt_user' "$TENA_HOME" | xargs -0r sed -i 's#/home/dt_user#/home/plugin#g'

export TENA_VERSION="$(ls "$TENA_HOME" | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | head -1)"
./build.sh release --j2735-version "$J2735_VERSION"

ldconfig
