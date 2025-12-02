#!/usr/bin/env python3
import re
import os
import sys
import shutil

DT_PATH = os.environ['VUG_LOCAL_DT_PATH']
DEFAULT_SITE_CONFIG = os.path.join(DT_PATH, "config/site_config/default_site.config")
DEFAULT_SCENARIO_CONFIG = os.path.join(DT_PATH, "config/scenario_config/default_scenario.config")

USER_SITE_CONFIG = os.path.realpath(os.path.expanduser("~/.dt_site_config"))
USER_SCENARIO_CONFIG = os.path.realpath(os.path.expanduser("~/.dt_scenario_config"))

export_re = re.compile(r'^export\s+([A-Za-z_][A-Za-z0-9_]*)=(.*)$')

def parse_config(path):
    """
    Parse a .config file and return a dict of exported environment variables.
    Ignores comment lines, empty lines, and skips any lines inside an if..fi block
    """

    exports = {}
    invalid_lines = []
    inside_if_block = False

    with open(path, 'r') as f:
        for line in f:
            stripped = line.strip()

            # Skip comments and blank lines
            if not stripped or stripped.startswith('#'):
                continue

            # Ignore if-block
            if stripped.startswith ("if "):
                inside_if_block = True
                continue

            if stripped == "fi":
                inside_if_block = False
                continue

            if inside_if_block:
                continue

            # Match export lines
            match = export_re.match(stripped)
            if match:
                var, val = match.groups()
                exports[var] = val.strip()
            else:
                invalid_lines.append(stripped)
    
    return exports, invalid_lines

def compare_config(default_path, user_path):
    default_vars, _ = parse_config(default_path)
    user_vars, user_invalid = parse_config(user_path)

    default_keys = set(default_vars.keys())
    user_keys = set(user_vars.keys())

    added = user_keys - default_keys
    removed = default_keys - user_keys
    modified = {
        k for k in (default_keys & user_keys)
        if default_vars[k] != user_vars[k]
    }

    print("=== Differences Between Configs ===\n")

    if added:
        print("Variables added by user:")
        for k in sorted(added):
            print(f"  + {k}={user_vars[k]}")
    else:
        print("No variables added.")

    print()

    if removed:
        print("Variables removed (found in default but not user config):")
        for k in sorted(removed):
            print(f"  - {k}={default_vars[k]}")
    else:
        print("No variables removed.")

    print()

    if modified:
        print("Variables with modified values:")
        for k in sorted(modified):
            print(f"  * {k}: default='{default_vars[k]}' -> user='{user_vars[k]}'")
    else:
        print("No variables modified.")

    print()

    if user_invalid:
        print("Found unrecognized lines in user config:")
        for line in user_invalid:
            print("  ", line)

    print()

    if added or removed or user_invalid:
        return True
    else:
        return False

def update_user_config(default_path, user_path):

    """
    Rebuild the user config based on the default config and user-defined overrides.
    Only environment variables present in the default are kept.
    """

    # Read vars
    user_vars, _ = parse_config(user_path)

    # Backup User Config
    backup_path = user_path + ".bak"
    shutil.copy2(user_path, backup_path)
    print(f"Backup created: {backup_path}")

    # Replace user config with default template
    shutil.copy2(default_path, user_path)
    print(f"User config reset to default template.")

    # Apply user overrides onto fresh config
    updated_lines = []
    with open(user_path, "r") as f:
        for line in f:
            stripped = line.strip()

            match = export_re.match(stripped)
            if match:
                var, val = match.groups()
                if var in user_vars:
                    # Replace default value with user's value
                    new_line = f"export {var}={user_vars[var]}\n"
                    updated_lines.append(new_line)
                    continue
            
            updated_lines.append(line)

    # Write updated user config
    with open(user_path, "w") as f:
        f.writelines(updated_lines)

    print(f"User config updated successfully: {user_path}\n")


def validate_paths(user_site, user_scenario):
    if not os.path.exists(user_site):
        print(f"Error: User Site Config '{user_site}' does not exist")
        return False
    if not os.path.exists(user_scenario):
        print(f"Error: User Scenario Config '{user_scenario}' does not exist")
        return False
    return True

if __name__ == "__main__":
    if not validate_paths(USER_SITE_CONFIG, USER_SCENARIO_CONFIG):
        sys.exit(2)

    UPDATE_MODE = ("--update" in sys.argv) or ("-u" in sys.argv)

    print("=== Comparing Site Configuration to Default ===")
    changed_site = compare_config(DEFAULT_SITE_CONFIG, USER_SITE_CONFIG)
    print("=== Comparing Scenario Configuration to Default ===")
    changed_scenario = compare_config(DEFAULT_SCENARIO_CONFIG, USER_SCENARIO_CONFIG)

    if changed_site or changed_scenario:
        print(f"WARNING: Your configuration file(s) have additional and/or missing required environment variables. Update them using 'dt config update' ")

    if UPDATE_MODE:
        if changed_site:
            print("=== Updating Site Configuration ===")
            update_user_config(DEFAULT_SITE_CONFIG, USER_SITE_CONFIG)
        if changed_scenario:
            print("=== Updating Scenario Configuration ===")
            update_user_config(DEFAULT_SCENARIO_CONFIG, USER_SCENARIO_CONFIG)
        if not changed_site and not changed_scenario:
            print("No updates required")

    if changed_site or changed_scenario:
        sys.exit(1)
    sys.exit(0)
    
    
    