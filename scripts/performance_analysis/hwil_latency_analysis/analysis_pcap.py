"""Decode fixed-layout PCAP inputs and analyze V2X message latency."""

import logging
import shutil
from pathlib import Path

import pcapDecode
from plots_and_summaries import (
    calculate_latency,
    create_plots_and_report,
    read_log_entries,
    results_to_dataframe,
)

MAX_LATENCY_MS = 200.0
ROLLING_WINDOW = 20

ENDPOINTS = (
    "dut_1",
    "proxy_1",
    "proxy_2",
    "dut_2",
    "v2xhub_1",
    "v2xhub_2",
)

CAPTURE_DIRECTIONS = ("tx", "rx")

SUPPORTED_LINKS = (
    ("dut_1", "proxy_1"),
    ("dut_2", "proxy_2"),
    ("proxy_1", "v2xhub_1"),
    ("proxy_2", "v2xhub_2"),
    ("dut_1", "dut_2"),
)

LATENCY_THRESHOLDS_MS = {
    ("dut", "dut"): 120.0,
    ("dut", "proxy"): 39.77,
    ("proxy", "dut"): 32.0,
    ("proxy", "v2xhub"): 10.0,
    ("v2xhub", "proxy"): 10.0,
}


def get_endpoint_type(endpoint: str) -> str:
    """Remove the endpoint number used in the input folder name."""
    # Ex: Retrieve dut from dut_1
    return endpoint.rsplit("_", maxsplit=1)[0]


def get_latency_threshold(
    tx_endpoint: str,
    rx_endpoint: str,
) -> float | None:
    """Return the configured latency threshold for a direction."""
    # Retrieve threshold value based tuple of transmit or recieve key
    endpoint_types = (
        get_endpoint_type(tx_endpoint),
        get_endpoint_type(rx_endpoint),
    )
    return LATENCY_THRESHOLDS_MS.get(endpoint_types)


def filename_has_direction(path: Path, direction: str) -> bool:
    """Check whether a PCAP filename ends with TX or RX."""
    return path.stem.lower().endswith(direction)


def get_pcap(
    pcap_root: Path,
    endpoint: str,
    direction: str,
) -> Path | None:
    """Find a TX or RX PCAP in an endpoint directory."""
    endpoint_directory = pcap_root / endpoint

    if not endpoint_directory.is_dir():
        logging.info(
            "PCAP endpoint directory is missing; skipping %s",
            endpoint,
        )
        return None

    # Search through all tx and rx files in the endpoint directory and
    # check for the one that matches our end point and direction.
    matches = sorted(
        (
            path.resolve()
            for path in endpoint_directory.iterdir()
            if path.is_file()
            and path.suffix.lower() == ".pcap"
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

    # Multiple matching files make it unclear which capture should be used.
    if len(matches) > 1:
        filenames = ", ".join(path.name for path in matches)
        raise ValueError(
            f"Multiple {direction.upper()} PCAP files found for {endpoint}: {filenames}"
        )

    return matches[0]


def get_pcaps(pcap_root: Path) -> dict[str, Path]:
    """Find all available transmit and recieve pcaps."""
    pcap_files: dict[str, Path] = {}

    # Iterate over tx and rx for all endpoints
    for endpoint in ENDPOINTS:
        for direction in CAPTURE_DIRECTIONS:
            path = get_pcap(
                pcap_root=pcap_root,
                endpoint=endpoint,
                direction=direction,
            )

            if path is None:
                continue

            name = f"{endpoint}_{direction}"
            # Link file name and file path in a dictionary
            pcap_files[name] = path

            logging.info(
                "Found %s PCAP: %s",
                name,
                path,
            )

    return pcap_files


def decode_pcap(
    pcap_name: str,
    pcap_path: Path,
    decoded_root: Path,
) -> Path:
    """Decode one PCAP into its own output directory."""
    output_directory = decoded_root / pcap_name
    decoded_log = output_directory / "decoded.log"

    # Remove the previous output so every PCAP is decoded from scratch.
    if output_directory.exists():
        shutil.rmtree(output_directory)

    output_directory.mkdir(parents=True)

    logging.info("Decoding %s", pcap_name)
    pcapDecode.decode_pcap(pcap_path, output_directory)

    return decoded_log.resolve()


def analyze_direction(
    tx_endpoint: str,
    rx_endpoint: str,
    decoded_logs: dict[str, Path],
    results_dir: Path,
    run_name: str,
) -> Path | None:
    """Match TX and RX messages and save a latency report."""
    tx_capture_name = f"{tx_endpoint}_tx"
    rx_capture_name = f"{rx_endpoint}_rx"

    # A direction needs both the sender's TX and the receiver's RX pcap.
    if tx_capture_name not in decoded_logs or rx_capture_name not in decoded_logs:
        logging.info(
            "Skipping %s -> %s because %s or %s is missing",
            tx_endpoint,
            rx_endpoint,
            tx_capture_name,
            rx_capture_name,
        )
        return None

    logging.info("Analyzing %s -> %s", tx_endpoint, rx_endpoint)

    tx_entries = read_log_entries(decoded_logs[tx_capture_name])
    rx_entries = read_log_entries(decoded_logs[rx_capture_name])

    logging.info(
        "Loaded %d TX messages and %d RX messages",
        len(tx_entries),
        len(rx_entries),
    )

    latency_results = calculate_latency(
        tx_entries,
        rx_entries,
    )
    latency_data = results_to_dataframe(latency_results)

    if latency_data.empty:
        logging.warning(
            "No matching messages found for %s -> %s",
            tx_endpoint,
            rx_endpoint,
        )
        return None

    threshold = get_latency_threshold(
        tx_endpoint,
        rx_endpoint,
    )
    direction_name = f"{tx_endpoint}_to_{rx_endpoint}"
    report_directory = results_dir / "pcap" / direction_name

    # Generate timeseries, cdf and histogram for latency data. Also a summary of statistics and success status
    report_summary = create_plots_and_report(
        latency_data,
        report_directory,
        message_type=f"{tx_endpoint}->{rx_endpoint}",
        run_name=run_name,
        max_latency_ms=MAX_LATENCY_MS,
        rolling_window=ROLLING_WINDOW,
        threshold=threshold,
    )

    if threshold is None:
        logging.info(
            "No threshold is configured for %s -> %s",
            tx_endpoint,
            rx_endpoint,
        )
    else:
        logging.info(
            "%s -> %s threshold: %s (%d/%d below %.2f ms, %.2f%%)",
            tx_endpoint,
            rx_endpoint,
            report_summary["threshold_result"],
            report_summary["passed_samples"],
            len(latency_data),
            threshold,
            report_summary["pass_percent"],
        )

    return report_directory.resolve()


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
        captures = get_pcaps(pcap_root)

        if not captures:
            logging.info(
                "No supported PCAP files found in %s",
                pcap_root,
            )
            return 0

        # Decoded logs are raw text files with JSON formatted stringes of message data
        # They are always outputted and are whats processed for the actual analysis
        decoded_root = results_dir / "decoded"
        decoded_logs: dict[str, Path] = {}
        analysis_failed = False

        for capture_name, capture_path in sorted(captures.items()):
            # Process one log at a time, mark a failure but dont stop analysis
            try:
                decoded_logs[capture_name] = decode_pcap(
                    pcap_name=capture_name,
                    pcap_file_path=capture_path,
                    decoded_root=decoded_root,
                )
            except Exception:
                logging.exception(
                    "Failed to decode %s",
                    capture_name,
                )
                analysis_failed = True

        report_count = 0

        for endpoint_a, endpoint_b in SUPPORTED_LINKS:
            # Analyze bidirectionally
            directions = (
                (endpoint_a, endpoint_b),
                (endpoint_b, endpoint_a),
            )

            for tx_endpoint, rx_endpoint in directions:
                try:
                    report_directory = analyze_direction(
                        tx_endpoint=tx_endpoint,
                        rx_endpoint=rx_endpoint,
                        decoded_logs=decoded_logs,
                        results_dir=results_dir,
                        run_name=input_dir.name,
                    )

                    if report_directory is not None:
                        report_count += 1
                except Exception:
                    # Keep processing so one failure does not block other reports.
                    logging.exception(
                        "Failed to analyze %s -> %s",
                        tx_endpoint,
                        rx_endpoint,
                    )
                    analysis_failed = True

        if report_count == 0:
            logging.info(
                "No complete PCAP directions were available for run",
            )
        else:
            logging.info(
                "Generated %d PCAP report(s) for run %s",
                report_count,
                input_dir.name,
            )

        return 1 if analysis_failed else 0

    except Exception:
        logging.exception(
            "PCAP analysis failed for run %s",
            input_dir.name,
        )
        return 1
