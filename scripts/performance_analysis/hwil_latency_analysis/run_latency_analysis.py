"""Decode PCAPs and run V2X messaging-performance analysis.

Raw PCAP names are automatically discovered from file names. 

    dut_1_tx, dut_1_rx
    proxy_1_tx, proxy_1_rx
    proxy_2_tx, proxy_2_rx
    dut_2_tx, dut_2_rx
    v2xhub_tx, v2xhub_rx

Hyphens and expanded direction names are accepted. Examples:

    dut_1_tx_rmnet.pcap
    dut-1-receive.pcapng
    proxy_1_transmit_eth0.pcap
    v2xhub-rx.pcap

You can set command-line arguments to manually control which devices are which.  

Pipeline:

    PCAP -> pcapDecode.py -> decoded/*.log
         -> v2xhub_messaging_performance_analyzer.py -> results/*/plots/*.png

Default output structure:

    run_001/
        decoded/
            decoded_dut_1_tx_rmnet.log
            decoded_proxy_1_rx_eth0.log
            ...
        results/
            dut_1_to_proxy_1/
                data/
                    latency_results.csv
                plots/
                    latency_histogram.png
                    latency_cdf.png
                    latency_timeseries.png
            proxy_1_to_dut_1/
                ...
        run_manifest.json

Supported analysis:

    dut_1 <-> proxy_1
    dut_2 <-> proxy_2
    proxy_1 <-> v2xhub
    proxy_2 <-> v2xhub
    dut_1 <-> dut_2

Use --name DIRECTION=FOLDER_NAME to customize individual result sub-folders:

    --name dut_1_to_proxy_1=side_1_local
    --name dut_1_to_dut_2=end_to_end
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DECODER_SCRIPT = SCRIPT_DIR / "pcapdecoder" / "src" / "pcapDecode.py"
DEFAULT_PLOTTER_SCRIPT = SCRIPT_DIR / "radio_latency_plotting.py"

PCAP_SUFFIXES = {".pcap", ".pcapng"}
SQLITE_SUFFIXES = {".db", ".db3", ".sqlite", ".sqlite3"}

ENDPOINTS = (
    "dut_1",
    "proxy_1",
    "proxy_2",
    "dut_2",
    "v2xhub",
)

CAPTURE_DIRECTIONS = ("tx", "rx")

PCAP_ROLES = tuple(
    f"{endpoint}_{direction}"
    for endpoint in ENDPOINTS
    for direction in CAPTURE_DIRECTIONS
)

SUPPORTED_LINKS = (
    ("dut_1", "proxy_1"),
    ("dut_2", "proxy_2"),
    ("proxy_1", "v2xhub"),
    ("proxy_2", "v2xhub"),
    ("dut_1", "dut_2"),
)

ENDPOINT_PATTERNS = {
    "dut_1": r"dut[_-]?1",
    "proxy_1": r"proxy[_-]?1",
    "proxy_2": r"proxy[_-]?2",
    "dut_2": r"dut[_-]?2",
    "v2xhub": r"v2x[_-]?hub|v2xhub",
}

DIRECTION_PATTERNS = {
    "tx": r"tx|transmit",
    "rx": r"rx|receive",
}

EXPECTED_PLOT_FILENAMES = (
    "latency_histogram.png",
    "latency_cdf.png",
    "latency_timeseries.png",
)


def run_command(command: list[str]) -> None:
    """Run a subprocess and raise an exception on failure."""
    logging.debug("Running command: %s", shlex.join(command))
    subprocess.run(command, check=True)


def validate_helper_script(path: Path, description: str) -> None:
    """Verify a required helper script exists."""
    if not path.is_file():
        raise FileNotFoundError(f"{description} not found: {path}")


def validate_pcap(role: str, path: Path) -> None:
    """Verify a PCAP path exists and has a supported file extension."""
    if not path.is_file():
        raise FileNotFoundError(
            f"PCAP assigned to {role} does not exist: {path}"
        )

    if path.suffix.lower() not in PCAP_SUFFIXES:
        suffixes = ", ".join(sorted(PCAP_SUFFIXES))
        raise ValueError(
            f"Unsupported PCAP type for {role}: {path}. "
            f"Expected one of: {suffixes}"
        )


def role_parts(role: str) -> tuple[str, str]:
    """Split a PCAP role into endpoint and capture direction."""
    endpoint, direction = role.rsplit("_", maxsplit=1)
    return endpoint, direction


def cli_option_name(role: str) -> str:
    """Return the command-line option name for a PCAP role."""
    return f"--{role.replace('_', '-')}"


def decoded_log_name(pcap_path: Path) -> str:
    """Return the expected filename produced by pcapDecode.py."""
    return f"decoded_{pcap_path.stem}.log"


def make_role_pattern(role: str) -> re.Pattern[str]:
    """Build a PCAP filename matching pattern for one endpoint-direction."""
    endpoint, direction = role_parts(role)
    endpoint_pattern = ENDPOINT_PATTERNS[endpoint]
    direction_pattern = DIRECTION_PATTERNS[direction]

    return re.compile(
        rf"(?:^|[^a-z0-9])(?:{endpoint_pattern})"
        rf"(?:[^a-z0-9])(?:{direction_pattern})(?:[^a-z0-9]|$)",
        re.IGNORECASE,
    )


def find_pcap_candidates(input_dir: Path, role: str) -> list[Path]:
    """Find all PCAP files that match a particular role."""
    pattern = make_role_pattern(role)

    return sorted(
        (
            path.resolve()
            for path in input_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in PCAP_SUFFIXES
            and pattern.search(path.stem)
        ),
        key=lambda path: path.name.lower(),
    )


def discover_role_pcap(input_dir: Path, role: str) -> Path | None:
    """Discover exactly one PCAP for a role, if one is present."""
    candidates = find_pcap_candidates(input_dir, role)

    if not candidates:
        logging.info("No PCAP automatically discovered for %s", role)
        return None

    if len(candidates) > 1:
        candidate_list = "\n".join(f"  - {path}" for path in candidates)
        raise ValueError(
            f"Multiple PCAP files matched {role}:\n"
            f"{candidate_list}\n"
            f"Choose one explicitly with {cli_option_name(role)}."
        )

    logging.info("Automatically discovered %s: %s", role, candidates[0].name)
    return candidates[0]


def resolve_explicit_path(value: Path, input_dir: Path) -> Path:
    """Resolve an explicit path relative to input directory, then CWD."""
    value = value.expanduser()

    if value.is_absolute():
        return value.resolve()

    input_relative = input_dir / value

    if input_relative.is_file():
        return input_relative.resolve()

    return value.resolve()


def collect_pcap_inputs(
    args: argparse.Namespace,
    input_dir: Path,
) -> dict[str, Path]:
    """Collect explicitly selected and automatically discovered PCAP files."""
    inputs: dict[str, Path] = {}
    assigned_paths: dict[Path, str] = {}

    for role in PCAP_ROLES:
        explicit_value = getattr(args, role)

        if explicit_value is not None:
            path = resolve_explicit_path(explicit_value, input_dir)
            logging.info("Using explicit %s PCAP: %s", role, path)
        else:
            path = discover_role_pcap(input_dir, role)

        if path is None:
            continue

        validate_pcap(role, path)

        if path in assigned_paths:
            other_role = assigned_paths[path]
            raise ValueError(
                f"The same PCAP is assigned to both {other_role} and {role}: "
                f"{path}"
            )

        assigned_paths[path] = role
        inputs[role] = path

    return inputs


def discover_sqlite_inputs(input_dir: Path) -> list[Path]:
    """Find SQLite files in the input directory for the run manifest."""
    return sorted(
        (
            path.resolve()
            for path in input_dir.iterdir()
            if path.is_file() and path.suffix.lower() in SQLITE_SUFFIXES
        ),
        key=lambda path: path.name.lower(),
    )


def locate_decoder_output(
    decoded_dir: Path,
    pcap_path: Path,
    expected_output: Path,
) -> Path:
    """Locate the decoded log specifically associated with a PCAP.

    The decoded directory is shared across all roles, so this deliberately
    does not fall back to an arbitrary .log file in the directory.
    """
    if expected_output.is_file() and expected_output.stat().st_size > 0:
        return expected_output.resolve()

    alternative_names = (
        f"decoded_{pcap_path.stem}.log",
        f"{pcap_path.stem}.log",
    )

    for filename in alternative_names:
        candidate = decoded_dir / filename

        if candidate.is_file() and candidate.stat().st_size > 0:
            logging.warning(
                "Decoder output filename differed from expectation; using %s",
                candidate,
            )
            return candidate.resolve()

    raise RuntimeError(
        "The decoder completed without creating an identifiable nonempty "
        f"log for {pcap_path}. Expected: {expected_output}"
    )


def decode_pcap(
    role: str,
    pcap_path: Path,
    decoded_dir: Path,
    decoder_script: Path,
    force_decode: bool,
) -> Path:
    """Decode one PCAP into the shared decoded output directory."""
    decoded_dir.mkdir(parents=True, exist_ok=True)

    expected_output = decoded_dir / decoded_log_name(pcap_path)

    if (
        not force_decode
        and expected_output.is_file()
        and expected_output.stat().st_size > 0
    ):
        logging.info("Reusing decoded %s log: %s", role, expected_output)
        return expected_output.resolve()

    # Do not leave a stale expected file that could make a failed decoding run
    # appear successful.
    if expected_output.is_file():
        logging.debug("Removing old decoded log: %s", expected_output)
        expected_output.unlink()

    logging.info("Decoding %s: %s", role, pcap_path.name)

    run_command(
        [
            sys.executable,
            str(decoder_script),
            "--input-file",
            str(pcap_path),
            "--output-dir",
            str(decoded_dir),
        ]
    )

    decoded_log = locate_decoder_output(
        decoded_dir=decoded_dir,
        pcap_path=pcap_path,
        expected_output=expected_output,
    )

    logging.info("Decoded %s log: %s", role, decoded_log)
    return decoded_log


def supported_direction_names() -> set[str]:
    """Return every supported source-to-destination analysis direction."""
    directions: set[str] = set()

    for endpoint_a, endpoint_b in SUPPORTED_LINKS:
        directions.add(f"{endpoint_a}_to_{endpoint_b}")
        directions.add(f"{endpoint_b}_to_{endpoint_a}")

    return directions


def parse_custom_result_names(values: list[str]) -> dict[str, str]:
    """Parse repeated --name DIRECTION=FOLDER_NAME values."""
    valid_directions = supported_direction_names()
    custom_names: dict[str, str] = {}

    for value in values:
        if "=" not in value:
            raise ValueError(
                f"Invalid --name value {value!r}. "
                "Expected DIRECTION=FOLDER_NAME."
            )

        direction, folder_name = value.split("=", maxsplit=1)
        direction = direction.strip()
        folder_name = folder_name.strip()

        if direction not in valid_directions:
            valid_direction_text = ", ".join(sorted(valid_directions))
            raise ValueError(
                f"Unknown direction {direction!r} in --name. "
                f"Valid directions: {valid_direction_text}"
            )

        if not folder_name:
            raise ValueError(
                f"Result folder name cannot be empty for {direction!r}."
            )

        if Path(folder_name).name != folder_name:
            raise ValueError(
                "Result folder name must not contain path separators: "
                f"{folder_name!r}"
            )

        if folder_name in custom_names.values():
            raise ValueError(
                f"Custom result folder name is duplicated: {folder_name!r}"
            )

        custom_names[direction] = folder_name

    return custom_names


def verify_plot_outputs(output_dir: Path) -> None:
    """Ensure the analyzer/plotter created all expected PNG plot artifacts."""
    plots_dir = output_dir / "plots"

    missing_plots = [
        plots_dir / filename
        for filename in EXPECTED_PLOT_FILENAMES
        if not (plots_dir / filename).is_file()
    ]

    if missing_plots:
        missing_text = "\n".join(f"  - {path}" for path in missing_plots)
        raise RuntimeError(
            "The plotter script completed but did not generate the expected "
            f"plot files:\n{missing_text}\n"
            "This commonly means the TX and RX logs contained no matching "
            "messages."
        )


def evaluate_direction(
    tx_endpoint: str,
    rx_endpoint: str,
    decoded_logs: dict[str, Path],
    results_dir: Path,
    plotter_script: Path,
    custom_result_names: dict[str, str],
    max_latency_ms: int,
    rolling_window: int,
    debug: bool,
) -> Path | None:
    """Run the analyzer/plotter for one source-to-destination direction."""
    tx_role = f"{tx_endpoint}_tx"
    rx_role = f"{rx_endpoint}_rx"

    if tx_role not in decoded_logs or rx_role not in decoded_logs:
        logging.info(
            "Skipping %s -> %s because %s or %s is missing",
            tx_endpoint,
            rx_endpoint,
            tx_role,
            rx_role,
        )
        return None

    direction_name = f"{tx_endpoint}_to_{rx_endpoint}"
    folder_name = custom_result_names.get(direction_name, direction_name)
    output_dir = results_dir / folder_name
    output_dir.mkdir(parents=True, exist_ok=True)

    logging.info("Analyzing and plotting %s -> %s", tx_endpoint, rx_endpoint)

    # This invokes v2xhub_messaging_performance_analyzer.py, which:
    #   1. matches TX/RX messages in the decoded logs,
    #   2. writes data/latency_results.csv,
    #   3. generates plots/latency_histogram.png,
    #   4. generates plots/latency_cdf.png, and
    #   5. generates plots/latency_timeseries.png.
    command = [
        sys.executable,
        str(plotter_script),
        "--transmit-log",
        str(decoded_logs[tx_role]),
        "--receive-log",
        str(decoded_logs[rx_role]),
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
    verify_plot_outputs(output_dir)

    logging.info("Plots written to: %s", output_dir / "plots")
    return output_dir.resolve()


def evaluate_bidirectional(
    endpoint_a: str,
    endpoint_b: str,
    decoded_logs: dict[str, Path],
    results_dir: Path,
    plotter_script: Path,
    custom_result_names: dict[str, str],
    max_latency_ms: int,
    rolling_window: int,
    debug: bool,
) -> list[Path]:
    """Evaluate every available direction for one supported logical link."""
    has_forward = (
        f"{endpoint_a}_tx" in decoded_logs
        and f"{endpoint_b}_rx" in decoded_logs
    )
    has_reverse = (
        f"{endpoint_b}_tx" in decoded_logs
        and f"{endpoint_a}_rx" in decoded_logs
    )

    if not has_forward and not has_reverse:
        logging.info(
            "Skipping %s <-> %s because no complete direction is available",
            endpoint_a,
            endpoint_b,
        )
        return []

    logging.info("=== Evaluating %s <-> %s ===", endpoint_a, endpoint_b)

    result_dirs: list[Path] = []

    forward_output = evaluate_direction(
        tx_endpoint=endpoint_a,
        rx_endpoint=endpoint_b,
        decoded_logs=decoded_logs,
        results_dir=results_dir,
        plotter_script=plotter_script,
        custom_result_names=custom_result_names,
        max_latency_ms=max_latency_ms,
        rolling_window=rolling_window,
        debug=debug,
    )

    if forward_output is not None:
        result_dirs.append(forward_output)

    reverse_output = evaluate_direction(
        tx_endpoint=endpoint_b,
        rx_endpoint=endpoint_a,
        decoded_logs=decoded_logs,
        results_dir=results_dir,
        plotter_script=plotter_script,
        custom_result_names=custom_result_names,
        max_latency_ms=max_latency_ms,
        rolling_window=rolling_window,
        debug=debug,
    )

    if reverse_output is not None:
        result_dirs.append(reverse_output)

    return result_dirs


def relative_or_absolute(path: Path, base_dir: Path) -> str:
    """Return a run-relative path when path belongs to the run directory."""
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        return str(path)


def write_manifest(
    run_dir: Path,
    input_dir: Path,
    pcap_inputs: dict[str, Path],
    sqlite_inputs: list[Path],
    decoded_logs: dict[str, Path],
    result_dirs: list[Path],
    custom_result_names: dict[str, str],
    decoder_script: Path,
    plotter_script: Path,
) -> Path:
    """Write run metadata and generated artifact paths to JSON."""
    manifest_path = run_dir / "run_manifest.json"

    manifest: dict[str, Any] = {
        "schema_version": 3,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_directory": str(run_dir),
        "input_directory": relative_or_absolute(input_dir, run_dir),
        "decoder_script": str(decoder_script),
        "plotter_script": str(plotter_script),
        "pcap_inputs": {
            role: relative_or_absolute(path, run_dir)
            for role, path in sorted(pcap_inputs.items())
        },
        "sqlite_inputs": [
            relative_or_absolute(path, run_dir) for path in sqlite_inputs
        ],
        "decoded_logs": {
            role: relative_or_absolute(path, run_dir)
            for role, path in sorted(decoded_logs.items())
        },
        "custom_result_names": custom_result_names,
        "result_directories": [
            relative_or_absolute(path, run_dir)
            for path in sorted(result_dirs)
        ],
        "expected_plot_files": list(EXPECTED_PLOT_FILENAMES),
    }

    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    return manifest_path


def parse_arguments() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description=(
            "Decode PCAPs and run bidirectional V2X "
            "messaging-performance analysis and plotting."
        )
    )

    parser.add_argument(
        "--run-dir",
        type=Path,
        required=True,
        help=(
            "Directory for one analysis run. Outputs are written here. "
            "Raw PCAPs are discovered here unless --input-dir is supplied."
        ),
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help=(
            "Directory containing raw PCAP and SQLite files. "
            "Defaults to --run-dir."
        ),
    )
    parser.add_argument(
        "--decoder-script",
        type=Path,
        default=DEFAULT_DECODER_SCRIPT,
        help=(
            "Path to pcapDecode.py. Defaults to "
            "pcapdecoder/src/pcapDecode.py beside this script."
        ),
    )
    parser.add_argument(
        "--plotter-script",
        "--analyzer-script",
        dest="plotter_script",
        type=Path,
        default=DEFAULT_PLOTTER_SCRIPT,
        help=(
            "Path to v2xhub_messaging_performance_analyzer.py. This script "
            "reads decoded logs and generates CSV and PNG plots."
        ),
    )

    for role in PCAP_ROLES:
        parser.add_argument(
            cli_option_name(role),
            dest=role,
            type=Path,
            default=None,
            help=(
                f"Explicit {role.replace('_', ' ').upper()} PCAP. "
                "Overrides automatic filename discovery."
            ),
        )

    parser.add_argument(
        "--name",
        action="append",
        default=[],
        metavar="DIRECTION=FOLDER_NAME",
        help=(
            "Customize a directional result folder. May be repeated. "
            "Example: --name dut_1_to_dut_2=end_to_end"
        ),
    )
    parser.add_argument(
        "--max-latency-ms",
        type=int,
        default=200,
        help=(
            "Maximum displayed latency value passed to the histogram and CDF "
            "plotter."
        ),
    )
    parser.add_argument(
        "--rolling-window",
        type=int,
        default=20,
        help="Number of samples in the rolling latency mean plot.",
    )
    parser.add_argument(
        "--force-decode",
        action="store_true",
        help="Decode all selected PCAPs again even if decoded logs exist.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose debug logging.",
    )

    return parser.parse_args()


def main() -> int:
    """Run PCAP decoding, latency analysis, and plot generation."""
    args = parse_arguments()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    try:
        run_dir = args.run_dir.expanduser().resolve()
        input_dir = (
            run_dir
            if args.input_dir is None
            else args.input_dir.expanduser().resolve()
        )
        decoder_script = args.decoder_script.expanduser().resolve()
        plotter_script = args.plotter_script.expanduser().resolve()

        if not run_dir.is_dir():
            raise FileNotFoundError(f"Run directory does not exist: {run_dir}")

        if not input_dir.is_dir():
            raise FileNotFoundError(
                f"Input directory does not exist: {input_dir}"
            )

        if args.max_latency_ms <= 0:
            raise ValueError("--max-latency-ms must be greater than zero.")

        if args.rolling_window <= 0:
            raise ValueError("--rolling-window must be greater than zero.")

        validate_helper_script(decoder_script, "PCAP decoder script")
        validate_helper_script(
            plotter_script,
            "V2X messaging-performance analyzer/plotter script",
        )

        custom_result_names = parse_custom_result_names(args.name)
        pcap_inputs = collect_pcap_inputs(args, input_dir)
        sqlite_inputs = discover_sqlite_inputs(input_dir)

        if not pcap_inputs:
            available_roles = ", ".join(PCAP_ROLES)
            raise ValueError(
                f"No PCAPs were discovered in {input_dir}. "
                f"Expected role identifiers such as: {available_roles}"
            )

        if sqlite_inputs:
            logging.info(
                "Found %d SQLite input file(s), not processed yet.",
                len(sqlite_inputs),
            )

            for sqlite_path in sqlite_inputs:
                logging.info("SQLite input: %s", sqlite_path.name)
        else:
            logging.info("No SQLite input files discovered.")

        logging.info("PCAP role assignments:")

        for role, path in sorted(pcap_inputs.items()):
            logging.info("  %-12s -> %s", role, path.name)

        decoded_dir = run_dir / "decoded"
        results_dir = run_dir / "results"

        decoded_dir.mkdir(parents=True, exist_ok=True)
        results_dir.mkdir(parents=True, exist_ok=True)

        decoded_logs: dict[str, Path] = {}

        for role, pcap_path in sorted(pcap_inputs.items()):
            decoded_logs[role] = decode_pcap(
                role=role,
                pcap_path=pcap_path,
                decoded_dir=decoded_dir,
                decoder_script=decoder_script,
                force_decode=args.force_decode,
            )

        result_dirs: list[Path] = []

        for endpoint_a, endpoint_b in SUPPORTED_LINKS:
            result_dirs.extend(
                evaluate_bidirectional(
                    endpoint_a=endpoint_a,
                    endpoint_b=endpoint_b,
                    decoded_logs=decoded_logs,
                    results_dir=results_dir,
                    plotter_script=plotter_script,
                    custom_result_names=custom_result_names,
                    max_latency_ms=args.max_latency_ms,
                    rolling_window=args.rolling_window,
                    debug=args.debug,
                )
            )

        if not result_dirs:
            raise ValueError(
                "No supported analysis directions could be evaluated. "
                "Each direction requires the source endpoint TX PCAP and "
                "the destination endpoint RX PCAP."
            )

        manifest_path = write_manifest(
            run_dir=run_dir,
            input_dir=input_dir,
            pcap_inputs=pcap_inputs,
            sqlite_inputs=sqlite_inputs,
            decoded_logs=decoded_logs,
            result_dirs=result_dirs,
            custom_result_names=custom_result_names,
            decoder_script=decoder_script,
            plotter_script=plotter_script,
        )

    except subprocess.CalledProcessError as error:
        logging.error(
            "A pipeline command failed with exit code %s.",
            error.returncode,
        )
        return 1
    except (
        FileNotFoundError,
        PermissionError,
        RuntimeError,
        ValueError,
        OSError,
    ) as error:
        logging.error("%s", error)
        return 1

    print()
    print("PCAP decoding, analysis, and plot generation complete.")
    print(f"Run directory: {run_dir}")
    print(f"Input data:    {input_dir}")
    print(f"Decoded logs:  {decoded_dir}")
    print(f"Results:       {results_dir}")
    print(f"Manifest:      {manifest_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())