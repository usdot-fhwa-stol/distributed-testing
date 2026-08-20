#!/usr/bin/env bash
set -euo pipefail

TENA_VERSION="$(ls "$TENA_HOME" | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | head -1)" cmake -Bbuild -D CMAKE_BUILD_TYPE=RELEASE \
  -D "CMAKE_PREFIX_PATH=${TENA_HOME}/lib/cmake;/usr/local/plugins/;/opt/carma/cmake;/opt/carma/lib" \
  -D CMAKE_MODULE_PATH=/opt/carma/cmake \
  -D VUG_INSTALL_DIR=/usr/local/plugins/ \
  -D tmx-plugin_DIR=/usr/local/share/tmx/ .

cmake --build build -j"$(nproc)"
