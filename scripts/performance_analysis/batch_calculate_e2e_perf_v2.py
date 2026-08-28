"""
batch_calculate_e2e_perf.py


============================== USAGE ==============================

    cd ~/distributed-testing/scripts/performance_analysis
    python3 batch_calculate_e2e_perf.py -m <path to Run's metadata.json> -n <short label>

    -m   path to the metadata.json for ONE run (from batch_decode_raw_data.py)
    -n   a SHORT LABEL for this batch of results, e.g. "Run1" -- NOT a path.
         (calculate_e2e_perf.py uses this to build results/<label>_results/
         and <label>_results_summary.csv, relative to wherever you run this
         script from -- so run it from the performance_analysis directory.)

    --dry-run   only generate the per-pair import CSVs, don't actually run
                calculate_e2e_perf.py. Use this first to sanity check the
                file paths it found before running the full batch.


"""

import argparse
import csv
import glob
import json
import os
import subprocess
import sys

##############################################################################
# CONFIG -- CHECK / EDIT THESE BEFORE RUNNING
##############################################################################

# Which data types to compute latency for. Names must exactly match
# calculate_e2e_perf.py's J2735_message_types list. Uncomment what you need.
# NOTE: there's no standalone TrafficLight/BSM table in your data -- both live
# inside the V2X message file, pulled out via subtype ("J2735-BSM"/"J2735-SPAT").
DATA_TYPES_TO_RUN = [
    "Vehicle",
    "J2735-BSM",
    # "J2735-SPAT",  # not broadcast in this test -- skipping
    # "J2735-MAP",
]

# Glob pattern to find each data type's exported TDCS CSV inside a site's
# tdcs_dir (i.e. its "exported_tdcs" folder). Confirmed against your real
# filenames: DOT_OSTR-Entities-LandVehicle-<ts>.csv and DOT_OSTR-TV2XMsg-V2X-<ts>.csv.
TDCS_FILE_PATTERNS = {
    "Vehicle": "*LandVehicle*",
    "J2735": "*TV2XMsg-V2X*",
    "J2735-BSM": "*TV2XMsg-V2X*",
    "J2735-SPAT": "*TV2XMsg-V2X*",
    "J2735-MAP": "*TV2XMsg-V2X*",
    "J3224": None,  # no J3224 table observed in your export
}

# Glob pattern to find each data type's decoded pcap CSV inside a site's
# pcap_in_dir / pcap_out_dir. Only used as a fallback if a site has no TDCS
# export for that type. No pcap files were seen in your run, so these
# patterns are unverified placeholders -- fine to leave as-is since they'll
# simply never be reached while TDCS data is present.
PCAP_FILE_PATTERNS = {
    "Vehicle": None,
    "J2735": "*J2735*",
    "J2735-BSM": "*BSM*",
    "J2735-SPAT": "*SPAT*",
    "J2735-MAP": "*MAP*",
    "J3224": "*J3224*",
}

# Which key to look up in each site's metadata.json "adapter_addresses_by_type"
# dict to get the full "IP:port" endpoint string needed for J2735-family
# "Metadata,Endpoint" filtering (a bare IP address will not match). The key
# name comes from the exported filename prefix before the timestamp.
ADAPTER_ENDPOINT_LOOKUP_KEY = {
    "J2735": "DOT_OSTR-TV2XMsg-V2X",
    "J2735-BSM": "DOT_OSTR-TV2XMsg-V2X",
    "J2735-SPAT": "DOT_OSTR-TV2XMsg-V2X",
    "J2735-MAP": "DOT_OSTR-TV2XMsg-V2X",
    "J3224": None,
}

##############################################################################


def resolve_adapter_ip(site, data_type):
    """For J2735-family data types, look up the site's full IP:port endpoint
    string from metadata.json's adapter_addresses_by_type (required for the
    'Metadata,Endpoint' filter to match anything). Other data types (e.g.
    Vehicle) don't need this and just get the bare ip_address back, which
    load_data() ignores for them anyway."""
    lookup_key = ADAPTER_ENDPOINT_LOOKUP_KEY.get(data_type)
    if lookup_key:
        endpoint = site.get("adapter_addresses_by_type", {}).get(lookup_key)
        if endpoint:
            return endpoint
        print(f"\tWARNING: no '{lookup_key}' entry in adapter_addresses_by_type for "
              f"{site['site_name']} -- falling back to bare IP, which will likely "
              f"yield zero matching rows for {data_type}")
    return site.get("ip_address", "")


def find_file(directory, pattern):
    """Find a file matching pattern inside directory (non-recursive).
    Returns None if directory/pattern missing or nothing matches.
    Prompts for a choice if multiple files match."""
    if not directory or not pattern:
        return None
    if not os.path.isdir(directory):
        return None

    matches = sorted(glob.glob(os.path.join(directory, pattern)))
    if len(matches) == 0:
        return None
    if len(matches) == 1:
        return matches[0]

    print(f"\n\tMultiple files matched '{pattern}' in {directory}:")
    for i, m in enumerate(matches):
        print(f"\t\t[{i}] {m}")
    choice = input("\tSelect file index --> ")
    try:
        return matches[int(choice)]
    except (ValueError, IndexError):
        print("\tInvalid selection, defaulting to first match")
        return matches[0]


def write_import_csv(csv_path, rows):
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow([
            "load_data", "dataset_name", "dataset_file_location",
            "dataset_type", "message_type", "adapter_ip",
            "start_time", "end_time",
        ])
        for row in rows:
            writer.writerow(row)


def build_import_file(site_a, site_b, data_type, import_dir):
    """Build a 2-hop import file: site_a's own data -> site_b's received copy.
    Prefers each site's TDCS export; falls back to pcap if unavailable.
    Returns the import file path, or None if required data is missing."""

    a_name = site_a["site_name"]
    b_name = site_b["site_name"]

    tdcs_pattern = TDCS_FILE_PATTERNS.get(data_type)
    pcap_pattern = PCAP_FILE_PATTERNS.get(data_type)

    a_tdcs_file = find_file(site_a.get("tdcs_dir"), tdcs_pattern)
    a_pcap_file = find_file(site_a.get("pcap_out_dir"), pcap_pattern)

    b_tdcs_file = find_file(site_b.get("tdcs_dir"), tdcs_pattern)
    b_pcap_file = find_file(site_b.get("pcap_in_dir"), pcap_pattern)

    a_adapter_ip = resolve_adapter_ip(site_a, data_type)
    b_adapter_ip = resolve_adapter_ip(site_b, data_type)

    rows = []

    if a_tdcs_file:
        rows.append(["true", f"{a_name}_{data_type}_tdcs", a_tdcs_file, "tdcs",
                     data_type, a_adapter_ip,
                     site_a.get("start_time", ""), site_a.get("end_time", "")])
    elif a_pcap_file:
        rows.append(["true", f"{a_name}_{data_type}_pcap_out", a_pcap_file, "pcap",
                     data_type, a_adapter_ip,
                     site_a.get("start_time", ""), site_a.get("end_time", "")])
    else:
        print(f"\tSkipping {a_name} -> {b_name} ({data_type}): no source data found for {a_name}")
        return None

    if b_tdcs_file:
        rows.append(["true", f"{a_name}_to_{b_name}_{data_type}_tdcs", b_tdcs_file, "tdcs",
                     data_type, b_adapter_ip,
                     site_b.get("start_time", ""), site_b.get("end_time", "")])
    elif b_pcap_file:
        rows.append(["true", f"{a_name}_to_{b_name}_{data_type}_pcap_in", b_pcap_file, "pcap",
                     data_type, b_adapter_ip,
                     site_b.get("start_time", ""), site_b.get("end_time", "")])
    else:
        print(f"\tSkipping {a_name} -> {b_name} ({data_type}): no destination data found for {b_name}")
        return None

    os.makedirs(import_dir, exist_ok=True)
    import_file_path = os.path.join(import_dir, f"{a_name}_to_{b_name}_{data_type}.csv")
    write_import_csv(import_file_path, rows)
    return import_file_path


def main():
    parser = argparse.ArgumentParser(description="Batch E2E latency calculation, driven by metadata.json")
    parser.add_argument("-m", "--metadata", required=True, help="Path to the run's metadata.json")
    parser.add_argument("-n", "--name", required=True,
                         help="Short label for this batch of results (e.g. 'Run1') -- NOT a path")
    parser.add_argument("--dry-run", action="store_true",
                         help="Only generate import CSVs, don't run calculate_e2e_perf.py")
    args = parser.parse_args()

    with open(args.metadata, "r") as f:
        sites = json.load(f)

    print(f"\nLoaded {len(sites)} site(s) from metadata:")
    for s in sites:
        print(f"\t{s['site_name']}  (tdcs_dir={s.get('tdcs_dir')})")

    metadata_dir = os.path.dirname(os.path.abspath(args.metadata))
    import_dir = os.path.join(metadata_dir, "generated_import_files")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    calculate_script = os.path.join(script_dir, "calculate_e2e_perf.py")

    if not os.path.isfile(calculate_script):
        print(f"\nERROR: calculate_e2e_perf.py not found at {calculate_script}")
        sys.exit(1)

    ran_any = False

    for data_type in DATA_TYPES_TO_RUN:
        print(f"\n========== DATA TYPE: {data_type} ==========")

        for site_a in sites:
            for site_b in sites:
                if site_a["site_name"] == site_b["site_name"]:
                    continue

                print(f"\n{site_a['site_name']} -> {site_b['site_name']} ({data_type})")

                import_file = build_import_file(site_a, site_b, data_type, import_dir)
                if not import_file:
                    continue

                print(f"\tGenerated import file: {import_file}")

                if args.dry_run:
                    continue

                outfile_name = f"{site_a['site_name']}_to_{site_b['site_name']}_{data_type}"

                cmd = [
                    "python3", calculate_script,
                    "-i", import_file,
                    "-t", data_type,
                    "-s", site_a["site_name"],
                    "-m", args.metadata,
                    "-o", outfile_name,
                    "-r", args.name,
                ]

                print("\tRunning: " + " ".join(cmd))
                subprocess.run(cmd, check=False)
                ran_any = True

    if args.dry_run:
        print(f"\n----- DRY RUN COMPLETE ----- (import files written to {import_dir})")
    elif not ran_any:
        print("\nNo site pairs had usable data for any configured data type. "
              "Check TDCS_FILE_PATTERNS / PCAP_FILE_PATTERNS against your actual filenames.")
    else:
        print(f"\n----- BATCH ANALYSIS COMPLETE ----- (results/{args.name}_results/)")


if __name__ == "__main__":
    main()