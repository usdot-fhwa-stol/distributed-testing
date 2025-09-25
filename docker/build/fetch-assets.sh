#!/usr/bin/env bash
set -euo pipefail

# Usage: ./fetch-assets.sh [path/to/env]
ENV_FILE="${1:-./build-assets.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "env file not found: $ENV_FILE" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

if [[ -z "${BUILD_DIR:-}" ]]; then
  echo "BUILD_DIR not set in env file" >&2
  exit 1
fi

# ensure gdown is available
if ! command -v gdown >/dev/null 2>&1; then
  echo "gdown not found. Installing with pip3..."
  if ! command -v pip3 >/dev/null 2>&1; then
    echo "pip3 is not installed. Please install Python3 + pip3 first." >&2
    exit 1
  fi
  pip3 install --user gdown
  export PATH="$HOME/.local/bin:$PATH"
fi

mkdir -p "$BUILD_DIR"

download_one() {
  local key="$1"
  local glob_var="${key}_GLOB"
  local id_var="${key}_ID"
  local out_var="${key}_OUT"   # optional explicit output name

  # indirect expansion
  local pattern="${!glob_var:-}"
  local id="${!id_var:-}"
  local out="${!out_var:-}"

  if [[ -z "$pattern" || -z "$id" ]]; then
    echo "skipping $key  missing ${glob_var} or ${id_var} in env" >&2
    return
  fi

  # expand glob inside BUILD_DIR
  shopt -s nullglob
  # NOTE: unquoted $pattern is intentional to allow glob expansion
  # shellcheck disable=SC2086
  local matches=( $BUILD_DIR/$pattern )
  shopt -u nullglob

  if (( ${#matches[@]} > 0 )); then
    echo "? $key: found ${#matches[@]} file(s) matching '$pattern'; skipping download"
    return
  fi

  echo "? $key: no files matching '$pattern' in $BUILD_DIR; downloading"
  if [[ -n "$out" ]]; then
    # save under a specific name
    gdown "$id" -O "$BUILD_DIR/$out"
  else
    # let Drive/original filename decide; download into BUILD_DIR
    (
      cd "$BUILD_DIR"
      gdown "$id"
    )
  fi
  echo "? $key: download complete"
}

for key in ${ASSETS:-}; do
  download_one "$key"
done

echo "all done. files in: $BUILD_DIR"
