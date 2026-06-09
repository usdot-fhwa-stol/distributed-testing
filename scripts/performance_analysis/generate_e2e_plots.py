from collections.abc import Sequence
import argparse
from pathlib import Path

import sys
import os

# Get the directory of the current script and add it to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

from e2e_utils.data_utils import load_and_parse_csv_data, _DATA_TYPE_FOLDER_ABBREV
from e2e_utils.plot_utils import plot_cumulative_histogram, plot_grouped_histogram
from e2e_utils.style_utils import assign_destination_colors

_RESULTS_DIR = Path(__file__).parent / "results"


def process_and_plot_results(
    root_dir: Path,
    folder_prefix: str,
    data_type: str,
    generate_grouped: bool = True,
    generate_cumulative: bool = True,
    max_bins: Sequence[int] | None = None,
) -> None:
    """Loads run data and generates grouped and/or cumulative histogram plots.

    Args:
        root_dir: Root directory containing run result folders.
        folder_prefix: Prefix used to identify matching run folders.
        data_type: Message type used to filter CSV files.
        generate_grouped: Whether to generate grouped bar histogram plots.
        generate_cumulative: Whether to generate cumulative histogram plots.
        max_bins: Upper bin limits defining zoomed plot levels. Defaults to
            an empty list if not provided, resulting in no plots.
    """
    if not max_bins or not (generate_grouped or generate_cumulative):
        return

    data_abrv = _DATA_TYPE_FOLDER_ABBREV.get(
        data_type.lower(),
        "".join(c for c in data_type if c.isupper()),
    )
    plots_dir = root_dir / f"{folder_prefix.rstrip('-')}-RALL-{data_abrv}_results"
    print(plots_dir)

    result = load_and_parse_csv_data(root_dir, folder_prefix, data_type)
    if result is None:
        return

    run_data_frames, all_source_sites, all_destination_sites = result

    plots_dir.mkdir(parents=True, exist_ok=True)

    destination_colors = assign_destination_colors(run_data_frames)

    common_args = (
        plots_dir,
        data_type,
        run_data_frames,
        all_source_sites,
        all_destination_sites,
    )

    for max_bin in max_bins:
        if generate_grouped:
            plot_grouped_histogram(*common_args, max_bin, destination_colors)
        if generate_cumulative:
            plot_cumulative_histogram(*common_args, max_bin, destination_colors)


def main() -> None:
    """Parses command-line arguments and invokes the result processing pipeline."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate latency plots for distributed connected autonomous"
            " vehicle test runs."
        ),
        epilog=(
            "Examples:\n"
            "  python3 generate_e2e_plots.py EnergyOffset-131 LandVehicle\n"
            "  python3 generate_e2e_plots.py EnergyOffset-130 V2XMessage\n"
            "  python3 generate_e2e_plots.py EnergyOffset-130 TrafficSignalController\n"
            "  python3 generate_e2e_plots.py EnergyOffset-131 LandVehicle --grouped\n"
            "  python3 generate_e2e_plots.py EnergyOffset-131 LandVehicle --cumulative\n"
            "  python3 generate_e2e_plots.py EnergyOffset-131 LandVehicle --max-bins 200 1000\n"
            "\n"
            "Note: if neither --grouped nor --cumulative is specified,\n"
            "      both plot types are generated."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "run_prefix",
        nargs="?",
        default="Energy131-",
        help="Prefix used to match run folders inside results_dir.",
    )
    parser.add_argument(
        "message_type",
        nargs="?",
        default="LandVehicle",
        help="Message type to filter CSV files by.",
    )
    parser.add_argument(
        "--grouped",
        action="store_true",
        help="Generate grouped bar histogram plots of message latency.",
    )
    parser.add_argument(
        "--cumulative",
        action="store_true",
        help="Generate cumulative histogram plots of message latency.",
    )
    parser.add_argument(
        "--max-bins",
        nargs="+",
        type=int,
        default=[200, 1000],
        help=(
            "List of maximum bin values for generating multiple zoomed"
            " levels of plots (default: 200 1000)."
        ),
    )
    args = parser.parse_args()

    generate_grouped = args.grouped or not args.cumulative
    generate_cumulative = args.cumulative or not args.grouped

    process_and_plot_results(
        _RESULTS_DIR,
        args.run_prefix,
        args.message_type,
        generate_grouped=generate_grouped,
        generate_cumulative=generate_cumulative,
        max_bins=args.max_bins,
    )


if __name__ == "__main__":
    main()
