### The purpose of this script is to compile the generated event results csv files across all runs into a single csv file.
### This script will take the command line argument event and only search through folders with that event prefix.
### It will extract the data from each <Event>-R<run#>-<DataType>_results_summary.csv file, return those results, as well
### as compiled latency data across all runs for each data type, and compiled across all runs for all data types

import os
import re
import argparse
import pandas as pd

# -----------------------
# Command line argument
# -----------------------
parser = argparse.ArgumentParser(description="Compile latency analysis results")
parser.add_argument("event", help="Event name to filter (e.g. Energy130)")
parser.add_argument("--root", default="./results", help="Root directory of result folders")
args = parser.parse_args()

EVENT_FILTER = args.event
ROOT_DIR = args.root

# Folder Pattern: <Event>-R<Run #>-<DataType>_results
FOLDER_PATTERN = re.compile(r"(.+)-R(\d+)-(.+)_results")

EXPECTED_COLUMNS = [
    "j2735_type", "source", "source_type",
    "destination", "destination_type", "step_type",
    "min", "max", "mean", "jitter", "std_dev"
]

# -----------------------
# Load data
# -----------------------

all_data = []

for folder in os.listdir(ROOT_DIR):
    folder_path = os.path.join(ROOT_DIR, folder)

    #Skip non directories/folders
    if not os.path.isdir(folder_path):
        continue

    #Skip folders that don't match the desired folder pattern
    match = FOLDER_PATTERN.match(folder)
    if not match:
        continue

    # Extract the event name, run#, and data type
    event, run, data_type = match.groups()

    # Filter by event
    if event != EVENT_FILTER:
        continue

    summary_file = f"{event}-R{run}-{data_type}_results_summary.csv"
    summary_path = os.path.join(folder_path, summary_file)

    if not os.path.exists(summary_path):
        print(f"Missing summary file: {summary_path}")
        continue

    df = pd.read_csv(summary_path)

    # Validate schema
    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{summary_file} missing columns: {missing}")
    
    df = df[EXPECTED_COLUMNS]

    # Add metadata
    df["run"] = int(run)
    df["data_type"] = data_type

    all_data.append(df)

# Safety check
if not all_data:
    raise RuntimeError(f"No data found for event: {EVENT_FILTER}")

# Combine
master_df = pd.concat(all_data, ignore_index=True)

# -----------------------
# Aggregations
# -----------------------

agg_map = {
    "min": "min",
    "max": "max",
    "mean": "mean",
    "jitter": "mean"
}

# Per run
by_run = master_df.groupby(
    ["source", "destination", "run"]
).agg(agg_map).reset_index()

# Across runs per data_type
by_datatype = master_df.groupby(
    ["source", "destination", "data_type"]
).agg(agg_map).reset_index()

# Across all data_types
overall = master_df.groupby(
    ["source", "destination"]
).agg(agg_map).reset_index()

# -----------------------
# Pivot views (for readability)
# -----------------------

# Mean latency per run
pivot_run_mean = master_df.pivot_table(
    index=["source", "destination"],
    columns="run",
    values="mean"
)

# Mean latency per data_type
pivot_datatype_mean = master_df.pivot_table(
    index=["source", "destination"],
    columns="data_type",
    values="mean"
)

# -----------------------
# Excel output
# -----------------------
output_file = f"{EVENT_FILTER}_latency_analysis.xlsx"

with pd.ExcelWriter(output_file) as writer:
    # Raw Data
    master_df = master_df.sort_values(
        by=["run", "source", "destination", "data_type"],
        ascending=[True, True, True, True]
    )
    master_df.to_excel(writer, sheet_name="Raw_Latency_Data", index=False)
    
    # Grouped
    by_run.to_excel(writer, sheet_name="Latency_By_Run", index=False)
    by_datatype.to_excel(writer, sheet_name="Latency_By_DataType", index=False)
    overall.to_excel(writer, sheet_name="Latency_Overall", index=False)

    # Pivot (visual)
    pivot_run_mean.to_excel(writer, sheet_name="Pivot_Run_Mean")
    pivot_datatype_mean.to_excel(writer, sheet_name="Pivot_DataType_Mean")

print(f" Excel file created: {output_file}")