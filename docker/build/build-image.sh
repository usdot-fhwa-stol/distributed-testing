#!/usr/bin/env bash

# Unified build script for the dt-*_Dockerfile images in this directory.
# Wraps the differing `docker build` invocations documented at the top of
# each dt-*_Dockerfile (build-context assets, secrets, tag naming) behind one
# consistent interface.
#
# Usage: ./build-image.sh <image> -v VERSION [options]
#
#   <image>            One of: base, build-general, build-carla, core, v2xhub, carla, carla-0-9-15, simdis
#   -v, --version      Image version tag (required)
#   --plugin-branch    v2xhub only: vug-v2xhub-v2x-plugin branch to build (default develop)
#   --target           Dockerfile stage to build, e.g. v2xhub's "base" (plugin not baked in,
#                       always builds - use for a devcontainer) vs "runtime" (default; the
#                       full deployable image, requires the plugin to build cleanly)
#   --tag-latest       Also tag the image as :latest
#   -h, --help         Show this help
#
# Environment variables:
#   DOCKER_ORG   Harbor org/project the built image is tagged under, and that
#                base-image FROM lines pull dt-* images from, e.g.
#                "distributed-testing" (default) or "distributed-testing-dev"
#   DOCKER_TAG   Tag to pull dt-* base images at, e.g. "latest" (default) or "0.0.1"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

REGISTRY_HOST="harbor.distributedtesting.org"
DOCKER_ORG="${DOCKER_ORG:-distributed-testing}"
DOCKER_TAG="${DOCKER_TAG:-latest}"
ORG_TOKEN="${ORG_TOKEN:-}"
REGISTRY="${REGISTRY_HOST}/${DOCKER_ORG}"
TOKEN_FILE="usdotfhwastol_token"
ASSETS_ENV="build-assets.env"

declare -A DOCKERFILE=(
      [base]="dt-base_Dockerfile"
      [build-general]="dt-build-general_Dockerfile"
      [build-carla]="dt-build-carla_Dockerfile"
      [core]="dt-core_Dockerfile"
      [v2xhub]="dt-v2xhub_Dockerfile"
      [carla]="dt-carla_Dockerfile"
      [carla-0-9-15]="dt-carla-0-9-15_Dockerfile"
      [simdis]="dt-simdis_Dockerfile"
)

# Harbor repo name each image key publishes under (carla-0-9-15 shares dt-carla,
# distinguished by tag prefix below)
declare -A IMAGE_NAME=(
      [base]="dt-base"
      [build-general]="dt-build-general"
      [build-carla]="dt-build-carla"
      [core]="dt-core"
      [v2xhub]="dt-v2xhub"
      [carla]="dt-carla"
      [carla-0-9-15]="dt-carla"
      [simdis]="dt-simdis"
)

declare -A TAG_PREFIX=(
      [carla-0-9-15]="0-9-15-"
)

# Images whose Dockerfile mounts the shared "assets" build-context (populated
# via build-assets.env + fetch-assets.sh)
declare -A NEEDS_ASSETS=(
      [base]=1
      [core]=1
      [v2xhub]=1
      [simdis]=1
)

# Images whose assets come from an env file other than the default build-assets.env
declare -A ASSETS_ENV_FILE=(
      [simdis]="build-assets_simdis.env"
)

# Images whose Dockerfile mounts the usdotfhwastol_token secret
declare -A NEEDS_SECRET=(
      [build-general]=1
      [v2xhub]=1
)

# Images whose Dockerfile FROMs another dt-* image via ARG DOCKER_ORG/DOCKER_TAG
declare -A USES_ORG_TAG=(
      [build-general]=1
      [build-carla]=1
      [core]=1
      [v2xhub]=1
)

usage() {
      echo "Usage: $0 <image> -v VERSION [options]"
      echo
      echo "  image            one of: ${!DOCKERFILE[*]}"
      echo "  -v, --version    image version tag (required)"
      echo "  --plugin-branch  v2xhub only: vug-v2xhub-v2x-plugin branch to build (default develop)"
      echo "  --target         Dockerfile stage to build, e.g. v2xhub's 'base' vs 'runtime' (default)"
      echo "  --tag-latest     also tag the image as :latest"
      echo "  -h, --help       show this help"
      exit 1
}

if [[ $# -eq 0 ]]; then
      usage
fi

IMAGE="$1"
shift

VERSION=""
PLUGIN_BRANCH="develop"
TARGET=""
TAG_LATEST=0

while [[ $# -gt 0 ]]; do
      arg="$1"
      case $arg in
            -v|--version)
                  VERSION="$2"
                  shift
                  shift
            ;;
            --plugin-branch)
                  PLUGIN_BRANCH="$2"
                  shift
                  shift
            ;;
            --target)
                  TARGET="$2"
                  shift
                  shift
            ;;
            --tag-latest)
                  TAG_LATEST=1
                  shift
            ;;
            -h|--help)
                  usage
            ;;
            *)
                  echo "Unknown argument: $1" >&2
                  usage
            ;;
      esac
done

if [[ -z "${DOCKERFILE[$IMAGE]:-}" ]]; then
      echo "Unknown image '$IMAGE'. Must be one of: ${!DOCKERFILE[*]}" >&2
      exit 1
fi

if [[ -z "$VERSION" ]]; then
      echo "Missing required -v/--version" >&2
      usage
fi

DOCKERFILE_PATH="${DOCKERFILE[$IMAGE]}"
TAG="${TAG_PREFIX[$IMAGE]:-}${VERSION}${TARGET:+-$TARGET}"
FULL_TAG="${REGISTRY}/${IMAGE_NAME[$IMAGE]}:${TAG}"

BUILD_ARGS=(--build-arg "VERSION=${VERSION}")
EXTRA_ARGS=()

if [[ -n "$TARGET" ]]; then
      EXTRA_ARGS+=(--target "$TARGET")
fi

if [[ "${NEEDS_ASSETS[$IMAGE]:-0}" -eq 1 ]]; then
      ASSETS_ENV="${ASSETS_ENV_FILE[$IMAGE]:-$ASSETS_ENV}"
      # shellcheck disable=SC1090
      source "$ASSETS_ENV"
      if [[ -z "${BUILD_DIR:-}" ]]; then
            echo "BUILD_DIR not set by $ASSETS_ENV" >&2
            exit 1
      fi
      EXTRA_ARGS+=(--build-context "assets=$BUILD_DIR")
fi

if [[ "${NEEDS_SECRET[$IMAGE]:-0}" -eq 1 ]]; then
      if [[ "$IMAGE" == "build-general" ]]; then
            if [[ -z "${USDOTFHWASTOL_TOKEN:-}" ]]; then
                  echo "USDOTFHWASTOL_TOKEN is required for build-general" >&2
                  exit 1
            fi
            EXTRA_ARGS+=(--secret "id=usdotfhwastol_token,env=USDOTFHWASTOL_TOKEN")
      else
            if [[ ! -f "$TOKEN_FILE" ]]; then
                  echo "Missing $TOKEN_FILE - see the secret instructions at the top of dt-v2xhub_Dockerfile" >&2
                  exit 1
            fi
            EXTRA_ARGS+=(--secret "id=usdotfhwastol_token,src=$TOKEN_FILE")
      fi
fi

if [[ "$IMAGE" == "v2xhub" ]]; then
      BUILD_ARGS+=(--build-arg "PLUGIN_BRANCH=${PLUGIN_BRANCH}")
fi

if [[ "${USES_ORG_TAG[$IMAGE]:-0}" -eq 1 ]]; then
      BUILD_ARGS+=(--build-arg "DOCKER_ORG=${DOCKER_ORG}" --build-arg "DOCKER_TAG=${DOCKER_TAG}")
fi

DOCKER_BUILDKIT=1 docker build \
      "${EXTRA_ARGS[@]}" \
      "${BUILD_ARGS[@]}" \
      -t "$FULL_TAG" \
      --progress=plain \
      -f "$DOCKERFILE_PATH" \
      .

if [[ "$TAG_LATEST" -eq 1 ]]; then
      LATEST_TAG="${REGISTRY}/${IMAGE_NAME[$IMAGE]}:latest"
      docker tag "$FULL_TAG" "$LATEST_TAG"
      echo "Tagged $LATEST_TAG"
fi

echo "Built $FULL_TAG"