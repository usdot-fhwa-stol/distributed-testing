from collections.abc import Sequence
import argparse
from pathlib import Path

from e2e_utils.data_utils import load_and_parse_csv_data, _DATA_TYPE_FOLDER_ABBREV
from e2e_utils.plot_utils import (
    plot_cumulative_histogram,
    plot_grouped_histogram,
    plot_timeseries_by_destination,
    plot_timeseries_by_run,
)
from e2e_utils.style_utils import assign_destination_colors, assign_destination_linestyles

_RESULTS_DIR = Path(__file__).parent / "results"


def process_and_plot_results(
    root_dir: Path,
    folder_prefix: str,
    data_type: str,
    generate_grouped: bool = True,
    g_data_label: bool = True,
    generate_cumulative: bool = True,
    c_data_label: bool = True,
    max_bins: Sequence[int] | None = None,
    generate_timeseries: bool = True,
) -> None:
    """Loads run data and generates grouped and/or cumulative histogram plots as well as timeseries plots.

    Args:
        root_dir: Root directory containing run result folders.
        folder_prefix: Prefix used to identify matching run folders.
        data_type: Message type used to filter CSV files.
        generate_grouped: Whether to generate grouped bar histogram plots.
        g_data_label: Whether to include sample count for each bar in grouped histogram plot.
        generate_cumulative: Whether to generate cumulative histogram plots.
        c_data_label: Whether to include probability value for each bin in cumulative histogram plot.
        max_bins: Upper bin limits defining zoomed plot levels. Defaults to
            an empty list if not provided, resulting in no plots for histograms.
        generate_timeseries: Whether to generate timeseries latency plots.
    """
    if not (generate_grouped or generate_cumulative or generate_timeseries):
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

    destination_linestyles = assign_destination_linestyles(run_data_frames)

    for max_bin in max_bins or []:
        if generate_grouped:
            plot_grouped_histogram(*common_args, g_data_label, max_bin, destination_colors)
        if generate_cumulative:
            plot_cumulative_histogram(*common_args, c_data_label, max_bin, destination_colors, destination_linestyles)

    run_colors = assign_destination_colors(run_data_frames)

    if generate_timeseries:
        plot_timeseries_by_run(*common_args, run_colors)
        plot_timeseries_by_destination(
            plots_dir, data_type, run_data_frames, destination_colors
        )


def main() -> None:
    """Plots the end to end (E2E) latency results in histograms and timeseries plots for distributed testing for connected autonomous vehicles.
    Allows users to specify test event, message type, and plot types, and plot details to generate.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Generate latency plots for distributed testing for connected autonomous vehicles"
        ),
        epilog=(
            "Examples:\n"
            "  python3 generate_e2e_plots.py EnergyOffset-130 LandVehicle\n"
            "  python3 generate_e2e_plots.py EnergyOffset-130 V2XMessage\n"
            "  python3 generate_e2e_plots.py EnergyOffset-130 TrafficSignalController\n"
            "  python3 generate_e2e_plots.py EnergyOffset-131 LandVehicle --grouped\n"
            "  python3 generate_e2e_plots.py EnergyOffset-131 LandVehicle --cumulative --c_data_label false\n"
            "  python3 generate_e2e_plots.py EnergyOffset-131 LandVehicle --timeseries\n"
            "  python3 generate_e2e_plots.py EnergyOffset-131 LandVehicle --max-bins 200 1000\n"
            "\n"
            "Note: if none of --grouped, --cumulative are specified,\n"
            "      all plot types are generated."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "run_prefix",
        nargs="?",
        default="EnergyOffset-130",
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
        "--no_g_data_label",
        action="store_false",
        help="Include sample count for each bar in grouped histogram plot.",
    )
    parser.add_argument(
        "--cumulative",
        action="store_true",
        help="Generate cumulative histogram plots of message latency.",
    )
    parser.add_argument(
        "--no_c_data_label",
        action="store_false",
        help="Include probability value for each bin in cumulative histogram plot.",
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
    parser.add_argument(
        "--timeseries",
        action="store_true",
        help="Generate timeseries plots of message latency.",
    )


    args = parser.parse_args()

    generate_grouped = args.grouped or not args.cumulative
    generate_cumulative = args.cumulative or not args.grouped
    generate_timeseries = args.timeseries

    process_and_plot_results(
        _RESULTS_DIR,
        args.run_prefix,
        args.message_type,
        generate_grouped=generate_grouped,
        g_data_label=args.no_g_data_label,
        generate_cumulative=generate_cumulative,
        c_data_label=args.no_c_data_label,
        max_bins=args.max_bins,
        generate_timeseries=generate_timeseries,
    )


if __name__ == "__main__":
    main()
