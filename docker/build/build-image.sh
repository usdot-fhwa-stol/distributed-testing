#!/usr/bin/env bash
set -euo pipefail

# Builds a bake target/group whose setup lives in its own subdirectory here (a docker-bake.hcl +
# versions.env, following the dt-v2xhub/ convention: subdirectory name == bake target/group name).
# Usage: ./build-image.sh <target> [extra docker buildx bake args...]
if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <target> [extra docker buildx bake args...]" >&2
  exit 1
fi

TARGET="$1"
shift

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${SCRIPT_DIR}/${TARGET}"

if [[ ! -d "${TARGET_DIR}" ]]; then
  echo "No such build directory: ${TARGET_DIR}" >&2
  exit 1
fi

cd "${TARGET_DIR}"
set -a
source versions.env
set +a
docker buildx bake --allow=fs.read=.. "${TARGET}" "$@"
