#!/usr/bin/env bash

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTS_REF="${CARLA_AGENTS_REF:-ue5-dev}"      
THIRD_PARTY="/tmp/carla-erv-ego/third_party"
AGENTS_PARENT="$THIRD_PARTY/PythonAPI/carla"
PIP_PKGS=(pyyaml opencv-python-headless)

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32mok\033[0m  %s\n' "$*"; }
warn() { printf '  \033[33mwarn\033[0m %s\n' "$*"; }
die()  { printf '  \033[31mFAIL\033[0m %s\n' "$*" >&2; exit 1; }

say "Installing Python packages: ${PIP_PKGS[*]}"
if ! python3 -m pip install --user --upgrade "${PIP_PKGS[@]}" 2>/tmp/erv_ego_pip.err; then
    if grep -q "externally-managed-environment" /tmp/erv_ego_pip.err; then
        warn "system Python is externally managed: retrying with --break-system-packages"
        python3 -m pip install --user --break-system-packages --upgrade "${PIP_PKGS[@]}" \
            || die "pip install failed"
    else
        cat /tmp/erv_ego_pip.err >&2
        die "pip install failed"
    fi
fi
ok "packages installed"

say "Fetching CARLA agents ($AGENTS_REF)"
if [ -f "$AGENTS_PARENT/agents/navigation/global_route_planner.py" ]; then
    ok "already present in $AGENTS_PARENT/agents (delete third_party/ to refetch)"
else
    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT
    git clone --quiet --depth 1 --branch "$AGENTS_REF" --filter=blob:none --sparse \
        https://github.com/carla-simulator/carla.git "$TMP/carla" \
        || die "git clone failed (no network, or ref '$AGENTS_REF' does not exist)"
    git -C "$TMP/carla" sparse-checkout set PythonAPI/carla/agents
    mkdir -p "$AGENTS_PARENT"
    rm -rf "$AGENTS_PARENT/agents"
    cp -r "$TMP/carla/PythonAPI/carla/agents" "$AGENTS_PARENT/agents"
    ok "copied to $AGENTS_PARENT/agents"
fi

say "Registering agents on Python's path"
USER_SITE="$(python3 -m site --user-site)"
mkdir -p "$USER_SITE"
echo "$AGENTS_PARENT" > "$USER_SITE/erv_ego_agents.pth"
ok "$USER_SITE/erv_ego_agents.pth -> $AGENTS_PARENT"

say "Verifying"
python3 - <<'PY' || die "an import failed: see above"
import importlib
bad = 0
for mod, label in [("yaml", "pyyaml"), ("cv2", "opencv"),
                   ("agents.navigation.global_route_planner", "CARLA agents (GRP)"),
                   ("agents.navigation.basic_agent", "CARLA agents (BasicAgent)")]:
    try:
        importlib.import_module(mod)
        print("  \033[32mok\033[0m  %s" % label)
    except Exception as e:
        bad += 1
        print("  \033[31mFAIL\033[0m %s: %s" % (label, e))
raise SystemExit(1 if bad else 0)
PY

say "Done"
echo "Run from $REPO_DIR, e.g.:"
echo "  python3 dt/dt_event3_ego.py --role VW-M-1 --erv-role PATH-M-1 --spawn-only"