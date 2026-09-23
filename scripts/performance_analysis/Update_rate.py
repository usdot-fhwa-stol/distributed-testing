"""
analyze_update_rate_v2.py

Measures the motion-update rate (position message frequency) of LandVehicle
and VulnerableRoadUser SDOs, from exported TDCS CSVs.

METHOD
    Rows are grouped by entity identifier and sorted by time. Intervals are the
    differences between successive timestamps.

    THREE rate metrics are reported, because they answer different questions
    and can disagree sharply when publishing is irregular:

      overall_hz   (messages - 1) / (last_timestamp - first_timestamp)
                   The SUSTAINED rate. This is the honest headline number: it
                   cannot be fooled by burstiness or by outliers, because it
                   only looks at total count over total elapsed time.

      mean_hz      1 / mean(interval)
                   Pulled DOWN by long gaps.

      median_hz    1 / median(interval)
                   Describes the typical spacing, NOT the rate. For bursty
                   publishers (several messages milliseconds apart, then a long
                   gap) the median interval sits between the burst spacing and
                   the gap and corresponds to no real rate at all. Observed in
                   real data: a LandVehicle publishing a true 10.000 Hz showed
                   a median interval of 68 ms (= 14.7 Hz), which is wrong.

    ==> Report overall_hz as the update rate. Use the interval percentiles and
        the burstiness ratio to describe HOW EVENLY that rate is delivered.

    Regularity metrics:
      p01/p25/p50/p75/p99_interval_ms   shape of the interval distribution
      burstiness         = p99_interval / p01_interval. Near 1 means
                           metronomic; large means clumped delivery.
      pct_off_nominal    = share of intervals more than TOLERANCE away from
                           the median interval (default 20%).
      is_bursty          True when burstiness exceeds BURSTY_RATIO.

    Two timestamp sources are used:
      send_*     from "Metadata,TimeOfCommit"  (column E) -- stamped by the
                 PUBLISHER, so identical in every site's recording of the same
                 SDO. Measures how fast the owning adapter publishes.
      recv_*     from "Metadata,TimeOfReceipt" (column F) -- stamped LOCALLY by
                 whichever site recorded the file, so this is the
                 direction-specific arrival rate.

    Discovery / Destruction events are excluded; they are not periodic updates.

DIRECTORY LAYOUT EXPECTED
    <root>/<TestFolder>/<RunFolder>/<SiteFolder>/exported_tdcs/VUG-Entities-*.csv

USAGE
    python3 analyze_update_rate_v2.py [-r <root dir>] [-o <output csv>]
                                      [--tolerance 0.20] [--bursty-ratio 5.0]
    Prompts for which test folder(s) to analyze.
"""

import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd

# SDO types whose update rate we care about (filename fragment -> label)
SDO_TYPES = {
    "VulnerableRoadUser": "VulnerableRoadUser",
    "LandVehicle": "LandVehicle",
}

COMMIT_COL = "Metadata,TimeOfCommit"
RECEIPT_COL = "Metadata,TimeOfReceipt"
EVENT_COL = "Metadata,Enum,Middleware::EventType"
IDENT_COL = "const^identifier,String"
OWNER_COL = "const^Metadata,SDOid.hostIPaddress"

EXCLUDED_EVENTS = {"Discovery", "Destruction"}


def pick_from_list(items, what):
    """Show a numbered list and let the user select one or more entries."""
    print(f"\n{what}:\n")
    for i, name in enumerate(items, start=1):
        print(f"  [{i}] {name}")
    print("\nSelect by number (comma separated), or 'all':")
    choice = input("  --> ").strip()

    if choice.lower() == "all":
        return items

    selected = []
    for token in choice.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            idx = int(token)
        except ValueError:
            print(f"  Ignoring invalid entry: {token}")
            continue
        if 1 <= idx <= len(items):
            selected.append(items[idx - 1])
        else:
            print(f"  Ignoring out-of-range entry: {idx}")

    if not selected:
        print("Nothing selected, exiting")
        sys.exit(1)
    return selected


def interval_stats(series_ns, tolerance, bursty_ratio):
    """Given a Series of nanosecond timestamps, return interval/rate stats."""
    t = pd.to_numeric(series_ns, errors="coerce").dropna().sort_values()
    if len(t) < 2:
        return None

    span_s = (t.iloc[-1] - t.iloc[0]) / 1e9
    if span_s <= 0:
        return None

    intervals_s = t.diff().dropna() / 1e9
    # Non-positive intervals mean duplicate or out-of-order timestamps; they
    # cannot be turned into a rate, so exclude them but report the count.
    nonpositive = int((intervals_s <= 0).sum())
    intervals_s = intervals_s[intervals_s > 0]
    if intervals_s.empty:
        return None

    ms = intervals_s * 1000.0
    p01, p25, p50, p75, p99 = (float(np.percentile(ms, p)) for p in (1, 25, 50, 75, 99))

    burstiness = (p99 / p01) if p01 > 0 else float("nan")
    off_nominal = float((np.abs(ms - p50) > tolerance * p50).mean() * 100.0) if p50 > 0 else float("nan")

    return {
        # counts / span
        "samples": int(len(t)),
        "duration_s": span_s,
        "nonpositive_intervals": nonpositive,
        # rates
        "overall_hz": (len(t) - 1) / span_s,
        "mean_hz": 1.0 / intervals_s.mean(),
        "median_hz": 1.0 / intervals_s.median(),
        # intervals
        "mean_interval_ms": float(ms.mean()),
        "median_interval_ms": p50,
        "min_interval_ms": float(ms.min()),
        "max_interval_ms": float(ms.max()),
        "p01_interval_ms": p01,
        "p25_interval_ms": p25,
        "p75_interval_ms": p75,
        "p99_interval_ms": p99,
        # regularity
        "burstiness": burstiness,
        "pct_off_nominal": off_nominal,
        "is_bursty": bool(burstiness > bursty_ratio) if burstiness == burstiness else False,
    }


def analyze_file(csv_path, test_name, run_name, site_name, sdo_label,
                 tolerance, bursty_ratio):
    """Return one row of stats per entity found in the file."""
    try:
        df = pd.read_csv(csv_path, low_memory=False)
    except Exception as e:
        print(f"      ERROR reading {csv_path}: {e}")
        return []

    for required in (COMMIT_COL, RECEIPT_COL):
        if required not in df.columns:
            print(f"      SKIP (no '{required}' column): {os.path.basename(csv_path)}")
            return []

    if EVENT_COL in df.columns:
        before = len(df)
        df = df[~df[EVENT_COL].isin(EXCLUDED_EVENTS)]
        dropped = before - len(df)
    else:
        dropped = 0

    if df.empty:
        print(f"      SKIP (no update rows): {os.path.basename(csv_path)}")
        return []

    groups = df.groupby(IDENT_COL) if IDENT_COL in df.columns else [("<unknown>", df)]

    rows = []
    for identifier, g in groups:
        owner = g[OWNER_COL].iloc[0] if OWNER_COL in g.columns else ""

        send = interval_stats(g[COMMIT_COL], tolerance, bursty_ratio)
        recv = interval_stats(g[RECEIPT_COL], tolerance, bursty_ratio)
        if send is None and recv is None:
            continue

        row = {
            "test": test_name,
            "run": run_name,
            "recorded_by_site": site_name,
            "sdo_type": sdo_label,
            "entity": identifier,
            "published_by_ip": owner,
            "excluded_event_rows": dropped,
            "file": os.path.basename(csv_path),
        }

        for prefix, stats in (("send", send), ("recv", recv)):
            if stats is None:
                continue
            row[f"{prefix}_samples"] = stats["samples"]
            row[f"{prefix}_duration_s"] = round(stats["duration_s"], 2)
            # headline rate first
            row[f"{prefix}_overall_hz"] = round(stats["overall_hz"], 4)
            row[f"{prefix}_mean_hz"] = round(stats["mean_hz"], 4)
            row[f"{prefix}_median_hz"] = round(stats["median_hz"], 4)
            row[f"{prefix}_mean_interval_ms"] = round(stats["mean_interval_ms"], 4)
            row[f"{prefix}_median_interval_ms"] = round(stats["median_interval_ms"], 4)
            row[f"{prefix}_min_interval_ms"] = round(stats["min_interval_ms"], 4)
            row[f"{prefix}_p01_interval_ms"] = round(stats["p01_interval_ms"], 4)
            row[f"{prefix}_p25_interval_ms"] = round(stats["p25_interval_ms"], 4)
            row[f"{prefix}_p75_interval_ms"] = round(stats["p75_interval_ms"], 4)
            row[f"{prefix}_p99_interval_ms"] = round(stats["p99_interval_ms"], 4)
            row[f"{prefix}_max_interval_ms"] = round(stats["max_interval_ms"], 4)
            row[f"{prefix}_burstiness"] = round(stats["burstiness"], 2)
            row[f"{prefix}_pct_off_nominal"] = round(stats["pct_off_nominal"], 2)
            row[f"{prefix}_is_bursty"] = stats["is_bursty"]
            row[f"{prefix}_nonpositive_intervals"] = stats["nonpositive_intervals"]

        rows.append(row)

        flag = "  <-- BURSTY" if row.get("send_is_bursty") else ""
        print(f"      {identifier:<16} {sdo_label:<19} "
              f"overall send {row.get('send_overall_hz', float('nan')):7.3f} Hz  "
              f"recv {row.get('recv_overall_hz', float('nan')):7.3f} Hz   "
              f"median int {row.get('send_median_interval_ms', float('nan')):7.2f} ms  "
              f"burstiness {row.get('send_burstiness', float('nan')):6.1f}"
              f"{flag}")

    return rows


def main():
    ap = argparse.ArgumentParser(description="Motion update rate (Hz) from exported TDCS CSVs")
    ap.add_argument("-r", "--root",
                    default=os.path.expanduser("~/distributed-testing/logs/Local_testing"),
                    help="Directory containing the test folders")
    ap.add_argument("-o", "--outfile", default="update_rate_analysis.csv",
                    help="Where to write the per-entity results")
    ap.add_argument("--tolerance", type=float, default=0.20,
                    help="Fractional deviation from the median interval that counts "
                         "as off-nominal (default 0.20 = 20%%)")
    ap.add_argument("--bursty-ratio", type=float, default=5.0,
                    help="p99/p01 interval ratio above which delivery is flagged bursty "
                         "(default 5.0)")
    args = ap.parse_args()

    if not os.path.isdir(args.root):
        print(f"Root directory not found: {args.root}")
        sys.exit(1)

    tests = sorted(d for d in os.listdir(args.root)
                   if os.path.isdir(os.path.join(args.root, d)))
    if not tests:
        print(f"No test folders found in {args.root}")
        sys.exit(1)

    selected_tests = pick_from_list(tests, f"Test folders in {args.root}")

    all_rows = []

    for test_name in selected_tests:
        test_path = os.path.join(args.root, test_name)
        print(f"\n=== TEST: {test_name}")

        runs = sorted(d for d in os.listdir(test_path)
                      if os.path.isdir(os.path.join(test_path, d)))
        for run_name in runs:
            run_path = os.path.join(test_path, run_name)
            sites = sorted(d for d in os.listdir(run_path)
                           if os.path.isdir(os.path.join(run_path, d))
                           and d != "generated_import_files")
            if not sites:
                continue
            print(f"  RUN: {run_name}")

            for site_name in sites:
                tdcs_dir = os.path.join(run_path, site_name, "exported_tdcs")
                if not os.path.isdir(tdcs_dir):
                    continue
                print(f"    SITE: {site_name}")

                found_any = False
                for fragment, label in SDO_TYPES.items():
                    for csv_path in sorted(glob.glob(os.path.join(tdcs_dir, f"*{fragment}*.csv"))):
                        found_any = True
                        all_rows.extend(analyze_file(
                            csv_path, test_name, run_name, site_name, label,
                            args.tolerance, args.bursty_ratio))
                if not found_any:
                    print("      (no LandVehicle / VulnerableRoadUser exports here)")

    if not all_rows:
        print("\nNo usable files found. Check the -r root path and folder layout.")
        sys.exit(1)

    results = pd.DataFrame(all_rows)
    results.to_csv(args.outfile, index=False)

    print("\n\n================ SUMMARY ================")
    print("NOTE: overall_hz is the sustained update rate and is the number to")
    print("      report. median_interval_ms describes regularity, not rate --")
    print("      for a bursty publisher it corresponds to no real rate.")

    summary_cols = [c for c in ("send_overall_hz", "recv_overall_hz",
                                "send_median_interval_ms", "send_p99_interval_ms",
                                "send_burstiness", "send_pct_off_nominal")
                    if c in results.columns]

    for keys, title in ((["sdo_type"], "By SDO type"),
                        (["test", "sdo_type"], "By test and SDO type"),
                        (["test", "run", "sdo_type"], "By test, run and SDO type")):
        print(f"\n--- {title} ---")
        grouped = results.groupby(keys)[summary_cols].mean().round(3)
        counts = results.groupby(keys).size().rename("entities")
        print(pd.concat([grouped, counts], axis=1).to_string())

    print("\n--- Overall average across everything selected ---")
    for col, label in (("send_overall_hz", "SUSTAINED send rate (Hz)"),
                       ("recv_overall_hz", "SUSTAINED recv rate (Hz)"),
                       ("send_median_interval_ms", "median send interval (ms)"),
                       ("send_p99_interval_ms", "p99 send interval (ms)"),
                       ("send_burstiness", "burstiness (p99/p01)")):
        if col in results.columns:
            s = results[col].dropna()
            if not s.empty:
                print(f"  {label:<28} mean {s.mean():9.3f}   min {s.min():9.3f}   max {s.max():9.3f}")

    if "send_is_bursty" in results.columns:
        bursty = results[results["send_is_bursty"] == True]
        if not bursty.empty:
            print(f"\n--- Bursty publishers (p99/p01 interval > {args.bursty_ratio}) ---")
            print("These deliver their nominal rate unevenly: a consumer expecting")
            print("evenly spaced updates will see stale data for up to p99 ms.")
            cols = ["test", "run", "recorded_by_site", "sdo_type", "entity",
                    "send_overall_hz", "send_median_interval_ms",
                    "send_p99_interval_ms", "send_max_interval_ms", "send_burstiness"]
            print(bursty[[c for c in cols if c in bursty.columns]].to_string(index=False))
        else:
            print(f"\nNo bursty publishers found (all p99/p01 <= {args.bursty_ratio}).")

    print(f"\nPer-entity detail written to: {args.outfile}")


if __name__ == "__main__":
    main()