## Utility functions for styling the plots in plot_utils.py.
## Includes functions to assign unique colors to runs and destination sites.

import seaborn as sns


def _assign_unique_colors(targets: list[str]) -> dict[str, tuple]:
    """
    Assign unique colors to runs or destinations based on order
    """
    sorted_targets = sorted(targets)
    n_targets = len(sorted_targets)
    
    palette = sns.color_palette("bright", n_colors=n_targets)

    return dict(zip(sorted_targets, palette))


def assign_destination_colors(run_data_frames: dict) -> dict[str, tuple]:
    """Assigns a unique color to each unique destination site without repeating."""
    unique_destinations: set[str] = {
        destination_site
        for run_data in run_data_frames.values()
        for destinations in run_data.values()
        for destination_site in destinations
    }
    return _assign_unique_colors(sorted(list(unique_destinations)))


