"""
Run CSV and PCAP latency analysis for every run under a parent folder.
"""

import argparse
import logging
import sys
from pathlib import Path

import analysis_csv
import analysis_pcap
import pandas as pd


FAILURE_RESULTS = {"FAIL", "ERROR"}


def parse_arguments() -> argparse.Namespace:
    """Read the command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Run PCAP and CSV latency analysis for every run under an "
            "input directory."
        )
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help=(
            "Parent directory containing the run directories. Results are "
            "written to a results directory beside this parent directory."
        ),
    )
    return parser.parse_args()


def discover_runs(input_dir: Path) -> tuple[list[Path], Path]:
    """Find all run directories directly inside the input directory."""
    input_dir = input_dir.expanduser().resolve()

    if not input_dir.is_dir():
        raise FileNotFoundError(
            f"Input directory does not exist: {input_dir}"
        )

    # Ignore folders that dont contain run data
    ignored_names = {
        "decoded",
        "__pycache__",
    }

    # Sort file paths to process runs in order
    run_directories = sorted(
        (
            path.resolve()
            for path in input_dir.iterdir()
            if path.is_dir()
            and path.name not in ignored_names
            and not path.name.startswith(".")
        ),
        key=lambda path: path.name.casefold(),
    )

    if not run_directories:
        raise FileNotFoundError(
            f"No run directories found inside {input_dir}"
        )

    # Create the results folder under the same parent as the input directory.
    results_root = (input_dir.parent / "results").resolve()
    return run_directories, results_root


def read_run_summary_files(results_dir: Path) -> pd.DataFrame:
    """Read all generated result summaries for a run."""
    if not results_dir.is_dir():
        return pd.DataFrame()

    # Search for summary files based on file name, and process in sorted order
    summary_file_paths = sorted(
        (
            path
            for path in results_dir.rglob("results_summary.csv")
            if path.is_file()
        ),
        key=lambda path: str(path).casefold(),
    )

    summary_dfs: list[pd.DataFrame] = []

    # Read in data from summary csv
    for summary_file_path in summary_file_paths:
        try:
            summary_df = pd.read_csv(summary_file_path)
        except (
            OSError,
            pd.errors.EmptyDataError,
            pd.errors.ParserError,
            UnicodeDecodeError,
        ) as error:
            logging.error(
                "Failed to read summary %s: %s",
                summary_file_path,
                error,
            )
            continue

        if summary_df.empty:
            logging.warning("Summary file is empty: %s", summary_file_path)
            continue

        # Get the relative path of the summary file from the results directory
        # /results/run_001/summary.csv -> /run_001/summary.csv
        relative_file = summary_file_path.relative_to(results_dir)

        # run directory
        relative_parent = summary_file_path.parent.relative_to(results_dir)

        summary_df.insert(0, "summary_file", str(relative_file))
        summary_df.insert(0, "test_name", str(relative_parent))
        summary_df.insert(0, "run_name", results_dir.name)

        summary_dfs.append(summary_df)

    if not summary_dfs:
        return pd.DataFrame()

    return pd.concat(summary_dfs, ignore_index=True)


def get_run_result(
    summary: pd.DataFrame,
    analysis_failed: bool,
) -> tuple[str, str]:
    """Return the overall result and failure reason for one run."""
    if analysis_failed:
        return "FAIL", "ANALYSIS_ERROR"

    if summary.empty:
        return "FAIL", "NO_RESULTS"

    if "threshold_result" not in summary.columns:
        return "PASS", ""

    if summary["threshold_result"].isin(FAILURE_RESULTS).any():
        return "FAIL", "THRESHOLD_FAILURE"

    return "PASS", ""


def save_run_summary(
    run_dir: Path,
    results_dir: Path,
    run_result: str,
    failure_reason: str,
) -> Path:
    """Write the combined detailed summary for one run."""
    summary = read_run_summary_files(results_dir)

    # Write a blank summary if any failure prevent finishing analysis
    if summary.empty:
        summary = pd.DataFrame(
            [
                {
                    "run_name": run_dir.name,
                    "test_name": "",
                    "summary_file": "",
                    "threshold_result": "",
                    "run_result": run_result,
                    "failure_reason": failure_reason,
                }
            ]
        )
    else:
        summary["run_result"] = run_result
        summary["failure_reason"] = failure_reason

    # Save summary to results/run folder
    results_dir.mkdir(parents=True, exist_ok=True)
    output_file = results_dir / f"{run_dir.name}_summary.csv"
    summary.to_csv(output_file, index=False)

    logging.info("Run summary written to %s", output_file)
    return output_file.resolve()


def write_total_summary(
    results_root: Path,
    run_results: list[dict[str, str]],
) -> Path:
    """Write one simple PASS or FAIL result for each run."""
    total_summary = pd.DataFrame(
        run_results,
        columns=["run_name", "run_result", "failure_reason"],
    )

    # Keep the final summary at the top of the results folder
    results_root.mkdir(parents=True, exist_ok=True)
    output_file = results_root / "total_data_summary.csv"
    total_summary.to_csv(output_file, index=False)

    logging.info("Total summary written to %s", output_file)
    return output_file.resolve()


def analyze_run(
    input_dir: Path,
    results_dir: Path,
) -> bool:
    """Run the PCAP and CSV analysis for one run."""
    logging.info("============================================================")
    logging.info("Processing run: %s", input_dir.name)
    logging.info("Input: %s", input_dir)
    logging.info("Output: %s", results_dir)

    # Create reults directory
    results_dir.mkdir(parents=True, exist_ok=True)
    analysis_failed = False

    # Run pcap then csv analysis_csv and mark status as failed if either produces an error
    try:
        status = analysis_pcap.run_pcap_analysis(
            input_dir=input_dir,
            results_dir=results_dir,
        )
        analysis_failed = analysis_failed or status != 0
    except Exception:
        logging.exception(
            "PCAP analysis error for %s",
            input_dir.name,
        )
        analysis_failed = True

    try:
        status = analysis_csv.run_csv_analysis(
            input_dir=input_dir,
            results_dir=results_dir,
        )
        analysis_failed = analysis_failed or status != 0
    except Exception:
        logging.exception(
            "Unhandled CSV analysis error for %s",
            input_dir.name,
        )
        analysis_failed = True

    return analysis_failed


def main() -> int:
    """Analyze every run found under the input directory."""
    args = parse_arguments()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Find run folders
    try:
        run_directories, results_root = discover_runs(args.input_dir)
    except (FileNotFoundError, OSError) as error:
        logging.error("Unable to find input runs: %s", error)
        return 1

    run_results: list[dict[str, str]] = []
    any_run_failed = False

    # Analyze and write summary for each run
    for run_dir in run_directories:
        run_results_dir = results_root / run_dir.name

        analysis_failed = analyze_run(
            input_dir=run_dir,
            results_dir=run_results_dir,
        )

        summary = read_run_summary_files(run_results_dir)
        run_result, failure_reason = get_run_result(
            summary=summary,
            analysis_failed=analysis_failed,
        )

        try:
            save_run_summary(
                run_dir=run_dir,
                results_dir=run_results_dir,
                run_result=run_result,
                failure_reason=failure_reason,
            )
        except Exception:
            logging.exception(
                "Failed to write summary for %s",
                run_dir.name,
            )
            run_result = "FAIL"
            failure_reason = "SUMMARY_ERROR"

        run_results.append(
            {
                "run_name": run_dir.name,
                "run_result": run_result,
                "failure_reason": failure_reason,
            }
        )

        if run_result == "FAIL":
            any_run_failed = True

    try:
        summary_file = write_total_summary(
            results_root=results_root,
            run_results=run_results,
        )
        print(
            "[✓] Analysis complete. "
            f"Summary saved to: {summary_file}"
        )
    except Exception:
        logging.exception("Failed to write the total summary")
        return 1

    failed_runs = sum(
        result["run_result"] == "FAIL"
        for result in run_results
    )

    if failed_runs:
        logging.warning(
            "%d of %d run(s) failed.",
            failed_runs,
            len(run_directories),
        )

    return 1 if any_run_failed else 0


if __name__ == "__main__":
    sys.exit(main())