"""
Bidirectional V2X latency analysis pipeline.

Given one PCAP from Device A and one PCAP from Device B, this script:

1. Decodes each PCAP with the existing pcap decoder.
2. Calculates Device A -> Device B latency.
3. Calculates Device B -> Device A latency.
4. Writes separate CSV files and plots for both directions.
"""

import argparse
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DECODER_SCRIPT = SCRIPT_DIR / "pcapdecoder" / "src" / "pcapDecode.py"
PLOTTING_SCRIPT = SCRIPT_DIR / "radio_latency_plotting.py"


def run_command(command: list[str]) -> None:
    logging.debug("Running: %s", " ".join(command))
    subprocess.run(command, check=True)


def decoder_output_path(input_pcap: Path, decoded_dir: Path) -> Path:
    """Return the filename created by the unmodified pcap decoder.

    This matches decoder_helper.formatFileName():
        'decoded_' + basename.replace('.pcap', '.log')

    Examples:
        device_a.pcap   -> decoded_device_a.log
    """
    decoded_name = f"decoded_{input_pcap.name.replace('.pcap', '.log')}"
    return decoded_dir / decoded_name


def validate_paths(device_a_pcap: Path, device_b_pcap: Path) -> None:
    """Check if files exist"""
    if not device_a_pcap.is_file():
        raise RuntimeError(f"Device A PCAP does not exist: {device_a_pcap}")

    if not device_b_pcap.is_file():
        raise RuntimeError(f"Device B PCAP does not exist: {device_b_pcap}")

    if not DECODER_SCRIPT.is_file():
        raise RuntimeError(f"PCAP decoder was not found: {DECODER_SCRIPT}")

    if not PLOTTING_SCRIPT.is_file():
        raise RuntimeError(f"Plotting script was not found: {PLOTTING_SCRIPT}")


def decode_pcap(
    pcap_file: Path,
    decoded_dir: Path,
    device_label: str,
) -> Path:
    """Decode one PCAP and return its output log path."""
    decoded_dir.mkdir(parents=True, exist_ok=True)

    logging.info("Decoding %s PCAP: %s", device_label, pcap_file)

    run_command(
        [
            sys.executable,
            str(DECODER_SCRIPT),
            "--input-file",
            str(pcap_file),
            "--output-dir",
            str(decoded_dir),
        ]
    )

    decoded_log = decoder_output_path(pcap_file, decoded_dir)

    if not decoded_log.is_file():
        raise RuntimeError(
            f"Expected decoded log was not created for {device_label}:\n  {decoded_log}"
        )

    if decoded_log.stat().st_size == 0:
        logging.warning(
            "%s decoded log is empty: %s",
            device_label,
            decoded_log,
        )

    return decoded_log


def run_analysis(
    transmit_log: Path,
    receive_log: Path,
    output_dir: Path,
    direction_name: str,
    max_latency_ms: int,
    rolling_window: int,
    debug: bool,
) -> None:
    """Run analysis for transmit to receive."""
    output_dir.mkdir(parents=True, exist_ok=True)

    logging.info("Analyzing direction: %s", direction_name)

    command = [
        sys.executable,
        str(PLOTTING_SCRIPT),
        "--transmit-log",
        str(transmit_log),
        "--receive-log",
        str(receive_log),
        "--output-dir",
        str(output_dir),
        "--max-latency-ms",
        str(max_latency_ms),
        "--rolling-window",
        str(rolling_window),
    ]

    if debug:
        command.append("--debug")

    run_command(command)


def main() -> None:
    """Decode two device PCAPs and generate latency graphs bidirectionally."""
    parser = argparse.ArgumentParser(
        description=(
            "Decode Device A and Device B PCAPs and generate bidirectional "
            "V2X latency plots."
        )
    )
    parser.add_argument(
        "--device-a-pcap",
        type=Path,
        required=True,
        help="PCAP captured from Device A's perspective.",
    )
    parser.add_argument(
        "--device-b-pcap",
        type=Path,
        required=True,
        help="PCAP captured from Device B's perspective.",
    )
    parser.add_argument(
        "--device-a-name",
        default="device_a",
        help="Output label for Device A. Default: device_a.",
    )
    parser.add_argument(
        "--device-b-name",
        default="device_b",
        help="Output label for Device B. Default: device_b.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Root directory for decoded logs, analysis data, and plots.",
    )
    parser.add_argument(
        "--max-latency-ms",
        type=int,
        default=200,
        help="Maximum displayed histogram/CDF latency. Default: 200.",
    )
    parser.add_argument(
        "--rolling-window",
        type=int,
        default=20,
        help="Rolling-mean window in samples. Default: 20.",
    )
    parser.add_argument(
        "--skip-decode",
        action="store_true",
        help=(
            "Use existing decoded logs in the output directory rather than "
            "running pcapDecode.py again."
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose logging.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if args.max_latency_ms <= 0:
        parser.error("--max-latency-ms must be greater than zero.")

    if args.rolling_window <= 0:
        parser.error("--rolling-window must be greater than zero.")

    try:
        device_a_pcap = args.device_a_pcap.resolve()
        device_b_pcap = args.device_b_pcap.resolve()
        output_dir = args.output_dir.resolve()

        validate_paths(device_a_pcap, device_b_pcap)

        decoded_root = output_dir / "decoded"

        device_a_decoded_dir = decoded_root / args.device_a_name
        device_b_decoded_dir = decoded_root / args.device_b_name

        expected_device_a_log = decoder_output_path(
            device_a_pcap,
            device_a_decoded_dir,
        )
        expected_device_b_log = decoder_output_path(
            device_b_pcap,
            device_b_decoded_dir,
        )

        if args.skip_decode:
            device_a_log = expected_device_a_log
            device_b_log = expected_device_b_log

            if not device_a_log.is_file():
                raise RuntimeError(
                    f"Device A decoded log was not found: {device_a_log}"
                )

            if not device_b_log.is_file():
                raise RuntimeError(
                    f"Device B decoded log was not found: {device_b_log}"
                )

            logging.info("Skipping PCAP decoding.")
        else:
            device_a_log = decode_pcap(
                device_a_pcap,
                device_a_decoded_dir,
                args.device_a_name,
            )
            device_b_log = decode_pcap(
                device_b_pcap,
                device_b_decoded_dir,
                args.device_b_name,
            )

        a_to_b_name = f"{args.device_a_name}_to_{args.device_b_name}"
        b_to_a_name = f"{args.device_b_name}_to_{args.device_a_name}"

        run_analysis(
            transmit_log=device_a_log,
            receive_log=device_b_log,
            output_dir=output_dir / a_to_b_name,
            direction_name=a_to_b_name,
            max_latency_ms=args.max_latency_ms,
            rolling_window=args.rolling_window,
            debug=args.debug,
        )

        run_analysis(
            transmit_log=device_b_log,
            receive_log=device_a_log,
            output_dir=output_dir / b_to_a_name,
            direction_name=b_to_a_name,
            max_latency_ms=args.max_latency_ms,
            rolling_window=args.rolling_window,
            debug=args.debug,
        )

        print()
        print("Bidirectional latency analysis complete.")
        print(f"Output directory: {output_dir}")
        print()
        print(f"{a_to_b_name}:")
        print(f"  CSV:   {output_dir / a_to_b_name / 'data' / 'latency_results.csv'}")
        print(f"  Plots: {output_dir / a_to_b_name / 'plots'}")
        print()
        print(f"{b_to_a_name}:")
        print(f"  CSV:   {output_dir / b_to_a_name / 'data' / 'latency_results.csv'}")
        print(f"  Plots: {output_dir / b_to_a_name / 'plots'}")

    except subprocess.CalledProcessError as error:
        logging.error(
            "Command failed with exit code %d: %s",
            error.returncode,
            " ".join(str(item) for item in error.cmd),
        )
        sys.exit(error.returncode)

    except RuntimeError as error:
        logging.error("%s", error)
        sys.exit(1)


if __name__ == "__main__":
    main()
