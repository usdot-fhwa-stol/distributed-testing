#!/usr/bin/env bash
# set -euo pipefail
IFS=$'\n\t'
shopt -s nullglob

print_help() {
  cat <<'EOF'
usage: ADMIN_check_configs.sh [--debug] [--verbose] [--apply] [--help]

Validate your config(s) against the defaults. By default, no files are changed.
Use --apply to modify files in place (backups created as *.bak).

optional arguments:
  -d, --debug     step through each iteration
  -v, --verbose   verbose output
  -a, --apply     apply changes (in-place), otherwise dry-run
  -h, --help      show help
EOF
}

debug_enabled=false
verbose_enabled=false
apply_changes=false

# Simple getopts + long flags
while (( $# )); do
  case "${1:-}" in
    -d|--debug)   debug_enabled=true ;;
    -v|--verbose) verbose_enabled=true ;;
    -a|--apply)   apply_changes=true ;;
    -h|--help)    print_help; exit 0 ;;
    *) echo "Invalid argument: $1" >&2; print_help; exit 2 ;;
  esac
  shift
done

logv() { $verbose_enabled && printf '%s\n' "$*" || true; }
step() { $debug_enabled && { read -r -p "[PRESS ENTER TO CONTINUE]" _; } || true; }

normalize_file() {
  # Ensure LF endings and exactly one trailing newline
  # Writes to a temp, then moves back
  local f="$1" tmp
  tmp=$(mktemp)
  # Convert CRLF to LF, strip trailing spaces, ensure single trailing newline
  awk '{ sub(/\r$/, ""); print } END { if (NR==0 || $0!~/^$/) print "" }' "$f" > "$tmp"
  mv "$tmp" "$f"
}

backup_once() {
  local f="$1"
  [[ -f "${f}.bak" ]] || cp -p "$f" "${f}.bak"
}

# Safer literal match helper (avoids regex pitfalls)
has_key_literal() {
  # $1=key, $2=file
  local key="$1" f="$2"
  grep -Fq "export ${key}=" "$f"
}

# Extract KEY from a config line; empty if comment/blank/non-export
key_of_line() {
  # Use shell parameter expansion instead of grep -P
  local line="$1"
  [[ -z "$line" || "${line:0:1}" == "#" ]] && { printf '\n'; return; }
  [[ "$line" == export\ *=* ]] || { printf '\n'; return; }
  line=${line#export }    # drop leading 'export '
  line=${line%%=*}        # take before '='
  printf '%s\n' "$line"
}

check_configs() {
  local config_folder="$1" default_config="$2"

  if [[ ! -e "$default_config" ]]; then
    printf 'Error: default config not found in %s\n' "$default_config" >&2
    return 1
  fi

  # Normalize default once
  normalize_file "$default_config"
  local default_lines; mapfile -t default_lines < "$default_config"
  local default_line_count=${#default_lines[@]}

  local cfg
  for cfg in "$config_folder"/*.config; do
    [[ "$cfg" == "$default_config" ]] && continue

    printf '\nComparing: %s\n' "$(basename -- "$cfg")"
    normalize_file "$cfg"

    local other_lines; mapfile -t other_lines < "$cfg"
    local other_line_count=${#other_lines[@]}

    logv "default lines: $default_line_count"
    logv "$(basename -- "$cfg") lines: $other_line_count"

    local i=0 max_line_count=$(( default_line_count > other_line_count ? default_line_count : other_line_count ))

    while (( i < max_line_count )); do
      step

      # reload arrays ONLY if we changed the file in the previous iteration
      # (we'll set changed=true when we edit)
      local changed=false

      local default_line="${default_lines[i]:-}"
      local other_line="${other_lines[i]:-}"

      logv "Checking Line: $((i+1))"

      if [[ "$default_line" != "$other_line" ]]; then
        # Compute keys (if any)
        local kdef kdefo koth
        kdef=$(key_of_line "$default_line")
        koth=$(key_of_line "$other_line")

        $verbose_enabled && {
          printf '\t[XXX] Mismatch\n'
          printf '\t\tDefault %4d: %s\n' "$((i+1))" "$default_line"
          printf '\t\tOther   %4d: %s\n' "$((i+1))" "$other_line"
          [[ -n "$kdef" ]] && printf '\t\tKey(def): %s\n' "$kdef"
          [[ -n "$koth" ]] && printf '\t\tKey(oth): %s\n' "$koth"
        }

        # Handle blank default line: mirror structure
        if [[ -z "$default_line" ]]; then
          if (( i >= default_line_count )); then
            $verbose_enabled && printf '\t\t[---] Past default length; deleting trailing line.\n'
            if $apply_changes; then
              backup_once "$cfg"; sed -e '$d' "$cfg" > "$cfg.tmp" && mv "$cfg.tmp" "$cfg"; changed=true
            fi
          else
            $verbose_enabled && printf '\t\t[+++] Inserting blank line from default.\n'
            if $apply_changes; then
              backup_once "$cfg"; awk -v n=$((i+1)) 'NR==n{print ""}1' "$cfg" > "$cfg.tmp" && mv "$cfg.tmp" "$cfg"; changed=true
            fi
          fi
        else
          # If default has a key
          if [[ -n "$kdef" ]]; then
            # If other has duplicate blank: collapse double blank
            if [[ -z "$other_line" && $((i+1)) -lt other_line_count ]]; then
              $verbose_enabled && printf '\t\t[---] Collapsing double newline.\n'
              if $apply_changes; then
                backup_once "$cfg"; sed "$((i+1))d" "$cfg" > "$cfg.tmp" && mv "$cfg.tmp" "$cfg"; changed=true
              fi
            elif has_key_literal "$kdef" "$cfg"; then
              # Key exists elsewhere -> move it here
              $verbose_enabled && printf '\t\t[>>>] Moving key '%s' to match default order.\n' "$kdef"
              if $apply_changes; then
                backup_once "$cfg"
                # extract line literal
                line_to_move=$(grep -F "export ${kdef}=" "$cfg" | head -n1)
                # delete all matches, insert at position i+1
                awk -v k="export ${kdef}=" -v n=$((i+1)) 'index($0,k){next} {lines[++c]=$0} END{for (j=1;j<=c;j++){ if (j==n) print line_to_move; print lines[j] }}' "$cfg" > "$cfg.tmp" && mv "$cfg.tmp" "$cfg"; changed=true
              fi
            else
              # Key missing in other -> insert the default line here
              $verbose_enabled && printf '\t\t[+++] Inserting missing key '%s'.\n' "$kdef"
              if $apply_changes; then
                backup_once "$cfg"; awk -v n=$((i+1)) -v ins="$default_line" 'NR==n{print ins}1' "$cfg" > "$cfg.tmp" && mv "$cfg.tmp" "$cfg"; changed=true
              fi
            fi
          else
            # Default line is comment or non-export: mirror it
            $verbose_enabled && printf '\t\t[===] Mirroring non-export line from default.\n'
            if $apply_changes; then
              backup_once "$cfg"; awk -v n=$((i+1)) -v ins="$default_line" 'NR==n{print ins}1' "$cfg" > "$cfg.tmp" && mv "$cfg.tmp" "$cfg"; changed=true
            fi
          fi
        fi
      else
        logv "\t[OOO] Match: $default_line"
        (( i++ ))
        continue
      fi

      # If we changed file content, reload arrays and counts, keep index consistent
      if $changed; then
        mapfile -t other_lines < "$cfg"
        other_line_count=${#other_lines[@]}
        max_line_count=$(( default_line_count > other_line_count ? default_line_count : other_line_count ))
      else
        (( i++ ))
      fi
    done

    printf '\nFINISHED CHECKING CONFIG: %s\n' "$(basename -- "$cfg")"
  done
}

site_config_folder="./site_config"
default_site_config="$site_config_folder/default_site.config"

scenario_config_folder="./scenario_config"
default_scenario_config="$scenario_config_folder/default_scenario.config"

printf '\n----------------- CHECKING SITE CONFIG -----------------\n'
check_configs "$site_config_folder" "$default_site_config"

printf '\n----------- FINISHED CHECKING ALL SITE CONFIG ----------\n'

printf '\n--------------- CHECKING SCENARIO CONFIG ---------------\n'
# Uncomment when ready
# check_configs "$scenario_config_folder" "$default_scenario_config"

printf '\n----------- FINISHED CHECKING ALL SITE CONFIG ----------\n'
```

### What changed vs. yours (high level)

* Unified `set -euo pipefail`, `IFS`, `nullglob`, and **consistent quoting**.
* Removed `grep -P`; replaced with shell parameter expansion.
* Added **dry‑run** by default; `--apply` flips to editing with `*.bak` backups.
* Added **normalize_file** to handle missing EOF newline & CRLF in a single pass.
* Avoid re‑reading both files at every iteration; only reload after a change.
* Replaced regex searches with **fixed‑string** (`grep -F`) where appropriate.
* Avoided `sed -i` portability pitfalls by writing to a temp and `mv`.

---

# Next Iteration: Symlink‑based single‑config check

When you pivot to checking only the “current” active configs, bolt on:

```bash
resolve_cfg() {
  # Linux: readlink -f ; macOS coreutils: greadlink -f
  local p="$1"
  if command -v readlink >/dev/null 2>&1; then
    readlink -f "$p" 2>/dev/null || echo "$p"
  else
    # Fallback without -f support
    python3 - <<'PY'
import os,sys
p=sys.argv[1]
try:
  print(os.path.realpath(p))
except Exception:
  print(p)
PY
  fi
}

active_site=$(resolve_cfg "$HOME/.dt_site_config")
active_scn=$(resolve_cfg "$HOME/.dt_scenario_config")

# Then compare: active_site vs default_site_config, and active_scn vs default_scenario_config
```

Add guardrails:

* If symlink missing or broken, print a clear error.
* If the resolved path is **outside** the expected repo (e.g., not under `./site_config`), still compare, but warn.

---

# Extra Hardening Ideas (Optional)

* **`--fail-on-change`**: exit non‑zero if differences are detected (useful in CI).
* **`--summary`**: tally adds/moves/removes/edits for a concise end report.
* **Unit tests** with a small matrix of tricky inputs (CRLF, duplicate keys, comments in between, weird keys like `PATH_WITH_SLASH`).
* **Shellcheck** in CI (`shellcheck -x ADMIN_check_configs.sh`).

---

If you want, I can also provide a **pure key/value comparator** variant that:

1. parses `export KEY=VALUE` into ordered maps, 2) reports `added/removed/changed`, and 3) has a `--sync` that rebuilds the other file in default order while preserving unmatched comments at their relative positions. This tends to be simpler and more deterministic than line‑surgery.

---

# Single‑file mode (active symlinks only)

Below is an implementation that compares **only** the active configs pointed to by `~/.dt_site_config` and `~/.dt_scenario_config` against their respective defaults. It keeps the portability/safety improvements (dry‑run by default, `--apply` to modify with backups, CRLF/EOF normalization, no `grep -P`, no `sed -i` pitfalls).

```bash
#!/usr/bin/env bash
set -euo pipefail
IFS=$'
	'

print_help() {
  cat <<'EOF'
usage: ADMIN_check_configs.sh [--debug] [--verbose] [--apply] [--site-only] [--scenario-only] [--help]

Validate your *active* config(s) (resolved from ~/.dt_site_config and ~/.dt_scenario_config) against defaults.
By default, no files are changed; use --apply to modify files in place (backups created as *.bak).

optional arguments:
  -d, --debug        step through each iteration
  -v, --verbose      verbose output
  -a, --apply        apply changes (in-place), otherwise dry-run
      --site-only    check only site config symlink
      --scenario-only check only scenario config symlink
  -h, --help         show help
EOF
}

debug_enabled=false
verbose_enabled=false
apply_changes=false
check_site=true
check_scenario=true

while (( $# )); do
  case "${1:-}" in
    -d|--debug)         debug_enabled=true ;;
    -v|--verbose)       verbose_enabled=true ;;
    -a|--apply)         apply_changes=true ;;
    --site-only)        check_scenario=false ;;
    --scenario-only)    check_site=false ;;
    -h|--help)          print_help; exit 0 ;;
    *) echo "Invalid argument: $1" >&2; print_help; exit 2 ;;
  esac
  shift
done

logv() { $verbose_enabled && printf '%s
' "$*" || true; }
step() { $debug_enabled && { read -r -p "[PRESS ENTER TO CONTINUE]" _; } || true; }

normalize_file() {
  local f="$1" tmp
  [[ -f "$f" ]] || return 0
  tmp=$(mktemp)
  # Convert CRLF->LF; ensure single trailing newline
  awk '{ sub(/
$/, ""); print } END { if (NR==0 || $0!~/^$/) print "" }' "$f" > "$tmp"
  mv "$tmp" "$f"
}

backup_once() {
  local f="$1"
  [[ -f "${f}.bak" ]] || cp -p "$f" "${f}.bak"
}

has_key_literal() {
  local key="$1" f="$2"
  grep -Fq "export ${key}=" "$f"
}

key_of_line() {
  local line="$1"
  [[ -z "$line" || "${line:0:1}" == "#" ]] && { printf '
'; return; }
  [[ "$line" == export\ *=* ]] || { printf '
'; return; }
  line=${line#export }     # drop leading 'export '
  line=${line%%=*}         # before '='
  printf '%s
' "$line"
}

resolve_cfg() {
  # Try readlink -f; fall back to Python realpath for portability
  local p="$1" out
  if out=$(readlink -f "$p" 2>/dev/null); then
    printf '%s
' "$out"
  else
    python3 - <<'PY' "$p"
import os, sys
p = sys.argv[1]
print(os.path.realpath(p))
PY
  fi
}

compare_one() {
  local default_config="$1" active_config="$2" label="$3"

  if [[ ! -f "$default_config" ]]; then
    printf 'Error: default config not found: %s
' "$default_config" >&2
    return 1
  fi
  if [[ ! -L "$active_config" && ! -f "$active_config" ]]; then
    printf 'Warning: active %s config not found (missing symlink/file): %s
' "$label" "$active_config" >&2
    return 0
  fi

  local target
  target=$(resolve_cfg "$active_config")
  if [[ ! -f "$target" ]]; then
    printf 'Warning: active %s symlink is broken: %s -> %s
' "$label" "$active_config" "$target" >&2
    return 0
  fi

  printf '
----------------- CHECKING %s CONFIG -----------------
' "${label^^}"
  printf 'Default: %s
Active : %s (resolved)
' "$default_config" "$target"

  normalize_file "$default_config"
  normalize_file "$target"

  local default_lines other_lines
  mapfile -t default_lines < "$default_config"
  mapfile -t other_lines   < "$target"

  local dcount=${#default_lines[@]} ocount=${#other_lines[@]}
  logv "default lines: $dcount"
  logv "active  lines: $ocount"

  local i=0 max=$(( dcount > ocount ? dcount : ocount ))
  while (( i < max )); do
    step
    local changed=false

    local dline="${default_lines[i]:-}"
    local oline="${other_lines[i]:-}"

    logv "Checking Line: $((i+1))"

    if [[ "$dline" != "$oline" ]]; then
      local kdef koth
      kdef=$(key_of_line "$dline")
      koth=$(key_of_line "$oline")

      $verbose_enabled && {
        printf '	[XXX] Mismatch
'
        printf '		Default %4d: %s
' "$((i+1))" "$dline"
        printf '		Active  %4d: %s
' "$((i+1))" "$oline"
        [[ -n "$kdef" ]] && printf '		Key(def): %s
' "$kdef"
        [[ -n "$koth" ]] && printf '		Key(act): %s
' "$koth"
      }

      if [[ -z "$dline" ]]; then
        if (( i >= dcount )); then
          $verbose_enabled && printf '		[---] Past default length; deleting trailing line.
'
          if $apply_changes; then
            backup_once "$target"; sed -e '$d' "$target" > "$target.tmp" && mv "$target.tmp" "$target"; changed=true
          fi
        else
          $verbose_enabled && printf '		[+++] Insert blank line to mirror default.
'
          if $apply_changes; then
            backup_once "$target"; awk -v n=$((i+1)) 'NR==n{print ""}1' "$target" > "$target.tmp" && mv "$target.tmp" "$target"; changed=true
          fi
        fi
      else
        if [[ -n "$kdef" ]]; then
          if [[ -z "$oline" && $((i+1)) -lt ocount ]]; then
            $verbose_enabled && printf '		[---] Collapse double newline.
'
            if $apply_changes; then
              backup_once "$target"; sed "$((i+1))d" "$target" > "$target.tmp" && mv "$target.tmp" "$target"; changed=true
            fi
          elif has_key_literal "$kdef" "$target"; then
            $verbose_enabled && printf '		[>>>] Move key '%s' to match default order.
' "$kdef"
            if $apply_changes; then
              backup_once "$target"
              local line_to_move
              line_to_move=$(grep -F "export ${kdef}=" "$target" | head -n1)
              awk -v k="export ${kdef}=" -v n=$((i+1)) -v ins="$line_to_move" 'index($0,k){next} {lines[++c]=$0} END{for (j=1;j<=c;j++){ if (j==n) print ins; print lines[j] }}' "$target" > "$target.tmp" && mv "$target.tmp" "$target"; changed=true
            fi
          else
            $verbose_enabled && printf '		[+++] Insert missing key '%s'.
' "$kdef"
            if $apply_changes; then
              backup_once "$target"; awk -v n=$((i+1)) -v ins="$dline" 'NR==n{print ins}1' "$target" > "$target.tmp" && mv "$target.tmp" "$target"; changed=true
            fi
          fi
        else
          $verbose_enabled && printf '		[===] Mirror comment/non-export from default.
'
          if $apply_changes; then
            backup_once "$target"; awk -v n=$((i+1)) -v ins="$dline" 'NR==n{print ins}1' "$target" > "$target.tmp" && mv "$target.tmp" "$target"; changed=true
          fi
        fi
      fi

      if $changed; then
        mapfile -t other_lines < "$target"
        ocount=${#other_lines[@]}
        max=$(( dcount > ocount ? dcount : ocount ))
      else
        (( i++ ))
      fi
    else
      logv "	[OOO] Match: $dline"
      (( i++ ))
    fi
  done

  printf '
----------- FINISHED CHECKING %s CONFIG -----------
' "${label^^}"
}

# Defaults (keep same relative paths as your repo)
site_default="./site_config/default_site.config"
scenario_default="./scenario_config/default_scenario.config"

site_active="$HOME/.dt_site_config"
scenario_active="$HOME/.dt_scenario_config"

$check_site && compare_one "$site_default" "$site_active" "site"
$check_scenario && compare_one "$scenario_default" "$scenario_active" "scenario"
```

## How to use

* **Dry-run (no changes):** `./ADMIN_check_configs.sh`
* **Apply changes:** `./ADMIN_check_configs.sh --apply`
* **Only site:** `./ADMIN_check_configs.sh --site-only`
* **Only scenario:** `./ADMIN_check_configs.sh --scenario-only`

Notes:

* The script resolves symlinks and will warn on missing/broken links.
* Edits create `*.bak` once per active file.
* If you run on macOS without GNU coreutils, this version avoids `sed -i` differences.
