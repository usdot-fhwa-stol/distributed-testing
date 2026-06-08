import hashlib
import seaborn as sns

_DISTINCT_PALETTE = sns.color_palette("hls", 8)

def get_deterministic_color(target_name: str) -> tuple:
    """
    Deterministically assigns a different colors for each target name.
    """
    hash_int = int(hashlib.sha256((target_name).encode("utf-8")).hexdigest(), 16)

    return _DISTINCT_PALETTE[hash_int % len(_DISTINCT_PALETTE)]


def assign_plot_styles(run_data_frames: dict) -> dict[str, dict]:

    source_destination_colors: dict[str, tuple] = {}

    # Assign color and opacity to each destination
    for run_number, run_data in run_data_frames.items():
        for source_site, destinations in run_data.items():
            for destination_site, dfs in destinations.items():

                # 1. Assign consistent color via deterministic hash
                if destination_site not in source_destination_colors:
                    source_destination_colors[destination_site] = (
                        get_deterministic_color(destination_site)
                    )

    # Assign consistent color for each run
    run_colors: dict[str, tuple] = {}

    # Sort run numbers in ascending order
    for run_number in sorted(
        run_data_frames.keys(), key=lambda x: int(x) if x.isdigit() else 0
    ):
        if run_number not in run_colors:
            # Utilize a distinct colormap for runs to prevent overlap with destinations
            run_colors[run_number] = get_deterministic_color(
                run_number
            )

    return {
        "source_destination_colors": source_destination_colors,
        "run_colors": run_colors,
    }
