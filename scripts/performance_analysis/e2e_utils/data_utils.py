from pathlib import Path
import time
import re

import pandas as pd

_YEAR_PATTERN = re.compile(r"2\d{3}")

_DATA_TYPE_FOLDER_ABBREV: dict[str, str] = {
    "landvehicle": "LV",
    "v2xmessage": "V2X",
    "trafficsignalcontroller": "TSC",
}

_RUN_NUMBER_PATTERN = re.compile(r"R(\d+)", re.IGNORECASE)

RunDataFrames = dict[str, dict[str, dict[str, list[tuple[str, pd.DataFrame]]]]]


def _extract_site_name(raw: str) -> str:
    """Normalizes a raw site name token extracted from a CSV filename.

    Args:
        raw: Raw site name string parsed from a filename segment.

    Returns:
        Uppercase normalized site name with date and suffix tokens removed.
    """
    if _YEAR_PATTERN.search(raw) or "_" in raw:
        return raw.split("_")[0].upper()
    if "-" in raw:
        return raw.split("-")[0].upper()
    return raw.upper()


def _load_run_dataframe(csv_file: Path) -> pd.DataFrame:
    """Reads a single run CSV and returns a cleaned, renamed DataFrame.

    Args:
        csv_file: Path to the CSV file to load.

    Returns:
        DataFrame with columns [Datetime, Latency, Timestamp_in_s].
    """
    df = pd.read_csv(csv_file)

    date_col = df.filter(like="timestamp").columns[0]
    performance_metric_col = df.filter(like="_total_latency").columns[-1]
    df = df[[date_col, performance_metric_col]]

    if df[date_col].iloc[0] > int(time.time()):
        df["Timestamp_in_s"] = df[date_col] / 10**9
        df[date_col] = pd.to_datetime(df[date_col], unit="ns", errors="coerce")
    else:
        df["Timestamp_in_s"] = df[date_col]
        df[date_col] = pd.to_datetime(df[date_col], unit="s", errors="coerce")

    df[performance_metric_col] = pd.to_numeric(
        df[performance_metric_col], errors="coerce"
    )
    df.columns = pd.Index(["Datetime", "Latency", "Timestamp_in_s"])
    return df


def _print_import_summary(run_data_frames: RunDataFrames) -> None:
    """Prints a structured summary of all imported run data.

    Args:
        run_data_frames: Nested mapping of run numbers to site pair DataFrames.
    """
    print("\n\n-----------IMPORT SUMMARY-----------")
    for run_number, run_data in run_data_frames.items():
        print(f"RUN: {run_number}")
        for source_site, dest_data in run_data.items():
            print(f"\tsource_site: {source_site}")
            for dest_site in dest_data:
                print(f"\t\tdest_site: {dest_site}")


def load_and_parse_csv_data(
    root_dir: Path,
    folder_prefix: str,
    data_type: str,
) -> tuple[RunDataFrames, set[str], set[str]] | None:
    """Loads and parses CSV data from run directories matching a folder prefix.

    Args:
        root_dir: Root directory containing run result folders.
        folder_prefix: Substring used to identify matching run folders
            (e.g. 'EnergyOffset-130').
        data_type: Message type used to filter folders and CSV files
            (e.g. 'LandVehicle', 'V2XMessage', 'TrafficSignalController').

    Returns:
        A tuple of (run_data_frames, all_source_sites, all_destination_sites),
        or None if no matching data was found.
    """
    folder_abbrev = _DATA_TYPE_FOLDER_ABBREV.get(data_type.lower())
    if folder_abbrev is None:
        print(
            f"Unknown data type '{data_type}'."
            f" Known types: {list(_DATA_TYPE_FOLDER_ABBREV.keys())}"
        )
        return None

    run_dirs = [
        d
        for d in root_dir.glob(f"*{folder_prefix}*")
        if d.is_dir() and folder_abbrev in d.name.upper()
    ]

    if not run_dirs:
        print(
            f"No folders found matching prefix '{folder_prefix}'"
            f" and type '{folder_abbrev}' in {root_dir}"
        )
        return None

    run_data_frames: RunDataFrames = {}
    all_source_sites: set[str] = set()
    all_destination_sites: set[str] = set()

    for run_dir in run_dirs:
        match = _RUN_NUMBER_PATTERN.search(run_dir.name)
        run_number = match.group(1) if match else run_dir.name
        data_frames: dict[str, dict[str, list[tuple[str, pd.DataFrame]]]] = {}

        for csv_file in run_dir.glob("*.csv"):
            print(f"csv_file: {csv_file}")

            if "summary" in csv_file.name:
                continue

            filename_parts = csv_file.name.split("_to_")
            if len(filename_parts) < 2:
                continue

            source_site = _extract_site_name(filename_parts[0])
            print(f"source_site: {source_site}")

            destination_raw = filename_parts[1].split("_" + data_type.lower() + "_")[0]
            destination_site = _extract_site_name(destination_raw)
            print(f"destination_site: {destination_site}")

            df = _load_run_dataframe(csv_file)

            data_frames.setdefault(source_site, {}).setdefault(
                destination_site, []
            ).append((run_number, df))
            all_source_sites.add(source_site)
            all_destination_sites.add(destination_site)

        if data_frames:
            run_data_frames[run_number] = data_frames

    _print_import_summary(run_data_frames)

    if not run_data_frames:
        print(
            f"No data found for prefix '{folder_prefix}'"
            f" and data type '{data_type}'."
        )
        return None

    return run_data_frames, all_source_sites, all_destination_sites
