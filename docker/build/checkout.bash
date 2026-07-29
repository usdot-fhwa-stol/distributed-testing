#!/bin/bash

# Generic checkout script for private usdot-fhwa-stol repos, used by Dockerfiles
# to clone source at build time.
# Requires USDOTFHWASTOL_TOKEN to be exported (private repo, cloned over HTTPS).
#
# Usage: checkout.bash <repo> [-b branch] [-r root]
#   <repo>  Required. Repo name under github.com/usdot-fhwa-stol, e.g. vug-v2xhub-v2x-plugin
#   -b/--branch  Branch to clone, default 'develop'
#   -r/--root    Directory to clone into (must be empty/nonexistent), default is the current directory

set -exo pipefail

REPO=""
dir="$(pwd)"
BRANCH="develop"
while [[ $# -gt 0 ]]; do
      arg="$1"
      case $arg in
            -b|--branch)
                  BRANCH=$2
                  shift
                  shift
            ;;
            -r|--root)
                  dir=$2
                  shift
                  shift
            ;;
            *)
                  REPO=$1
                  shift
            ;;
      esac
done

if [[ -z "${REPO}" ]]; then
      echo "Usage: checkout.bash <repo> [-b branch] [-r root]"
      exit 1
fi

mkdir -p "${dir}"
cd "${dir}"

# Cloned directly into "${dir}" rather than a named subdirectory, since callers
# (e.g. the TENA V2X Plugin's own build.sh) may hardcode their source root.
git clone --depth=1 --branch "${BRANCH}" \
      "https://${USDOTFHWASTOL_TOKEN}@github.com/usdot-fhwa-stol/${REPO}.git" \
      .
