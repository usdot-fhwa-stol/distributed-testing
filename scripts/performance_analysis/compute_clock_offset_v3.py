"""
compute_clock_offset_v3.py



============================== USAGE ==============================

Auto mode, single run (most common case):
    python3 compute_clock_offset_v4.py \\
        -m /path/to/Run6/metadata.json \\
        -r results/Run6_results \\
        -t Vehicle \\
        -o results/Run6_results/clock_offset_vehicle

Auto mode, multiple runs at once (cross-run comparison too):
    python3 compute_clock_offset_v4.py \\
        -m /path/Run1/metadata.json /path/Run2/metadata.json /path/Run6/metadata.json \\
        -r results/Run1_results results/Run2_results results/Run6_results \\
        -t Vehicle \\
        -o results/plots/clock_offset_vehicle

If a run's metadata.json has more than 2 sites, tell it which pair to use:
    ... --site-a Driving_Simulator --site-b SILS

Manual mode (v3-compatible, for non-standard filenames):
    python3 compute_clock_offset_v4.py \\
        -a results/Run1_results/driving_simulator_to_sils_vehicle.csv \\
        -b results/Run1_results/sils_to_driving_simulator_vehicle.csv \\
        --a-label "Driving_Simulator->SILS" --b-label "SILS->Driving_Simulator" \\
        -o results/Run1_results/clock_offset_vehicle

"""

import argparse
import glob
import os
import re
import sys
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def clean_name(input_name):
    """Reproduce calculate_e2e_perf.py's clean_name() exactly, so
    auto-discovered filenames match what that script actually wrote."""
    name = re.sub(r'\.csv', '', input_name)
    name = re.sub(r'\.\/data\/.*\/', '', name)
    name = re.sub(r'[^A-Za-z0-9 _-]+', '', name)
    name = re.sub(r' ', '_', name)
    return name.lower()


def discover_direction_files(metadata_path, results_dir, data_type, site_a=None, site_b=None):
    """Given a run's metadata.json + its results folder + a data type,
    figure out the two direction result CSV filenames the same way
    batch_calculate_e2e_perf_v2.py named them, without needing them typed
    out by hand."""
    with open(metadata_path, "r") as f:
        sites = json.load(f)

    site_names = [s["site_name"] for s in sites]

    if site_a is None or site_b is None:
        if len(site_names) != 2:
            print(f"ERROR: {metadata_path} has {len(site_names)} sites ({site_names}). "
                  f"Specify --site-a and --site-b to pick which pair to analyze.")
            sys.exit(1)
        site_a, site_b = site_names

    for s in (site_a, site_b):
        if s not in site_names:
            print(f"ERROR: site '{s}' not found in {metadata_path}. Available: {site_names}")
            sys.exit(1)

    a_to_b_file = os.path.join(results_dir, clean_name(f"{site_a}_to_{site_b}_{data_type}") + ".csv")
    b_to_a_file = os.path.join(results_dir, clean_name(f"{site_b}_to_{site_a}_{data_type}") + ".csv")

    for f in (a_to_b_file, b_to_a_file):
        if not os.path.isfile(f):
            print(f"ERROR: expected result file not found: {f}")
            print("  (Has batch_calculate_e2e_perf_v2.py been run for this run + data type yet?)")
            sys.exit(1)

    return a_to_b_file, b_to_a_file, f"{site_a}->{site_b}", f"{site_b}->{site_a}"


def load_direction_csv(path):
    df = pd.read_csv(path)

    ts_cols = [c for c in df.columns if "timestamp" in c]
    lat_cols = [c for c in df.columns if "_total_latency" in c]

    if not ts_cols or not lat_cols:
        print(f"ERROR: {path} is missing a timestamp or _total_latency column")
        sys.exit(1)

    df["timestamp_s"] = pd.to_numeric(df[ts_cols[0]], errors="coerce")
    df["latency_ms"] = pd.to_numeric(df[lat_cols[-1]], errors="coerce")
    df = df.dropna(subset=["timestamp_s", "latency_ms"]).sort_values("timestamp_s").reset_index(drop=True)

    if df.empty:
        print(f"ERROR: {path} has no valid numeric rows after cleaning")
        sys.exit(1)

    return df


def windowed_means(df, t_zero, window_s):
    df = df.copy()
    df["elapsed_s"] = df["timestamp_s"] - t_zero
    df["window"] = (df["elapsed_s"] // window_s) * window_s
    grouped = df.groupby("window").agg(latency_ms=("latency_ms", "mean"), n=("latency_ms", "size")).reset_index()
    return grouped


def compute_dynamic_offset_and_latency(df_a, df_b, window_s):
    """The core change from v3: compute offset/true_latency PER TIME WINDOW,
    then average those -- rather than one offset from full-run means."""
    t_zero = min(df_a["timestamp_s"].min(), df_b["timestamp_s"].min())

    wa = windowed_means(df_a, t_zero, window_s)
    wb = windowed_means(df_b, t_zero, window_s)

    merged = wa.merge(wb, on="window", suffixes=("_a", "_b"), how="inner")
    merged["offset"] = (merged["latency_ms_b"] - merged["latency_ms_a"]) / 2
    merged["true_latency"] = (merged["latency_ms_a"] + merged["latency_ms_b"]) / 2

    # Sample-weighted versions, for comparison -- this is mathematically
    # equivalent to v3's old single-global-offset approach.
    sample_weighted_offset = (df_b["latency_ms"].mean() - df_a["latency_ms"].mean()) / 2
    sample_weighted_latency = (df_a["latency_ms"].mean() + df_b["latency_ms"].mean()) / 2

    summary = {
        "n_windows": len(merged),
        "offset_mean": merged["offset"].mean(),
        "offset_std": merged["offset"].std(),
        "offset_min": merged["offset"].min(),
        "offset_max": merged["offset"].max(),
        "true_latency_mean": merged["true_latency"].mean(),
        "true_latency_std": merged["true_latency"].std(),
        "sample_weighted_offset": sample_weighted_offset,
        "sample_weighted_latency": sample_weighted_latency,
    }
    return merged, summary


def plot_single_run(merged, a_label, b_label, summary, out_prefix):
    # Raw two-direction plot
    plt.figure(figsize=(14, 6))
    plt.plot(merged["window"], merged["latency_ms_a"], label=f"{a_label} (raw)", marker="o", ms=3)
    plt.plot(merged["window"], merged["latency_ms_b"], label=f"{b_label} (raw)", marker="o", ms=3)
    plt.axhline(0, color="gray", linewidth=0.8)
    plt.xlabel("Elapsed time in run (s)")
    plt.ylabel("Measured latency (ms)")
    plt.title(f"Raw (offset-biased) latency, both directions -- mean offset = {summary['offset_mean']:.2f} ms")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.savefig(f"{out_prefix}_raw_directions.png")
    plt.close()

    # Dynamic offset over time -- the new, honest view of how much it actually moves
    plt.figure(figsize=(14, 6))
    plt.plot(merged["window"], merged["offset"], marker="o", ms=3, color="tab:orange")
    plt.axhline(summary["offset_mean"], color="red", linestyle="--",
                label=f"Mean offset = {summary['offset_mean']:.2f} ms (std={summary['offset_std']:.2f})")
    plt.xlabel("Elapsed time in run (s)")
    plt.ylabel("Clock offset (ms)")
    plt.title("Clock offset over time (this is NOT assumed constant)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.savefig(f"{out_prefix}_offset_over_time.png")
    plt.close()

    # True latency over time -- one line now, computed per-window from that
    # window's own offset, not two separate "should-agree" estimates
    plt.figure(figsize=(14, 6))
    plt.plot(merged["window"], merged["true_latency"], marker="o", ms=3, color="tab:blue")
    plt.axhline(summary["true_latency_mean"], color="red", linestyle="--",
                label=f"Mean true latency = {summary['true_latency_mean']:.2f} ms")
    plt.xlabel("Elapsed time in run (s)")
    plt.ylabel("Corrected true latency (ms)")
    plt.title("True latency over time, offset-corrected per window")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.savefig(f"{out_prefix}_true_latency.png")
    plt.close()

    # Sample count per window -- flags low-confidence windows
    plt.figure(figsize=(14, 4))
    plt.bar(merged["window"], merged["n_a"], alpha=0.5, label=f"{a_label} samples/window", width=merged["window"].diff().median() or 1)
    plt.bar(merged["window"], merged["n_b"], alpha=0.5, label=f"{b_label} samples/window", width=merged["window"].diff().median() or 1)
    plt.xlabel("Elapsed time in run (s)")
    plt.ylabel("Samples in window")
    plt.title("Sample count per window (low bars = less trustworthy offset/latency estimate there)")
    plt.legend()
    plt.grid(True, axis="y", alpha=0.3)
    plt.savefig(f"{out_prefix}_sample_counts.png")
    plt.close()


def plot_multi_run_summary(summaries, run_labels, out_prefix):
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    offsets = [s["offset_mean"] for s in summaries]
    offset_stds = [s["offset_std"] for s in summaries]
    latencies = [s["true_latency_mean"] for s in summaries]
    latency_stds = [s["true_latency_std"] for s in summaries]

    axes[0].bar(run_labels, offsets, yerr=offset_stds, capsize=4, color="tab:orange")
    axes[0].set_ylabel("Clock offset (ms)")
    axes[0].set_title("Clock offset across runs (error bars = within-run std)")
    axes[0].grid(True, axis="y", alpha=0.3)

    axes[1].bar(run_labels, latencies, yerr=latency_stds, capsize=4, color="tab:blue")
    axes[1].set_ylabel("Recovered true latency (ms)")
    axes[1].set_title("True latency across runs (error bars = within-run std)")
    axes[1].grid(True, axis="y", alpha=0.3)

    plt.tight_layout()
    plt.savefig(f"{out_prefix}_summary.png")
    plt.close()


def main():
    parser = argparse.ArgumentParser(description="Estimate dynamic clock offset and true latency, for any run")

    # Auto-discovery mode
    parser.add_argument("-m", "--metadata", nargs="+", help="metadata.json path(s), one per run")
    parser.add_argument("-r", "--results-dir", nargs="+", help="results folder(s), same order as -m")
    parser.add_argument("-t", "--data-type", help="Data type, e.g. Vehicle or J2735-BSM")
    parser.add_argument("--site-a", default=None, help="Override: source site name (needed if >2 sites in metadata)")
    parser.add_argument("--site-b", default=None, help="Override: destination site name (needed if >2 sites)")

    # Manual v3-compatible mode
    parser.add_argument("-a", nargs="+", help="Direction A->B result CSV(s) (manual mode)")
    parser.add_argument("-b", nargs="+", help="Direction B->A result CSV(s) (manual mode)")
    parser.add_argument("--a-label", default=None)
    parser.add_argument("--b-label", default=None)

    parser.add_argument("--run-labels", nargs="+", default=None, help="Labels for each run, e.g. Run1 Run2 Run6")
    parser.add_argument("-o", "--out-prefix", required=True, help="Output path prefix for saved plots")
    parser.add_argument("--window", type=float, default=5.0, help="Window size in seconds")
    args = parser.parse_args()

    auto_mode = args.metadata is not None
    manual_mode = args.a is not None

    if auto_mode == manual_mode:
        print("ERROR: use either auto mode (-m/-r/-t) or manual mode (-a/-b), not both/neither")
        sys.exit(1)

    pairs = []  # list of (a_path, b_path, a_label, b_label)

    if auto_mode:
        if not args.results_dir or len(args.results_dir) != len(args.metadata):
            print("ERROR: -r must be given, same count as -m")
            sys.exit(1)
        if not args.data_type:
            print("ERROR: -t/--data-type is required in auto mode")
            sys.exit(1)
        for m_path, r_dir in zip(args.metadata, args.results_dir):
            a_path, b_path, a_lbl, b_lbl = discover_direction_files(
                m_path, r_dir, args.data_type, args.site_a, args.site_b
            )
            pairs.append((a_path, b_path, a_lbl, b_lbl))
        run_labels = args.run_labels or [os.path.basename(r.rstrip("/")) for r in args.results_dir]
    else:
        if len(args.a) != len(args.b):
            print("ERROR: -a and -b must have the same number of files")
            sys.exit(1)
        a_lbl = args.a_label or "A->B"
        b_lbl = args.b_label or "B->A"
        for a_path, b_path in zip(args.a, args.b):
            pairs.append((a_path, b_path, a_lbl, b_lbl))
        run_labels = args.run_labels or [f"Run{i+1}" for i in range(len(pairs))]

    if len(run_labels) != len(pairs):
        print("ERROR: --run-labels count must match number of runs")
        sys.exit(1)

    os.makedirs(os.path.dirname(args.out_prefix) or ".", exist_ok=True)

    summaries = []

    for i, (a_path, b_path, a_lbl, b_lbl) in enumerate(pairs):
        df_a = load_direction_csv(a_path)
        df_b = load_direction_csv(b_path)
        merged, summary = compute_dynamic_offset_and_latency(df_a, df_b, args.window)

        print(f"\n=== {run_labels[i]} ({a_lbl} / {b_lbl}) ===")
        print(f"  Windows analyzed: {summary['n_windows']} (window size = {args.window}s)")
        print(f"  Offset:  mean={summary['offset_mean']:.3f} ms  std={summary['offset_std']:.3f}  "
              f"range=[{summary['offset_min']:.3f}, {summary['offset_max']:.3f}]")
        print(f"  True latency (time-weighted): mean={summary['true_latency_mean']:.3f} ms  "
              f"std={summary['true_latency_std']:.3f}")
        print(f"  For comparison, old v3-style sample-weighted single estimate: "
              f"offset={summary['sample_weighted_offset']:.3f} ms, "
              f"latency={summary['sample_weighted_latency']:.3f} ms")

        summaries.append(summary)

        run_prefix = f"{args.out_prefix}_{run_labels[i]}"
        plot_single_run(merged, a_lbl, b_lbl, summary, run_prefix)
        print(f"  Plots saved: {run_prefix}_raw_directions.png, {run_prefix}_offset_over_time.png, "
              f"{run_prefix}_true_latency.png, {run_prefix}_sample_counts.png")

    if len(pairs) > 1:
        plot_multi_run_summary(summaries, run_labels, args.out_prefix)
        print(f"\nCross-run summary plot saved: {args.out_prefix}_summary.png")


if __name__ == "__main__":
    main()