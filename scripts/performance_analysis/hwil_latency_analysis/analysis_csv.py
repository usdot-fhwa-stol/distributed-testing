"""Analyze Radio and SecureV2XMessage CSV latency data."""

import logging
import re
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from plots_and_summaries import create_plots_and_report

MAX_LATENCY_MS = 200.0
ROLLING_WINDOW = 20
LATENCY_THRESHOLD_MS = 10.0
MESSAGE_ROUTE = "v2xhub->dt_plugin"

RECEIPT_COLUMN = "Metadata,TimeOfReceipt"

DATA_TYPES: dict[str, dict[str, Any]] = {
    "Radio": {
        "patterns": (
            "*Entities-Radio*.csv",
            "*Radio*.csv",
            "*.csv",
        ),
        "id_cols": (
            "const^identifier,String",
            "Metadata,StateVersion",
        ),
        "data_cols": (
            "Metadata,TimeOfCommit",
            "Metadata,TimeOfReceipt",
        ),
        "skip_events": {"Discovery", "Destruction"},
    },
    "SecureV2XMessage": {
        "patterns": (
            "*TV2XMsg-SecureV2XMsg*.csv",
            "*SecureV2XMsg*.csv",
            "*SecureV2X*.csv",
            "*.csv",
        ),
        "id_cols": (
            "Metadata,MessageCount",
            "senderIdentifier,String",
            "uuid,String",
        ),
        "data_cols": (
            "Metadata,TimeOfTransmission",
            "Metadata,TimeOfReceipt",
        ),
        "skip_events": set(),
    },
}


def clean_text(value: Any) -> str:
    """Return a trimmed string or an empty string for a missing value."""
    if pd.isna(value):
        return ""

    return str(value).strip()


def extract_host(value: Any) -> str:
    """Extract the host from an endpoint value."""
    endpoint = clean_text(value)

    if not endpoint:
        return ""

    # removes the protocol from the endpoint
    endpoint = re.sub(
        r"^[A-Za-z][A-Za-z0-9+.-]*://",
        "",
        endpoint,
    )

    # remove the port from the endpoint 
    if endpoint.count(":") == 1:
        return endpoint.rsplit(":", maxsplit=1)[0]

    return endpoint


def get_csv_file(
    directory: Path,
    patterns: Iterable[str],
) -> Path | None:
    """Find the first CSV matching the csv file name patterns."""
    
    if not directory.is_dir():
        logging.info("CSV directory is missing; skipping: %s", directory)
        return None

    # Find all files matching patterns defined in DATA_TYPES, sort and return first match
    for pattern in patterns:
        matches = sorted(
            (
                path.resolve()
                for path in directory.glob(pattern)
                if path.is_file()
            ),
            key=lambda path: path.name.lower(),
        )

        if not matches:
            continue

        if len(matches) > 1:
            logging.warning(
                "Multiple CSV files matched %r in %s; using %s",
                pattern,
                directory,
                matches[0].name,
            )

        return matches[0]

    return None


def read_latency_data(
    csv_file: Path,
    message_type: str,
) -> pd.DataFrame:
    """Read and prepare latency data from one CSV."""
    csv_data = pd.read_csv(
        csv_file,
        dtype=str,
    )

    # Check if TimeOfCommit or TimeOfRecipt are missing
    outbound_col = DATA_TYPES[message_type]["data_cols"][0]
    missing_columns = [
        column
        for column in (outbound_col, RECEIPT_COLUMN)
        if column not in csv_data.columns
    ]

    if missing_columns:
        logging.warning(
            "Skipping %s because it is missing: %s",
            csv_file,
            ", ".join(missing_columns),
        )
        return pd.DataFrame()

    # Skip events like Discovery, we only want StateChange
    skip_events = DATA_TYPES[message_type]["skip_events"]
    event_type_column = "Metadata,Enum,Middleware::EventType"

    if skip_events and event_type_column in csv_data.columns:
        skipped_events = csv_data[event_type_column].isin(skip_events)
        skipped_count = int(skipped_events.sum())

        if skipped_count:
            logging.info(
                "Skipped %d %s event row(s) in %s",
                skipped_count,
                message_type,
                csv_file.name,
            )

        csv_data = csv_data.loc[~skipped_events].copy()

    # Filter out messages where the host sent messages to itself
    # host_ip_column = "const^Metadata,SDOid.hostIPaddress"
    # endpoint_column = "const^Metadata,Endpoint"

    # if (
    #     host_ip_column in csv_data.columns
    #     and endpoint_column in csv_data.columns
    # ):
    #     # Extract and clean ips
    #     host_ips = csv_data[host_ip_column].map(clean_text)
    #     endpoint_hosts = csv_data[endpoint_column].map(extract_host)

    #     # Check if ips match
    #     self_messages = host_ips.eq(endpoint_hosts) & host_ips.ne("")
    #     skipped_count = int(self_messages.sum())

    #     if skipped_count:
    #         logging.info(
    #             "Skipped %d self-message row(s) in %s",
    #             skipped_count,
    #             csv_file.name,
    #         )

    #     # Remove rows that are self messages
    #     csv_data = csv_data.loc[~self_messages].copy()

    # Convert int time values to float, set to Nan if error
    tx_timestamps = pd.to_numeric(
        csv_data[outbound_col],
        errors="coerce",
    )
    rx_timestamps = pd.to_numeric(
        csv_data[RECEIPT_COLUMN],
        errors="coerce",
    )

    # Remove Nan values
    valid_timestamps = (
        tx_timestamps.notna()
        & rx_timestamps.notna()
    )
    skipped_count = int((~valid_timestamps).sum())

    if skipped_count:
        logging.warning(
            "Skipped %d row(s) without valid transmission and receipt "
            "timestamps in %s",
            skipped_count,
            csv_file.name,
        )

    # Calcualte latency for each row, remove latency values that dont make sense (negative)
    tx_timestamps = tx_timestamps.loc[valid_timestamps]
    rx_timestamps = rx_timestamps.loc[valid_timestamps]

    # Convert to ms
    tx_timestamps = tx_timestamps / 1e6
    rx_timestamps = rx_timestamps / 1e6
    
    latency_ms = rx_timestamps - tx_timestamps

    valid_latency = latency_ms >= 0
    skipped_count = int((~valid_latency).sum())

    if skipped_count:
        logging.warning(
            "Skipped %d row(s) with negative latency in %s",
            skipped_count,
            csv_file.name,
        )

    # Get all valid positive latency rows
    tx_timestamps = tx_timestamps.loc[valid_latency]
    rx_timestamps = rx_timestamps.loc[valid_latency]
    latency_ms = latency_ms.loc[valid_latency]

    return pd.DataFrame(
        {
            "Tx Timestamp (ms)": tx_timestamps.to_numpy(),
            "Rx Timestamp (ms)": rx_timestamps.to_numpy(),
            "Latency (ms)": latency_ms.to_numpy(),
            "Datetime": pd.to_datetime(
                tx_timestamps.to_numpy(),
                unit="ns",
                utc=True,
            ),
        }
    ).sort_values(
        by=["Tx Timestamp (ms)", "Rx Timestamp (ms)"],
        ignore_index=True,
    )


def analyze_message_type(
    csv_root: Path,
    results_dir: Path,
    run_name: str,
    message_type: str,
) -> bool:
    """Analyze one CSV message type."""
    # Ex: run_001/Radio/radio.csv
    message_directory = csv_root / message_type
    csv_file_path = get_csv_file(
        directory=message_directory,
        patterns=DATA_TYPES[message_type]["patterns"],
    )

    if csv_file_path is None:
        logging.info(
            "Skipping %s CSV analysis because no CSV was found in %s",
            message_type,
            message_directory,
        )
        return False

    logging.info("Processing %s CSV: %s", message_type, csv_file_path)

    latency_data = read_latency_data(
        csv_file=csv_file_path,
        message_type=message_type,
    )

    if latency_data.empty:
        logging.warning("No usable latency data found in %s", csv_file_path)
        return False

    report_directory = results_dir / "csv" / message_type

    report_summary = create_plots_and_report(
        latency_data,
        report_directory,
        message_type=MESSAGE_ROUTE,
        run_name=run_name,
        max_latency_ms=MAX_LATENCY_MS,
        rolling_window=ROLLING_WINDOW,
        threshold=LATENCY_THRESHOLD_MS,
    )

    logging.info(
        "%s threshold: %s (%d/%d below %.2f ms, %.2f%%)",
        message_type,
        report_summary["threshold_result"],
        report_summary["passed_samples"],
        len(latency_data),
        LATENCY_THRESHOLD_MS,
        report_summary["pass_percent"],
    )

    return True


def run_csv_analysis(
    input_dir: Path,
    results_dir: Path,
) -> int:
    """Analyze all supported CSV types in one run directory."""
    csv_root = input_dir / "csv"

    if not csv_root.is_dir():
        logging.info(
            "Skipping CSV analysis because the directory is missing: %s",
            csv_root,
        )
        return 0

    processed_count = 0
    analysis_failed = False

    # Analyze Radio and SecureV2XMessage
    for message_type in DATA_TYPES:
        try:
            report_created = analyze_message_type(
                csv_root=csv_root,
                results_dir=results_dir,
                run_name=input_dir.name,
                message_type=message_type,
            )

            if report_created:
                processed_count += 1
        except Exception:
            logging.exception(
                "CSV analysis failed for %s in run %s",
                message_type,
                input_dir.name,
            )
            analysis_failed = True

    if processed_count == 0:
        logging.info("No CSV data was processed for run %s", input_dir.name)
    else:
        logging.info(
            "Completed %d CSV analysis type(s) for run %s",
            processed_count,
            input_dir.name,
        )

    return 1 if analysis_failed else 0