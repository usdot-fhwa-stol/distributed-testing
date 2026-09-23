"""
compute_clock_offset_v5.py

Measures the clock offset between two machines and recovers the true one-way
latency, then reports which direction needs which sign of correction.

WHY
    When two machines' clocks disagree, the latency analysis reports
        measured_forward = true_latency - offset
        measured_reverse = true_latency + offset
    so one direction comes out NEGATIVE and the other INFLATED. Neither is the
    real latency. Combining both directions separates them:
        offset       = (reverse - forward) / 2
        true latency = (forward + reverse) / 2
    Computed per time window, so a drifting offset is followed rather than
    assumed constant.

WHAT CHANGED FROM v4
    v4 needed the two CSV paths, two labels, a run label and an output prefix
    typed out by hand whenever the result filenames did not match one exact
    naming convention. v5 finds the files itself: point it at a results folder
    and pick a data type from a menu. Site names, direction labels, run label
    and output paths are all derived from what it finds. The old explicit
    arguments still work for odd cases.

USAGE
    Fully interactive -- pick a results folder, then a data type:
        python3 compute_clock_offset_v5.py

    Skip the folder menu:
        python3 compute_clock_offset_v5.py -r <results folder>

    Skip both menus:
        python3 compute_clock_offset_v5.py -r <results folder> -t <data type>

    Every direction pair in a folder, no menus:
        python3 compute_clock_offset_v5.py -r <results folder> --all

    Manual override, for filenames this cannot parse:
        python3 compute_clock_offset_v5.py -a <forward csv> -b <reverse csv>

OPTIONS
    --results-root <dir>  where the results folders live (default: results)
    --window <seconds>    offset averaging window (default: 5)
    -o <prefix>           output path prefix (default: inside the results folder)
    --no-plots            print numbers only

OUTPUT
    Console: offset (mean/std/range), true latency, and the exact flags to pass
    to the batch script to correct each direction with the right sign.
    Plots: raw both-directions, offset over time, true latency over time,
    samples per window.

ASSUMPTION
    Splitting two unknowns from two measurements requires latency to be
    symmetric at any instant. The offset is robust; the per-direction latency
    split inherits that assumption. Once the machines are clock-synchronised
    the offset goes to zero and this becomes a verification tool.
"""

import argparse
import glob
import os
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

# Data types that may appear as a suffix in a result filename.
# ORDER MATTERS: longer names first, so "J2735-PSM" is matched before "J2735".
KNOWN_DATA_TYPES = [
    "VulnerableRoadUser", "J2735-PSM", "J2735-BSM", "J2735-SPAT", "J2735-MAP",
    "TrafficSignalController", "V2XMessage", "TrafficLight", "LandVehicle",
    "J3224", "Vehicle", "J2735",
]


def parse_result_filename(path):
    """Pull (SOURCE, DEST, data_type) out of a result CSV name, or None.

    Handles both naming conventions seen in practice:
        <src>_to_<dst>_<type>.csv
        <src>_to_<dst>_<type>_<endpoint>_performance_results.csv
    """
    base = os.path.basename(path)
    if not base.lower().endswith(".csv"):
        return None
    if "summary" in base.lower():
        return None

    stem = base[:-4].lower()
    # strip the trailing decorations the batch script may append
    stem = re.sub(r"_performance_results.*$", "", stem)
    stem = re.sub(r"_\d{1,3}-\d{1,3}-\d{1,3}-\d{1,3}_\d+$", "", stem)

    for dt in KNOWN_DATA_TYPES:
        suffix = "_" + dt.lower()
        if stem.endswith(suffix):
            route = stem[: -len(suffix)]
            parts = route.split("_to_")
            if len(parts) != 2:
                return None
            return parts[0], parts[1], dt
    return None


def index_results_folder(results_dir):
    """Map every parseable result CSV in a folder to (src, dst, data_type)."""
    found = {}
    for path in sorted(glob.glob(os.path.join(results_dir, "*.csv"))):
        parsed = parse_result_filename(path)
        if parsed:
            found[parsed] = path
    return found


def find_direction_pairs(indexed, data_type):
    """Return [(fwd_path, rev_path, src, dst)] for one data type."""
    entries = {(s, d): p for (s, d, t), p in indexed.items() if t == data_type}
    pairs, seen = [], set()
    for (src, dst), fwd in sorted(entries.items()):
        if (src, dst) in seen or (dst, src) in seen:
            continue
        rev = entries.get((dst, src))
        if rev is None:
            print(f"  No reverse direction for {src} -> {dst} ({data_type}); "
                  f"cannot separate offset from latency, skipping.")
            continue
        pairs.append((fwd, rev, src, dst))
        seen.add((src, dst))
        seen.add((dst, src))
    return pairs


def pick_one(items, what):
    """Numbered menu returning a single choice."""
    if not items:
        print(f"Nothing to choose for {what}.")
        sys.exit(1)
    if len(items) == 1:
        print(f"\n{what}: only one option, using '{items[0]}'")
        return items[0]

    print(f"\n{what}:\n")
    for i, name in enumerate(items, start=1):
        print(f"  [{i}] {name}")
    while True:
        choice = input("\n  Select a number --> ").strip()
        try:
            idx = int(choice)
        except ValueError:
            print("  Please enter a number.")
            continue
        if 1 <= idx <= len(items):
            return items[idx - 1]
        print(f"  Enter a number between 1 and {len(items)}.")


def load_direction_csv(path):
    df = pd.read_csv(path)

    ts_cols = [c for c in df.columns if "timestamp" in c]
    lat_cols = [c for c in df.columns if "_total_latency" in c]
    if not ts_cols or not lat_cols:
        print(f"ERROR: {path} has no timestamp or _total_latency column")
        sys.exit(1)

    out = pd.DataFrame({
        "timestamp_s": pd.to_numeric(df[ts_cols[0]], errors="coerce"),
        "latency_ms": pd.to_numeric(df[lat_cols[-1]], errors="coerce"),
    }).dropna().sort_values("timestamp_s").reset_index(drop=True)

    if out.empty:
        print(f"ERROR: {path} has no usable numeric rows")
        sys.exit(1)
    return out


def windowed_means(df, t_zero, window_s):
    df = df.copy()
    df["window"] = ((df["timestamp_s"] - t_zero) // window_s) * window_s
    return df.groupby("window").agg(
        latency_ms=("latency_ms", "mean"), n=("latency_ms", "size")
    ).reset_index()


def compute_offset_and_latency(df_a, df_b, window_s):
    t_zero = min(df_a["timestamp_s"].min(), df_b["timestamp_s"].min())
    wa = windowed_means(df_a, t_zero, window_s)
    wb = windowed_means(df_b, t_zero, window_s)

    merged = wa.merge(wb, on="window", suffixes=("_a", "_b"), how="inner")
    if merged.empty:
        print("ERROR: the two directions share no overlapping time windows")
        sys.exit(1)

    merged["offset"] = (merged["latency_ms_b"] - merged["latency_ms_a"]) / 2
    merged["true_latency"] = (merged["latency_ms_a"] + merged["latency_ms_b"]) / 2

    span = merged["window"].iloc[-1] - merged["window"].iloc[0]
    drift = 0.0
    if span > 0 and len(merged) > 1:
        slope = ((merged["offset"] * merged["window"]).mean()
                 - merged["offset"].mean() * merged["window"].mean())
        var = (merged["window"] ** 2).mean() - merged["window"].mean() ** 2
        if var > 0:
            drift = (slope / var) * span

    summary = {
        "n_windows": len(merged),
        "offset_mean": merged["offset"].mean(),
        "offset_std": merged["offset"].std(),
        "offset_min": merged["offset"].min(),
        "offset_max": merged["offset"].max(),
        "offset_drift_over_run": drift,
        "true_latency_mean": merged["true_latency"].mean(),
        "true_latency_median": merged["true_latency"].median(),
        "true_latency_std": merged["true_latency"].std(),
        "run_span_s": span,
    }
    return merged, summary


def plot_pair(merged, a_label, b_label, summary, out_prefix):
    plt.figure(figsize=(14, 6))
    plt.plot(merged["window"], merged["latency_ms_a"], label=f"{a_label} (raw)", marker="o", ms=3)
    plt.plot(merged["window"], merged["latency_ms_b"], label=f"{b_label} (raw)", marker="o", ms=3)
    plt.axhline(0, color="gray", linewidth=0.8)
    plt.xlabel("Elapsed time in run (s)")
    plt.ylabel("Measured latency (ms)")
    plt.title(f"Raw latency, both directions -- mean offset = {summary['offset_mean']:.2f} ms")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.savefig(f"{out_prefix}_raw_directions.png", bbox_inches="tight")
    plt.close()

    plt.figure(figsize=(14, 6))
    plt.plot(merged["window"], merged["offset"], marker="o", ms=3, color="tab:orange")
    plt.axhline(summary["offset_mean"], color="red", linestyle="--",
                label=f"Mean = {summary['offset_mean']:.3f} ms (std {summary['offset_std']:.3f})")
    plt.xlabel("Elapsed time in run (s)")
    plt.ylabel("Clock offset (ms)")
    plt.title("Clock offset over time (not assumed constant)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.savefig(f"{out_prefix}_offset_over_time.png", bbox_inches="tight")
    plt.close()

    plt.figure(figsize=(14, 6))
    plt.plot(merged["window"], merged["true_latency"], marker="o", ms=3, color="tab:blue")
    plt.axhline(summary["true_latency_mean"], color="red", linestyle="--",
                label=f"Mean = {summary['true_latency_mean']:.3f} ms")
    plt.xlabel("Elapsed time in run (s)")
    plt.ylabel("True latency (ms)")
    plt.title("Offset-corrected one-way latency over time")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.savefig(f"{out_prefix}_true_latency.png", bbox_inches="tight")
    plt.close()

    width = merged["window"].diff().median() or 1
    plt.figure(figsize=(14, 4))
    plt.bar(merged["window"], merged["n_a"], alpha=0.5, label=f"{a_label}", width=width)
    plt.bar(merged["window"], merged["n_b"], alpha=0.5, label=f"{b_label}", width=width)
    plt.xlabel("Elapsed time in run (s)")
    plt.ylabel("Samples in window")
    plt.title("Samples per window (short bars = less reliable estimate there)")
    plt.legend()
    plt.grid(True, axis="y", alpha=0.3)
    plt.savefig(f"{out_prefix}_sample_counts.png", bbox_inches="tight")
    plt.close()


def report(merged, summary, src, dst, data_type, run_label, out_prefix, make_plots):
    a_label = f"{src}->{dst}"
    b_label = f"{dst}->{src}"

    print(f"\n=== {run_label}  |  {data_type}  |  {a_label} vs {b_label} ===")
    print(f"  Windows analysed : {summary['n_windows']}")
    print(f"  Clock offset     : mean {summary['offset_mean']:.3f} ms   "
          f"std {summary['offset_std']:.3f}   "
          f"range [{summary['offset_min']:.3f}, {summary['offset_max']:.3f}]")
    print(f"  Offset drift     : {summary['offset_drift_over_run']:.3f} ms "
          f"across {summary['run_span_s']:.0f} s")
    print(f"  TRUE LATENCY     : mean {summary['true_latency_mean']:.3f} ms   "
          f"median {summary['true_latency_median']:.3f} ms   "
          f"std {summary['true_latency_std']:.3f}")

    if summary["true_latency_mean"] < 0:
        print("  WARNING: corrected latency is negative. The input CSVs were")
        print("           probably already offset-corrected; re-run the batch")
        print("           analysis without a clock-offset argument.")

    # Which direction measured negative, and therefore which sign each needs.
    if summary["offset_mean"] >= 0:
        neg_label, pos_label, neg_site = a_label, b_label, src
    else:
        neg_label, pos_label, neg_site = b_label, a_label, dst

    print(f"\n  Correction needed:")
    print(f"    {neg_label:<40} needs -{abs(summary['offset_mean']):.3f} ms")
    print(f"    {pos_label:<40} needs +{abs(summary['offset_mean']):.3f} ms")
    print(f"    batch flags:  --clock-offset-ms {abs(summary['offset_mean']):.3f} "
          f"--offset-negative-from {neg_site}")

    if make_plots:
        os.makedirs(os.path.dirname(out_prefix) or ".", exist_ok=True)
        plot_pair(merged, a_label, b_label, summary, out_prefix)
        print(f"\n  Plots written with prefix: {out_prefix}_*")


def main():
    ap = argparse.ArgumentParser(
        description="Clock offset and true latency, with interactive folder/type selection")
    ap.add_argument("-r", "--results-dir", default=None,
                    help="Results folder to analyse (prompts if omitted)")
    ap.add_argument("-t", "--data-type", default=None,
                    help="Data type to analyse (prompts if omitted)")
    ap.add_argument("--results-root", default="results",
                    help="Where result folders live, used for the folder menu (default: results)")
    ap.add_argument("--all", action="store_true",
                    help="Analyse every data type found, no data-type prompt")
    ap.add_argument("-a", default=None, help="Manual mode: forward direction CSV")
    ap.add_argument("-b", default=None, help="Manual mode: reverse direction CSV")
    ap.add_argument("-o", "--out-prefix", default=None,
                    help="Output path prefix (default: inside the results folder)")
    ap.add_argument("--window", type=float, default=5.0,
                    help="Offset averaging window in seconds (default 5)")
    ap.add_argument("--no-plots", action="store_true", help="Print numbers only")
    args = ap.parse_args()

    make_plots = not args.no_plots

    # ---- manual mode -------------------------------------------------------
    if args.a or args.b:
        if not (args.a and args.b):
            print("ERROR: manual mode needs both -a and -b")
            sys.exit(1)
        pa = parse_result_filename(args.a)
        pb = parse_result_filename(args.b)
        src, dst = (pa[0], pa[1]) if pa else ("A", "B")
        data_type = pa[2] if pa else "unknown"
        out_prefix = args.out_prefix or os.path.join(
            os.path.dirname(args.a) or ".", f"clock_offset_{data_type.lower()}")
        merged, summary = compute_offset_and_latency(
            load_direction_csv(args.a), load_direction_csv(args.b), args.window)
        run_label = os.path.basename(os.path.dirname(os.path.abspath(args.a))) or "manual"
        report(merged, summary, src, dst, data_type, run_label, out_prefix, make_plots)
        return

    # ---- pick the results folder ------------------------------------------
    results_dir = args.results_dir
    if results_dir is None:
        if not os.path.isdir(args.results_root):
            print(f"Results root not found: {args.results_root}")
            print("Pass -r <folder> or --results-root <dir>.")
            sys.exit(1)
        candidates = sorted(
            d for d in os.listdir(args.results_root)
            if os.path.isdir(os.path.join(args.results_root, d))
        )
        if not candidates:
            print(f"No result folders inside {args.results_root}")
            sys.exit(1)
        results_dir = os.path.join(
            args.results_root,
            pick_one(candidates, f"Result folders in {args.results_root}"))

    if not os.path.isdir(results_dir):
        print(f"Not a folder: {results_dir}")
        sys.exit(1)

    # ---- index it and pick the data type ----------------------------------
    indexed = index_results_folder(results_dir)
    if not indexed:
        print(f"\nNo recognisable result CSVs in {results_dir}")
        print("Expected names like  <site_a>_to_<site_b>_<DataType>*.csv")
        sys.exit(1)

    available = sorted({t for (_, _, t) in indexed})
    print(f"\nFound {len(indexed)} result file(s) in {os.path.basename(results_dir)}")
    print(f"Data types present: {', '.join(available)}")

    if args.all:
        chosen = available
    elif args.data_type:
        if args.data_type not in available:
            print(f"\nERROR: '{args.data_type}' not present. Available: {available}")
            sys.exit(1)
        chosen = [args.data_type]
    else:
        chosen = [pick_one(available, "Data types available")]

    run_label = os.path.basename(os.path.abspath(results_dir))

    analysed = 0
    for data_type in chosen:
        for fwd, rev, src, dst in find_direction_pairs(indexed, data_type):
            merged, summary = compute_offset_and_latency(
                load_direction_csv(fwd), load_direction_csv(rev), args.window)
            base = args.out_prefix or os.path.join(results_dir, "clock_offset")
            out_prefix = f"{base}_{data_type.lower()}"
            report(merged, summary, src, dst, data_type, run_label,
                   out_prefix, make_plots)
            analysed += 1

    if analysed == 0:
        print("\nNothing analysed: no data type had both directions present.")
        sys.exit(1)


if __name__ == "__main__":
    main()