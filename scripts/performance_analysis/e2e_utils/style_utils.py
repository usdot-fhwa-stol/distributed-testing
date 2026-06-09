import hashlib
import seaborn as sns

_PALETTE_ = sns.color_palette("tab10")

def get_deterministic_color(target_name: str) -> tuple:
    """
    Deterministically assigns a different colors for each target name.
    """
    hash_int = int(hashlib.md5((target_name).encode("utf-8")).hexdigest(), 16)

    return _PALETTE_[hash_int % len(_PALETTE_)]


def assign_destination_colors(run_data_frames: dict) -> dict[str, tuple]:
    """Assigns a deterministic color to each unique destination site."""
    unique_destinations: set[str] = {
        destination_site
        for run_data in run_data_frames.values()
        for destinations in run_data.values()
        for destination_site in destinations
    }
    return {dest: get_deterministic_color(dest) for dest in unique_destinations}


def assign_run_colors(run_data_frames: dict) -> dict[str, tuple]:
    """Assigns a deterministic color to each run in ascending order."""
    sorted_runs = sorted(
        run_data_frames.keys(), key=lambda x: int(x) if x.isdigit() else 0
    )
    return {run: get_deterministic_color(run) for run in sorted_runs}
