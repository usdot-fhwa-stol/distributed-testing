## Utility functions for styling the plots in plot_utils.py.
## Includes functions to assign unique colors and line styles to runs and destination sites.

import seaborn as sns

def _extract_unique_destinations(run_data_frames: dict) -> list[str]:
    """
    Extracts unique destination sites from the run data frames.
    """
    unique_destinations: set[str] = {
        destination_site
        for run_data in run_data_frames.values()
        for destinations in run_data.values()
        for destination_site in destinations
    }
    return sorted(list(unique_destinations))

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
    unique_destinations = _extract_unique_destinations(run_data_frames)
    return _assign_unique_colors(unique_destinations)


def assign_destination_linestyles(run_data_frames: dict) -> dict[str, any]:
    """Assigns a unique line style to each destination"""
    unique_dests = _extract_unique_destinations(run_data_frames)
    
    extended_styles = [
        "-",               # Solid
        "--",              # Dashed
        "-.",              # Dash-dot
        ":",               # Dotted
        (0, (5, 2)),       # Loose dash
        (0, (1, 1)),       # Dense dot
        (0, (4, 1, 1, 1)), # Distinct dash-dot
        (0, (8, 2)),       # Long dash
        (0, (2, 2)),       # Short dash
    ]
    
    return {
        dest: extended_styles[i % len(extended_styles)]
        for i, dest in enumerate(unique_dests)
    }


