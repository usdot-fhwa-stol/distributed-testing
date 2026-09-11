"""Analyze Radio and SecureV2XMessage CSV latency data."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from plots_and_summaries import save_latency_report

# Plot and threshold settings are constants instead of command-line options.
MAX_LATENCY_MS = 200.0
ROLLING_WINDOW = 20
LATENCY_THRESHOLD_MS = 10.0

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
        "skip_events": set(),
    },
}


@dataclass(frozen=True, slots=True)
class LogRecord:
    """One usable CSV message and its calculated latency."""

    tx_time_ms: float
    rx_time_ms: float
    latency_ms: float
    match_key: str
    row_id: str
    ip_address: str


def clean_value(value: Any) -> str:
    """Convert a missing value to an empty string and trim other values."""
    if value is None or pd.isna(value):
        return ""

    return str(value).strip()


def normalize_timestamp_ms(value: Any) -> float:
    """
    Convert a timestamp to milliseconds.

    The source CSVs may contain timestamps in seconds, milliseconds,
    microseconds, or nanoseconds. Their size is used to determine the unit.
    """
    numeric = float(value)

    if not np.isfinite(numeric):
        raise ValueError("Timestamp is not finite")

    magnitude = abs(numeric)

    if magnitude >= 1e17:
        return numeric / 1e6

    if magnitude >= 1e14:
        return numeric / 1e3

    if 1e8 <= magnitude < 1e11:
        return numeric * 1e3

    return numeric


def extract_host(value: Any) -> str:
    """
    Extract the hostname or IP address from an endpoint value.

    Examples:
        http://1.2.3.4:8080 -> 1.2.3.4
        [2001:db8::1]:8080 -> 2001:db8::1
    """
    endpoint = clean_value(value)

    if not endpoint:
        return ""

    endpoint = re.sub(
        r"^[A-Za-z][A-Za-z0-9+.-]*://",
        "",
        endpoint,
    )

    if endpoint.startswith("["):
        closing_bracket = endpoint.find("]")

        if closing_bracket != -1:
            return endpoint[1:closing_bracket]

    if endpoint.count(":") == 1:
        return endpoint.rsplit(":", maxsplit=1)[0]

    return endpoint


def find_csv_file(
    directory: Path,
    patterns: Iterable[str],
) -> Path | None:
    """
    Find one CSV using the configured filename patterns.

    Patterns are checked from most specific to least specific. If a pattern
    matches multiple files, the first alphabetically sorted file is used and
    a warning is logged.
    """
    if not directory.is_dir():
        logging.info("CSV directory is missing; skipping: %s", directory)
        return None

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


def find_first_column(
    df: pd.DataFrame,
    candidates: Iterable[str],
) -> str | None:
    """Return the first candidate column that exists in the DataFrame."""
    return next(
        (column for column in candidates if column in df.columns),
        None,
    )


def read_records(
    csv_file: Path,
    message_type: str,
) -> list[LogRecord]:
    """Read usable latency records from one CSV."""
    config = DATA_TYPES[message_type]

    try:
        df = pd.read_csv(
            csv_file,
            dtype=str,
            low_memory=False,
        )
    except (
        OSError,
        pd.errors.EmptyDataError,
        pd.errors.ParserError,
        UnicodeDecodeError,
    ) as error:
        logging.error("Failed to read %s: %s", csv_file, error)
        return []

    tx_column = find_first_column(
        df,
        (
            "Metadata,TimeOfTransmission",
            "Metadata,TimeOfCommit",
            "const^Metadata,TimeOfCreation",
        ),
    )
    rx_column = find_first_column(
        df,
        (
            "Metadata,TimeOfReceipt",
            "packetTimestamp",
        ),
    )

    if tx_column is None or rx_column is None:
        logging.warning(
            "Skipping %s because its TX or RX timestamp column is missing",
            csv_file,
        )
        return []

    event_column = "Metadata,Enum,Middleware::EventType"
    skip_events = config["skip_events"]

    if event_column in df.columns and skip_events:
        df = df.loc[~df[event_column].isin(skip_events)]

    ip_column = find_first_column(
        df,
        (
            "const^Metadata,SDOid.hostIPaddress",
            "Metadata,Endpoint",
            "const^Metadata,Endpoint",
        ),
    )

    available_id_columns = [
        column
        for column in config["id_cols"]
        if column in df.columns
    ]

    records: list[LogRecord] = []

    for row_index, row in df.iterrows():
        try:
            tx_time_ms = normalize_timestamp_ms(row[tx_column])
            rx_time_ms = normalize_timestamp_ms(row[rx_column])
        except (TypeError, ValueError, OverflowError):
            # A malformed timestamp only invalidates this row, not the whole
            # file, so continue processing the remaining rows.
            continue

        key_parts = [
            value
            for column in available_id_columns
            if (value := clean_value(row.get(column)))
        ]

        row_id = clean_value(row.get("rowID")) or str(row_index)

        if key_parts:
            match_key = f"{message_type}::{'::'.join(key_parts)}"
        else:
            match_key = f"{message_type}::row::{row_id}"

        ip_address = (
            extract_host(row.get(ip_column))
            if ip_column is not None
            else ""
        )

        records.append(
            LogRecord(
                tx_time_ms=tx_time_ms,
                rx_time_ms=rx_time_ms,
                latency_ms=rx_time_ms - tx_time_ms,
                match_key=match_key,
                row_id=row_id,
                ip_address=ip_address,
            )
        )

    return sorted(
        records,
        key=lambda record: (
            record.tx_time_ms,
            record.rx_time_ms,
        ),
    )


def records_to_dataframe(records: list[LogRecord]) -> pd.DataFrame:
    """Convert valid, non-negative latency records into a DataFrame."""
    rows = []

    for record in records:
        if not np.isfinite(record.latency_ms):
            continue

        if record.latency_ms < 0:
            continue

        rows.append(
            {
                "Tx Timestamp (ms)": record.tx_time_ms,
                "Rx Timestamp (ms)": record.rx_time_ms,
                "Latency (ms)": record.latency_ms,
                "Match Key": record.match_key,
                "Row ID": record.row_id,
                "IP Address": record.ip_address,
                "Datetime": pd.to_datetime(
                    record.tx_time_ms,
                    unit="ms",
                    utc=True,
                    errors="coerce",
                ),
            }
        )

    return pd.DataFrame(rows)


def analyze_csv_type(
    csv_root: Path,
    results_dir: Path,
    run_name: str,
    message_type: str,
) -> bool:
    """
    Analyze one configured CSV type.

    Returns True when a report was generated and False when the input was
    missing or did not contain usable records.
    """
    config = DATA_TYPES[message_type]
    input_directory = csv_root / message_type

    csv_file = find_csv_file(
        input_directory,
        config["patterns"],
    )

    if csv_file is None:
        logging.info(
            "Skipping %s CSV analysis because no CSV was found in %s",
            message_type,
            input_directory,
        )
        return False

    logging.info("Processing %s CSV: %s", message_type, csv_file)

    records = read_records(csv_file, message_type)

    if not records:
        logging.warning("No usable records found in %s", csv_file)
        return False

    dataframe = records_to_dataframe(records)

    if dataframe.empty:
        logging.warning(
            "No valid non-negative latency values found in %s",
            csv_file,
        )
        return False

    output_directory = results_dir / "csv" / message_type

    
    endpoint_and_direction = "v2xhub->dt_plugin"
    

    summary = save_latency_report(
        dataframe,
        output_directory,
        message_type=endpoint_and_direction,
        run_name=run_name,
        max_latency_ms=MAX_LATENCY_MS,
        rolling_window=ROLLING_WINDOW,
        threshold=LATENCY_THRESHOLD_MS,
    )

    logging.info(
        "%s threshold: %s (%d/%d below %.2f ms, %.2f%%)",
        message_type,
        summary["threshold_result"],
        summary["passed_samples"],
        len(dataframe),
        LATENCY_THRESHOLD_MS,
        summary["pass_percent"],
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

    for message_type in DATA_TYPES:
        try:
            if analyze_csv_type(
                csv_root=csv_root,
                results_dir=results_dir,
                run_name=input_dir.name,
                message_type=message_type,
            ):
                processed_count += 1
        except Exception:
            logging.exception(
                "CSV analysis failed for %s in run %s",
                message_type,
                input_dir.name,
            )
            return 1

    if processed_count == 0:
        logging.info("No CSV data was processed for run %s", input_dir.name)
    else:
        logging.info(
            "Completed %d CSV analysis type(s) for run %s",
            processed_count,
            input_dir.name,
        )

    return 0