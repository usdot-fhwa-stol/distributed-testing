#!/usr/bin/env bash
set -euo pipefail

# Usage: VERSION=my-tag ./build-image.sh dt-v2xhub
#   VERSION tags the built image (harbor.distributedtesting.org/distributed-testing/dt-v2xhub:VERSION);
#   defaults to docker-bake.hcl's own default ("develop") if not set. versions.env doesn't define
#   VERSION, so an exported VERSION here passes straight through to bake unmodified.
if [[ $# -lt 1 ]]; then
  echo "Usage: VERSION=my-tag $0 dt-v2xhub" >&2
  exit 1
fi

TARGET="$1"
shift

if [[ "${TARGET}" != "dt-v2xhub" ]]; then
  echo "Only the dt-v2xhub target is supported for now, got: ${TARGET}" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${SCRIPT_DIR}/${TARGET}"

if [[ ! -d "${TARGET_DIR}" ]]; then
  echo "No such build directory: ${TARGET_DIR}" >&2
  exit 1
fi

# This piece of logic will be changing once automated dockerhub is implemented
source dt-v2xhub/versions.env
docker pull "harbor.distributedtesting.org/distributed-testing-dev/dt-build-general:${DT_BUILD_GENERAL_TAG}"

cd "${TARGET_DIR}"
set -a
source versions.env
set +a
docker buildx bake --allow=fs.read=.. "${TARGET}" "$@"
