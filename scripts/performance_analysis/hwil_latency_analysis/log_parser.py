"""Read timestamped JSON messages and calculate TX-to-RX latency."""

import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import pandas as pd


def read_log_entries(log_file: Path) -> list[tuple[int, dict[str, Any]]]:
    """Read lines formatted as: TIMESTAMP : JSON_PAYLOAD."""
    entries = []

    with log_file.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                # Split once because the JSON itself contains colons.
                timestamp_text, payload_text = line.split(":", maxsplit=1)

                timestamp_ms = int(timestamp_text.strip())
                payload = json.loads(payload_text.strip())
            except (ValueError, json.JSONDecodeError) as error:
                print(f"Skipping line {line_number}: {error}")
                continue

            entries.append((timestamp_ms, payload))

    return entries


def message_key(payload: dict[str, Any]) -> str:
    """Create a consistent string for comparing two JSON payloads."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )


def calculate_latency(
    tx_entries: list[tuple[int, dict[str, Any]]],
    rx_entries: list[tuple[int, dict[str, Any]]],
) -> pd.DataFrame:
    """Match identical TX/RX payloads and calculate their latency."""
    rx_messages = defaultdict(deque)

    # Sort by the timestamp.
    for rx_time, payload in sorted(
        rx_entries,
        key=lambda entry: entry[0],
    ):
        rx_messages[message_key(payload)].append(rx_time)

    results = []

    for tx_time, payload in sorted(
        tx_entries,
        key=lambda entry: entry[0],
    ):
        timestamps = rx_messages.get(message_key(payload))

        if not timestamps:
            continue

        # Discard matching RX messages that occurred before this TX message.
        while timestamps and timestamps[0] < tx_time:
            timestamps.popleft()

        if not timestamps:
            continue

        # Use the earliest unused RX message with the same complete payload.
        rx_time = timestamps.popleft()

        results.append(
            {
                "Tx Timestamp (ms)": tx_time,
                "Rx Timestamp (ms)": rx_time,
                "Latency (ms)": rx_time - tx_time,
            }
        )

    dataframe = pd.DataFrame(
        results,
        columns=[
            "Tx Timestamp (ms)",
            "Rx Timestamp (ms)",
            "Latency (ms)",
        ],
    )

    dataframe["Datetime"] = pd.to_datetime(
        dataframe["Tx Timestamp (ms)"],
        unit="ms",
        utc=True,
    )

    return dataframe