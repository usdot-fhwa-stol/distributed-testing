from collections.abc import Sequence
import argparse
from pathlib import Path

from e2e_utils.data_utils import load_and_parse_csv_data
from e2e_utils.plot_utils import plot_cumulative_histogram, plot_grouped_histogram, assign_plot_styles

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
        generate_histogram: Whether to generate grouped bar histogram plots.
        generate_cumulative: Whether to generate cumulative histogram plots.
        max_bins: Upper bin limits defining zoomed plot levels. Defaults to
            an empty list if not provided, resulting in no plots.
    """
    if max_bins is None:
        max_bins = []

    plots_dir = root_dir / "plots" / folder_prefix.rstrip("-")
    plots_dir.mkdir(parents=True, exist_ok=True)

    result = load_and_parse_csv_data(root_dir, folder_prefix, data_type)
    if result is None:
        return

    run_data_frames, all_source_sites, all_destination_sites = result
    plot_styles = assign_plot_styles(run_data_frames)

    for max_bin in max_bins:
        if generate_grouped:
            plot_grouped_histogram(
                plots_dir,
                data_type,
                run_data_frames,
                all_source_sites,
                all_destination_sites,
                max_bin,
                plot_styles
            )
        if generate_cumulative:
            plot_cumulative_histogram(
                plots_dir,
                data_type,
                run_data_frames,
                all_source_sites,
                all_destination_sites,
                max_bin,
                plot_styles
            )


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
