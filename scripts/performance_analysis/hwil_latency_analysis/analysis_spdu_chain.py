"""Measure per-message latency along a chain of PCAP captures by matching 1609.2 signatures."""

import logging
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

import Ieee1609dot2
from analysis_pcap import LATENCY_THRESHOLDS_MS, get_pcaps
from pcap_frames import Address, FrameInfo, parse_frame, read_pcap
from plots_and_summaries import (
    LATENCY_COLUMN,
    TX_TIMESTAMP_COLUMN,
    add_threshold_summary,
    calculate_statistics,
    plot_chain_e2e_histogram,
    plot_chain_per_message,
    plot_chain_stage_boxplot,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from e2e_utils.spdu_utils import locate_spdu  # noqa: E402

REFERENCE = "dut_1_tx"
STAGES = (REFERENCE, "proxy_1_rx", "proxy_2_tx", "dut_2_rx")
DOWNSTREAM = STAGES[1:]
STAGE_LABELS = {
    "dut_1_tx": "DUT1 tx",
    "proxy_1_rx": "Proxy1 rx",
    "proxy_2_tx": "Proxy2 tx",
    "dut_2_rx": "DUT2 rx",
}
# Latency limits relative to the DUT1 send time; None means no limit is defined.
CHAIN_THRESHOLDS_MS = {
    "proxy_1_rx": LATENCY_THRESHOLDS_MS[("dut", "proxy")],
    "proxy_2_tx": None,
    "dut_2_rx": LATENCY_THRESHOLDS_MS[("dut", "dut")],
}
OUTPUT_SUBDIR = Path("pcap") / "full_chain"
ANOMALY_EXAMPLES = 3

Keep = Callable[[FrameInfo], bool]


@dataclass
class ChainFilters:
    """Address overrides for the per-stage frame filters; None keeps the default."""

    dut1_dst: set[Address] | None = None
    proxy1_src: set[Address] | None = None
    dut2_src: set[Address] | None = None


@dataclass(frozen=True)
class SpduRecord:
    """One captured copy of a signed SPDU."""

    timestamp: float
    spdu: str
    psid: int | None


def capture_sources(path: Path) -> set[Address]:
    """Return every source address of the payload-carrying frames in a capture."""
    sources: set[Address] = set()
    for _, frame, linktype in read_pcap(path):
        info = parse_frame(frame, linktype)
        if info.payload:
            sources |= info.src
    return sources


def derive_filters(captures: dict[str, Path], overrides: ChainFilters) -> dict[str, tuple[Keep, str]]:
    """Build a frame filter and its description for each stage.

    Defaults: dut_1_tx keeps outgoing frames (all frames if direction is unknown);
    proxy_1_rx drops frames sourced by the proxy_2_tx sender; dut_2_rx keeps all frames.
    Each override keeps only frames whose destination (DUT1) or source matches it.
    """
    filters: dict[str, tuple[Keep, str]] = {}

    if overrides.dut1_dst:
        filters["dut_1_tx"] = (lambda f, a=overrides.dut1_dst: not f.dst.isdisjoint(a),
                               f"dst in {_fmt_addresses(overrides.dut1_dst)}")
    else:
        filters["dut_1_tx"] = (lambda f: f.outgoing is not False, "outgoing frames")

    if overrides.proxy1_src:
        filters["proxy_1_rx"] = (lambda f, a=overrides.proxy1_src: not f.src.isdisjoint(a),
                                 f"src in {_fmt_addresses(overrides.proxy1_src)}")
    elif "proxy_2_tx" in captures:
        excluded = capture_sources(captures["proxy_2_tx"])
        filters["proxy_1_rx"] = (lambda f, a=excluded: f.src.isdisjoint(a),
                                 f"src not in {_fmt_addresses(excluded)}")
    else:
        filters["proxy_1_rx"] = (lambda f: True, "all frames")

    filters["proxy_2_tx"] = (lambda f: True, "all frames")

    if overrides.dut2_src:
        filters["dut_2_rx"] = (lambda f, a=overrides.dut2_src: not f.src.isdisjoint(a),
                               f"src in {_fmt_addresses(overrides.dut2_src)}")
    else:
        filters["dut_2_rx"] = (lambda f: True, "all frames")

    return filters


def _fmt_addresses(addresses: set[Address]) -> str:
    return "{" + ", ".join(sorted(map(str, addresses))) + "}"


def signature_key(signature) -> str:
    """Return rSig value || sSig as hex from a pycrate Signature value."""
    _, ecdsa = signature
    r_sig = ecdsa["rSig"]
    if isinstance(r_sig, tuple):  # EccP256CurvePoint / EccP384CurvePoint CHOICE
        r_sig = r_sig[1]
    if isinstance(r_sig, dict):  # uncompressed point
        r_sig = r_sig["x"] + r_sig["y"]
    return ((r_sig or b"") + ecdsa["sSig"]).hex()


def load_signed_spdus(path: Path, keep: Keep) -> tuple[dict[str, list[SpduRecord]], int]:
    """Decode the signed SPDUs of the frames that pass `keep`, grouped by signature.

    Returns:
        (signature -> copies sorted by timestamp, number of frames dropped by `keep`).
    """
    data = Ieee1609dot2.Ieee1609Dot2.Ieee1609Dot2Data
    by_signature: defaultdict[str, list[SpduRecord]] = defaultdict(list)
    n_dropped = 0

    for timestamp, frame, linktype in read_pcap(path):
        info = parse_frame(frame, linktype)
        if not info.payload:
            continue
        if not keep(info):
            n_dropped += 1
            continue

        spdu_info = locate_spdu(info.payload)
        if not (spdu_info.anchored and spdu_info.is_signed):
            continue
        start = spdu_info.spdu_offset
        end = start + spdu_info.wsm_length if spdu_info.wsm_length is not None else None
        spdu = info.payload[start:end]
        try:
            data.from_coer(spdu)
            signed = ["content", "signedData"]
            signature = signature_key(data.get_val_at(signed + ["signature"]))
            psid = data.get_val_at(signed + ["tbsData", "headerInfo", "psid"])
        except Exception as error:
            logging.debug("Skipping undecodable SPDU at %.6f in %s: %s", timestamp, path.name, error)
            continue
        by_signature[signature].append(SpduRecord(timestamp, spdu.hex(), psid))

    for copies in by_signature.values():
        copies.sort(key=lambda record: record.timestamp)
    return dict(by_signature), n_dropped


def find_anomalies(row: dict) -> list[str]:
    """Return anomaly tags for one matched message.

    Tags: ``missing:<stage>`` (never captured), ``negative:<stage>`` (captured before
    the reference send), ``order:<a>><b>`` (captured before an earlier stage) and
    ``spdu_mismatch:<stage>`` (same signature, different SPDU bytes).
    """
    tags = []
    prev_stage, prev_t = REFERENCE, row[f"t_{REFERENCE}"]
    for stage in DOWNSTREAM:
        if f"t_{stage}" not in row:
            continue
        t = row[f"t_{stage}"]
        if t is None:
            tags.append(f"missing:{stage}")
            continue
        if t < row[f"t_{REFERENCE}"]:
            tags.append(f"negative:{stage}")
        elif t < prev_t:
            tags.append(f"order:{prev_stage}>{stage}")
        if row[f"spdu_{stage}"] != row["spdu_hex"]:
            tags.append(f"spdu_mismatch:{stage}")
        prev_stage, prev_t = stage, t
    return tags


def match_chain(stages: dict[str, dict[str, list[SpduRecord]]]) -> pd.DataFrame:
    """Match every reference signature to its earliest copy at each downstream stage.

    No ordering in time is assumed; time inconsistencies are reported by find_anomalies.

    Returns:
        One row per reference signature, sorted by reference send time, with columns
        signature, psid, spdu_hex, t_<stage>, lat_<stage>_ms, n_<stage> and anomalies.
    """
    downstream = [stage for stage in DOWNSTREAM if stage in stages]
    rows = []
    for signature, copies in stages[REFERENCE].items():
        sent = copies[0]
        row = {"signature": signature, "psid": sent.psid, "spdu_hex": sent.spdu,
               f"t_{REFERENCE}": sent.timestamp}
        for stage in downstream:
            first = stages[stage].get(signature, [None])[0]
            row[f"t_{stage}"] = first.timestamp if first else None
            row[f"lat_{stage}_ms"] = (first.timestamp - sent.timestamp) * 1000 if first else None
            row[f"spdu_{stage}"] = first.spdu if first else None
        for stage in (REFERENCE, *downstream):
            row[f"n_{stage}"] = len(stages[stage].get(signature, []))
        row["anomalies"] = ";".join(find_anomalies(row))
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    table = pd.DataFrame(rows).sort_values(f"t_{REFERENCE}", ignore_index=True)
    return table.drop(columns=[f"spdu_{stage}" for stage in downstream])


def anomaly_counts(table: pd.DataFrame) -> Counter:
    """Count anomaly tags across all rows."""
    return Counter(tag for tags in table["anomalies"] for tag in tags.split(";") if tag)


def summarize(table: pd.DataFrame, run_name: str) -> pd.DataFrame:
    """Build one summary row per downstream stage with statistics, threshold result and anomaly counts."""
    counts = anomaly_counts(table)
    summaries = []
    for stage in DOWNSTREAM:
        column = f"lat_{stage}_ms"
        if column not in table:
            continue
        latency_data = pd.DataFrame({
            LATENCY_COLUMN: table[column],
            TX_TIMESTAMP_COLUMN: table[f"t_{REFERENCE}"] * 1000,
        }).dropna()
        route = f"{REFERENCE.rsplit('_', 1)[0]}->{stage.rsplit('_', 1)[0]}"
        threshold = CHAIN_THRESHOLDS_MS[stage]

        if latency_data.empty:
            summary = {"message_type": route, "run_name": run_name, "samples": 0,
                       "latency_threshold_ms": threshold, "threshold_result": "FAIL"}
        else:
            summary = calculate_statistics(latency_data, message_type=route, run_name=run_name)
            add_threshold_summary(summary, latency_data, threshold=threshold)

        summary.update({
            "sent": len(table),
            "missing": counts[f"missing:{stage}"],
            "negative": counts[f"negative:{stage}"],
            "out_of_order": sum(n for tag, n in counts.items()
                                if tag.startswith("order:") and tag.endswith(f">{stage}")),
            "spdu_mismatch": counts[f"spdu_mismatch:{stage}"],
        })
        summaries.append(summary)
    return pd.DataFrame(summaries)


def repeats_table(stages: dict[str, dict[str, list[SpduRecord]]]) -> pd.DataFrame:
    """List reference signatures captured more than once at any stage, with every timestamp."""
    rows = []
    for signature, sent in stages[REFERENCE].items():
        copies = {stage: stages[stage].get(signature, []) for stage in stages}
        if all(len(c) <= 1 for c in copies.values()):
            continue
        row = {"signature": signature, f"t_{REFERENCE}": sent[0].timestamp}
        row.update({f"n_{stage}": len(c) for stage, c in copies.items()})
        row.update({f"timestamps_{stage}": ";".join(f"{r.timestamp:.6f}" for r in c)
                    for stage, c in copies.items()})
        rows.append(row)
    if not rows:
        return pd.DataFrame(columns=["signature"])
    return pd.DataFrame(rows).sort_values(f"t_{REFERENCE}", ignore_index=True)


def log_anomalies(table: pd.DataFrame) -> None:
    """Log each anomaly tag's count with a few example signatures."""
    counts = anomaly_counts(table)
    if not counts:
        logging.info("No matching anomalies")
        return
    for tag, count in sorted(counts.items()):
        examples = table.loc[table["anomalies"].str.split(";").apply(lambda tags: tag in tags),
                             "signature"].head(ANOMALY_EXAMPLES)
        logging.warning("Anomaly %s: %d (e.g. %s)", tag, count,
                        ", ".join(s[:16] for s in examples))


def run_spdu_chain_analysis(
    input_dir: Path,
    results_dir: Path,
    overrides: ChainFilters | None = None,
) -> int:
    """Match signed SPDUs across the chain captures of one run and write reports.

    Returns:
        0 on success or when the run has no chain captures, 1 on error.
    """
    pcap_root = input_dir / "pcap"
    if not pcap_root.is_dir():
        logging.info("Skipping SPDU chain analysis because the PCAP directory is missing")
        return 0

    try:
        captures = {name: path for name, path in get_pcaps(pcap_root).items() if name in STAGES}
        if REFERENCE not in captures or len(captures) < 2:
            logging.info("Skipping SPDU chain analysis: need %s and at least one of %s",
                         REFERENCE, ", ".join(DOWNSTREAM))
            return 0

        filters = derive_filters(captures, overrides or ChainFilters())
        stages: dict[str, dict[str, list[SpduRecord]]] = {}
        for stage in STAGES:
            if stage not in captures:
                continue
            keep, description = filters[stage]
            stages[stage], n_dropped = load_signed_spdus(captures[stage], keep)
            logging.info("%s: %d signed SPDUs, %d unique signatures (kept %s; dropped %d frames)",
                         stage, sum(map(len, stages[stage].values())), len(stages[stage]),
                         description, n_dropped)

        table = match_chain(stages)
        if table.empty:
            logging.warning("No signed SPDUs found in %s", captures[REFERENCE])
            return 0

        output_dir = results_dir / OUTPUT_SUBDIR
        output_dir.mkdir(parents=True, exist_ok=True)
        table.to_csv(output_dir / "latency_results.csv", index=False, float_format="%.6f")
        repeats_table(stages).to_csv(output_dir / "spdu_repeats.csv", index=False)
        summary = summarize(table, run_name=input_dir.name)
        summary.to_csv(output_dir / "results_summary.csv", index=False)

        labels = {stage: STAGE_LABELS[stage] for stage in STAGES if stage in stages}
        plot_chain_e2e_histogram(table, output_dir, labels)
        plot_chain_stage_boxplot(table, output_dir, labels)
        plot_chain_per_message(table, output_dir, labels)

        log_anomalies(table)
        for _, row in summary.iterrows():
            logging.info("%s: %s/%s matched, median %s ms, threshold %s",
                         row["message_type"], row["samples"], row["sent"],
                         row.get("median_ms"), row["threshold_result"])
        return 0

    except Exception:
        logging.exception("SPDU chain analysis failed for run %s", input_dir.name)
        return 1
