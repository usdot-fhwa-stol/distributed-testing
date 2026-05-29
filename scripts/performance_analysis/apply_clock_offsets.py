import os
import json
import pandas as pd
from pathlib import Path
import argparse

# ------------------------
# SITE OFFSETS (ms)
# ------------------------

# For Energy Cohort, ORNL was deemed to have the most stable connection and thus they are the basis for the timing offsets
ENERGY_COHORT_OFFSETS = {
    "ANL": -10,
    "FHWA": -20,
    "ORNL": 0,
    "PITT": 180,
    "SWARCO": -2450,
    "SWRI": -3475,
}


# ------------------------
# CONSTANTS
# ------------------------

RECEIPT_FIELD = "Metadata,TimeOfReceipt"

TX_FIELD_V2X = "Metadata,TimeOfTransmission"
TX_FIELD_LV_TSC = "Metadata,TimeOfCommit"

TX_IP_FIELD_V2X = "Metadata,SenderId.hostIPaddress"
TX_IP_FIELD_LV_TSC = "const^Metadata,SDOid.hostIPaddress"

NS_PER_MS = 1_000_000

# ------------------------
# METADATA + SITE RESOLUTION
# ------------------------

def load_metadata(metadata_path):
    with open(metadata_path, "r") as f:
        return json.load(f)
    

def build_ip_to_site(metadata):
    ip_to_site = {}
    for site in metadata:
        site_name = site["site_name"]

        ip = site["ip_address"]
        ip_to_site[ip] = site_name

    return ip_to_site

def resolve_sender_site(row, ip_to_site, tx_field):
    """
    Resolve sender site using correct IP field per message type
    """
    if tx_field == TX_FIELD_V2X:
        sender_ip = row.get(TX_IP_FIELD_V2X, None)
    else:
        sender_ip = row.get(TX_IP_FIELD_LV_TSC, None)

    if pd.isna(sender_ip) or sender_ip is None:
        return None
    
    return ip_to_site.get(sender_ip, None)


# ------------------------
# TIMESTAMP HANDLING
# ------------------------

def get_tx_field(file_name: str):
    """
    Decide timestamp field based on dataset type in filename
    """
    # rule: TV2XMsg-V2X => transmission
    if "TV2XMsg-V2X" in file_name:
        return TX_FIELD_V2X
    return TX_FIELD_LV_TSC

def apply_offset(value, offset_ms):
    """
    offsets are in ms, timestamps are assumed ms
    """
    raw_ns = int(value)
    offset_ns = int(offset_ms * NS_PER_MS)
    
    return raw_ns + offset_ns


# ------------------------
# CORE PROCESSING
# ------------------------

def process_csv(csv_path, receipt_site, ip_to_site):

    print(f"        correcting: {csv_path}")
    df = pd.read_csv(csv_path)

    file_name = os.path.basename(csv_path)
    tx_field = get_tx_field(file_name)

    corrected_tx = []
    corrected_rx = []

    for _, row in df.iterrows():

        try:
            sender_site = resolve_sender_site(row, ip_to_site, tx_field)
            receiver_site = receipt_site

            send_offset = ENERGY_COHORT_OFFSETS.get(sender_site, 0)
            receipt_offset = ENERGY_COHORT_OFFSETS.get(receiver_site, 0)

            tx_val = row.get(tx_field)
            tx_val_corr = apply_offset(tx_val, send_offset)
            corrected_tx.append(tx_val_corr)

            rx_val = row.get(RECEIPT_FIELD)
            rx_val_corr = apply_offset(rx_val, receipt_offset)
            corrected_rx.append(rx_val_corr)
        except Exception as e:
            print(csv_path)
            print(tx_field)
            print(row)
            print(e)


    df[tx_field] = corrected_tx
    df[RECEIPT_FIELD] = corrected_rx

    df.to_csv(csv_path, index=False)
    print(f"        corrected: {csv_path}")

# ------------------------
# RUN PROCESSING
# ------------------------
def process_run(run_path: Path):
    metadata_path = run_path / "metadata.json"

    if not metadata_path.exists():
        print(f"[SKIP] No metadata in {run_path}")
        return
    
    metadata = load_metadata(metadata_path)
    ip_to_site = build_ip_to_site(metadata)

    print(ip_to_site)

    #
    # iterate site folders
    #

    for site_dir in run_path.iterdir():
        if not site_dir.is_dir():
            continue

        tdcs_dir = site_dir / "exported_tdcs"

        if not tdcs_dir.exists():
            continue

        receipt_site = site_dir.name

        print(f"\n SITE: {receipt_site}")

        #
        # iterate csv files
        #

        for csv_file in tdcs_dir.glob("*.csv"):
            if "Scenario" not in csv_file.name:
                process_csv(
                    csv_path=csv_file,
                    receipt_site=receipt_site,
                    ip_to_site=ip_to_site
                )

# ------------------------
# EVENT PROCESSING
# ------------------------
def apply_offset_to_event(event_dir: str):
    event_dir = Path(event_dir)

    for run in sorted(event_dir.iterdir()):
        if not run.is_dir():
            continue

        print(f"\n============ RUN: {run.name} ============")
        process_run(run)

# ------------------------
# main
# ------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", required=True, help="Event directory")
    args = parser.parse_args()

    apply_offset_to_event(args.input)

    print(f"\n============ DONE :) ============")