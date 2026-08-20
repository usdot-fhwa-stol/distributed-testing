#!/usr/bin/env bash
# V2X-Hub's own plugins come prebuilt from dt-v2xhub, so drop v2i-hub to avoid building them twice,
# then create the plugin user that TENA_HOME needs to live under.
set -euo pipefail

sed -i '/add_subdirectory(v2i-hub)/d' CMakeLists.txt

/home/V2X-Hub/container/database.sh
/home/V2X-Hub/container/library.sh
ldconfig
