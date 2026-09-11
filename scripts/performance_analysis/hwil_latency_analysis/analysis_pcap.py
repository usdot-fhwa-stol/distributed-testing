"""Decode fixed-layout PCAP inputs and analyze V2X message latency."""

import logging
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
import pcapDecode
from plots_and_summaries import (
    calculate_latency,
    read_log_entries,
    results_to_dataframe,
    save_latency_report,
)

MAX_LATENCY_MS = 200.0
ROLLING_WINDOW = 20
PCAP_SUFFIX = ".pcap"

ENDPOINTS = (
    "dut_1",
    "proxy_1",
    "proxy_2",
    "dut_2",
    "v2xhub",
)

CAPTURE_DIRECTIONS = ("tx", "rx")

SUPPORTED_LINKS = (
    ("dut_1", "proxy_1"),
    ("dut_2", "proxy_2"),
    ("proxy_1", "v2xhub"),
    ("proxy_2", "v2xhub"),
    ("dut_1", "dut_2"),
)

LATENCY_THRESHOLDS_MS = {
    ("dut", "dut"): 120.0,
    ("dut", "proxy"): 39.77,
    ("proxy", "dut"): 32.0,
    ("proxy", "v2xhub"): 10.0,
    ("v2xhub", "proxy"): 10.0,
}

LATENCY_COLUMN_CANDIDATES = (
    "latency_ms",
    "latency (ms)",
    "latency",
)


def endpoint_type(endpoint: str) -> str:
    """Convert a numbered endpoint name to its generic threshold type."""
    if endpoint.startswith("dut_"):
        return "dut"

    if endpoint.startswith("proxy_"):
        return "proxy"

    return endpoint


def get_latency_threshold(
    tx_endpoint: str,
    rx_endpoint: str,
) -> float | None:
    """Return the configured latency threshold for a direction."""
    key = (
        endpoint_type(tx_endpoint),
        endpoint_type(rx_endpoint),
    )
    return LATENCY_THRESHOLDS_MS.get(key)


def find_latency_column(dataframe: pd.DataFrame) -> str:
    """Find the latency column without depending on capitalization."""
    normalized_columns = {
        str(column).strip().lower(): str(column)
        for column in dataframe.columns
    }

    for candidate in LATENCY_COLUMN_CANDIDATES:
        if candidate in normalized_columns:
            return normalized_columns[candidate]

    available = ", ".join(str(column) for column in dataframe.columns)

    raise ValueError(
        "Could not identify the latency column. "
        f"Available columns: {available}"
    )


def filename_has_direction(path: Path, direction: str) -> bool:
    """
    Determine whether a PCAP filename identifies a TX or RX capture.

    The filename must contain `tx` or `rx`. Separators are recommended, such
    as `capture_tx.pcap`, but a filename such as `vehicleTX.pcap` also works.
    """
    return direction.lower() in path.stem.lower()


def find_endpoint_capture(
    pcap_root: Path,
    endpoint: str,
    direction: str,
) -> Path | None:
    """
    Find one TX or RX PCAP in an endpoint's fixed input directory.

    Missing files are skipped. Multiple matches are considered ambiguous
    because silently selecting one could produce incorrect latency results.
    """
    endpoint_directory = pcap_root / endpoint

    if not endpoint_directory.is_dir():
        logging.info(
            "PCAP endpoint directory is missing; skipping %s",
            endpoint,
        )
        return None

    matches = sorted(
        (
            path.resolve()
            for path in endpoint_directory.iterdir()
            if path.is_file()
            and path.suffix.lower() == PCAP_SUFFIX
            and filename_has_direction(path, direction)
        ),
        key=lambda path: path.name.lower(),
    )

    if not matches:
        logging.info(
            "No %s PCAP found for %s",
            direction.upper(),
            endpoint,
        )
        return None

    if len(matches) > 1:
        filenames = ", ".join(path.name for path in matches)
        raise ValueError(
            f"Multiple {direction.upper()} PCAP files found for "
            f"{endpoint}: {filenames}"
        )

    return matches[0]


def collect_pcap_inputs(pcap_root: Path) -> dict[str, Path]:
    """Find available endpoint/direction captures using the fixed layout."""
    captures: dict[str, Path] = {}

    for endpoint in ENDPOINTS:
        for direction in CAPTURE_DIRECTIONS:
            capture = find_endpoint_capture(
                pcap_root,
                endpoint,
                direction,
            )

            if capture is None:
                continue

            role = f"{endpoint}_{direction}"
            captures[role] = capture

            logging.info("Found %s PCAP: %s", role, capture)

    return captures


def find_decoder_log(
    decoder_directory: Path,
    pcap_path: Path,
) -> Path:
    """Find the nonempty log created by the external PCAP decoder."""
    preferred_names = (
        f"decoded_{pcap_path.stem}.log",
        f"{pcap_path.stem}.log",
    )

    for filename in preferred_names:
        candidate = decoder_directory / filename

        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate.resolve()

    logs = sorted(
        (
            path.resolve()
            for path in decoder_directory.glob("*.log")
            if path.is_file() and path.stat().st_size > 0
        ),
        key=lambda path: path.name.lower(),
    )

    if len(logs) == 1:
        return logs[0]

    if not logs:
        raise RuntimeError(
            f"The decoder did not create a nonempty log for {pcap_path}"
        )

    raise RuntimeError(
        f"The decoder created multiple possible logs for {pcap_path}: "
        + ", ".join(path.name for path in logs)
    )


def decode_pcap(
    role: str,
    pcap_path: Path,
    decoded_root: Path,
) -> Path:
    """
    Decode one capture into its own role-specific directory.

    Separate directories prevent collisions when several endpoints use common
    filenames such as `tx.pcap` and `rx.pcap`.
    """
    role_directory = decoded_root / role
    saved_log = role_directory / "decoded.log"

    if saved_log.is_file() and saved_log.stat().st_size > 0:
        logging.info("Reusing decoded log for %s: %s", role, saved_log)
        return saved_log.resolve()

    if role_directory.exists():
        shutil.rmtree(role_directory)

    role_directory.mkdir(parents=True, exist_ok=True)

    logging.info("Decoding %s", role)
    pcapDecode.decode_pcap(pcap_path, role_directory)

    generated_log = find_decoder_log(
        role_directory,
        pcap_path,
    )

    # Give every decoded result the same predictable name. The containing
    # role directory identifies which endpoint and direction it belongs to.
    if generated_log != saved_log:
        generated_log.replace(saved_log)

    if not saved_log.is_file() or saved_log.stat().st_size == 0:
        raise RuntimeError(f"Decoded log is missing or empty for {role}")

    return saved_log.resolve()


def evaluate_direction(
    tx_endpoint: str,
    rx_endpoint: str,
    decoded_logs: dict[str, Path],
    results_dir: Path,
    run_name: str,
) -> Path | None:
    """Match TX and RX messages and save one directional latency report."""
    tx_role = f"{tx_endpoint}_tx"
    rx_role = f"{rx_endpoint}_rx"

    # A directional test needs the sender's TX capture and the receiver's RX
    # capture. If either one is unavailable, only this direction is skipped.
    if tx_role not in decoded_logs or rx_role not in decoded_logs:
        logging.info(
            "Skipping %s -> %s because %s or %s is missing",
            tx_endpoint,
            rx_endpoint,
            tx_role,
            rx_role,
        )
        return None

    logging.info("Analyzing %s -> %s", tx_endpoint, rx_endpoint)

    tx_entries = read_log_entries(decoded_logs[tx_role])
    rx_entries = read_log_entries(decoded_logs[rx_role])

    logging.info(
        "Loaded %d TX messages and %d RX messages",
        len(tx_entries),
        len(rx_entries),
    )

    latency_results = calculate_latency(
        tx_entries,
        rx_entries,
    )
    dataframe = results_to_dataframe(latency_results)

    if dataframe.empty:
        logging.warning(
            "No matching messages found for %s -> %s",
            tx_endpoint,
            rx_endpoint,
        )
        return None

    latency_column = find_latency_column(dataframe)
    threshold = get_latency_threshold(
        tx_endpoint,
        rx_endpoint,
    )
    direction_name = f"{tx_endpoint}_to_{rx_endpoint}"
    output_directory = results_dir / "pcap" / direction_name

    summary: dict[str, Any] = save_latency_report(
        dataframe,
        output_directory,
        message_type=f"{tx_endpoint}->{rx_endpoint}",
        run_name=run_name,
        max_latency_ms=MAX_LATENCY_MS,
        rolling_window=ROLLING_WINDOW,
        threshold=threshold,
        latency_column=latency_column,
    )

    if threshold is None:
        logging.info(
            "No threshold is configured for %s -> %s",
            tx_endpoint,
            rx_endpoint,
        )
    else:
        logging.info(
            "%s -> %s threshold: %s "
            "(%d/%d below %.2f ms, %.2f%%)",
            tx_endpoint,
            rx_endpoint,
            summary["threshold_result"],
            summary["passed_samples"],
            len(dataframe),
            threshold,
            summary["pass_percent"],
        )

    return output_directory.resolve()


def run_pcap_analysis(
    input_dir: Path,
    results_dir: Path,
) -> int:
    """Decode and analyze all available PCAP directions for one run."""
    pcap_root = input_dir / "pcap"

    if not pcap_root.is_dir():
        logging.info(
            "Skipping PCAP analysis because the directory is missing",
        )
        return 0

    try:
        captures = collect_pcap_inputs(pcap_root)

        if not captures:
            logging.info("No supported PCAP files found in %s", pcap_root)
            return 0

        decoded_root = results_dir / "decoded"
        decoded_logs: dict[str, Path] = {}

        for role, capture in sorted(captures.items()):
            try:
                decoded_logs[role] = decode_pcap(
                    role=role,
                    pcap_path=capture,
                    decoded_root=decoded_root,
                )
            except Exception:
                # One bad capture should not prevent unrelated endpoint
                # captures from being decoded and analyzed.
                logging.exception("Failed to decode %s", role)

        generated_reports = 0

        for endpoint_a, endpoint_b in SUPPORTED_LINKS:
            for tx_endpoint, rx_endpoint in (
                (endpoint_a, endpoint_b),
                (endpoint_b, endpoint_a),
            ):
                try:
                    output_directory = evaluate_direction(
                        tx_endpoint=tx_endpoint,
                        rx_endpoint=rx_endpoint,
                        decoded_logs=decoded_logs,
                        results_dir=results_dir,
                        run_name=input_dir.name,
                    )

                    if output_directory is not None:
                        generated_reports += 1
                except Exception:
                    logging.exception(
                        "Failed to analyze %s -> %s",
                        tx_endpoint,
                        rx_endpoint,
                    )
                    return 1

        if generated_reports == 0:
            logging.info(
                "No complete PCAP directions were available for run",
            )
        else:
            logging.info(
                "Generated %d PCAP report(s) for run %s",
                generated_reports,
                input_dir.name,
            )

        return 0

    except Exception:
        logging.exception("PCAP analysis failed for run %s", input_dir.name)
        return 1