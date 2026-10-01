"""Extract and plot the GPS positions of DUT 1 BSMs as received by DUT 2."""

import argparse
import logging
import math
import sys
from pathlib import Path

import pandas as pd
from j2735_202409 import MessageFrame

import Ieee1609dot2
from analysis_pcap import get_pcaps
from analysis_spdu_chain import load_signed_spdus, signature_key
from pcap_frames import parse_frame, read_pcap
from plots_and_summaries import plot_bsm_track

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from e2e_utils.spdu_utils import locate_spdu  # noqa: E402

SENDER_CAPTURE = "dut_1_tx"
CAPTURE = "dut_2_rx"
OUTPUT_SUBDIR = Path("pcap") / "dut_2_bsm_gps"
PLOT_TITLE = "GPS trajectory in BSM received by DUT2"
BSM_MESSAGE_ID = 20

# J2735 units and "unavailable" sentinels
LAT_LON_SCALE = 1e-7          # 1/10 microdegree
LAT_UNAVAILABLE = 900000001
LON_UNAVAILABLE = 1800000001
ELEV_SCALE = 0.1              # m
ELEV_UNAVAILABLE = -4096
SPEED_SCALE = 0.02            # m/s
SPEED_UNAVAILABLE = 8191
HEADING_SCALE = 0.0125        # degrees
HEADING_UNAVAILABLE = 28800

EARTH_RADIUS_M = 6371008.8


def extract_j2735(payload: bytes) -> tuple[bytes, str | None] | None:
    """Return (J2735 UPER bytes, signature hex or None) carried by a payload.

    Handles signed and unsigned 1609.2 SPDUs; returns None when no SPDU is found.
    """
    spdu_info = locate_spdu(payload)
    if not (spdu_info.recognised and spdu_info.anchored):
        return None
    if spdu_info.content_choice not in ("signedData", "unsecuredData"):
        return None

    start = spdu_info.spdu_offset
    end = start + spdu_info.wsm_length if spdu_info.wsm_length is not None else None
    data = Ieee1609dot2.Ieee1609Dot2.Ieee1609Dot2Data
    try:
        data.from_coer(payload[start:end])
        if spdu_info.is_signed:
            signed = ["content", "signedData"]
            choice, inner = data.get_val_at(signed + ["tbsData", "payload", "data", "content"])
            if choice != "unsecuredData":
                return None
            return inner, signature_key(data.get_val_at(signed + ["signature"]))
        return data.get_val_at(["content"])[1], None
    except Exception:
        return None


def _scaled(value: int, scale: float, unavailable: int) -> float | None:
    return None if value == unavailable else value * scale


def decode_bsm(uper: bytes) -> dict | None:
    """Decode a J2735 MessageFrame and return the BSM core fields, or None if it is not a BSM."""
    try:
        MessageFrame.MessageFrame.from_uper(uper)
    except Exception:
        return None
    frame = MessageFrame.MessageFrame.get_val()
    if frame["messageId"] != BSM_MESSAGE_ID:
        return None
    core = frame["value"][1]["coreData"]
    return {
        "bsm_id": core["id"].hex(),
        "msg_cnt": core["msgCnt"],
        "sec_mark": core["secMark"],
        "lat_deg": _scaled(core["lat"], LAT_LON_SCALE, LAT_UNAVAILABLE),
        "lon_deg": _scaled(core["long"], LAT_LON_SCALE, LON_UNAVAILABLE),
        "elev_m": _scaled(core["elev"], ELEV_SCALE, ELEV_UNAVAILABLE),
        "speed_mps": _scaled(core["speed"], SPEED_SCALE, SPEED_UNAVAILABLE),
        "heading_deg": _scaled(core["heading"], HEADING_SCALE, HEADING_UNAVAILABLE),
    }


def sent_signatures(path: Path) -> set[str]:
    """Return the signatures of the signed SPDUs sent by the capturing host."""
    sent, _ = load_signed_spdus(path, lambda frame: frame.outgoing is not False)
    return set(sent)


def load_received_bsms(path: Path, signatures: set[str] | None = None) -> pd.DataFrame:
    """Decode the BSMs received in a capture, keeping one row per signed message.

    Frames the capturing host sent are skipped. Signed messages captured more than
    once are reduced to their first copy, with the count kept in ``copies``.

    Args:
        path: Capture taken on the receiving device.
        signatures: If given, keep only signed BSMs with one of these signatures.

    Returns:
        One row per BSM with timestamp, src, signature, copies and the BSM core fields.
    """
    rows: list[dict] = []
    first_row: dict[str, dict] = {}

    for timestamp, frame, linktype in read_pcap(path):
        info = parse_frame(frame, linktype)
        if not info.payload or info.outgoing:
            continue
        extracted = extract_j2735(info.payload)
        if extracted is None:
            continue
        uper, signature = extracted
        if signatures is not None and signature not in signatures:
            continue

        if signature is not None and signature in first_row:
            first_row[signature]["copies"] += 1
            continue
        bsm = decode_bsm(uper)
        if bsm is None:
            continue

        row = {"timestamp": timestamp, "src": ",".join(sorted(map(str, info.src))),
               "signature": signature, "copies": 1, **bsm}
        rows.append(row)
        if signature is not None:
            first_row[signature] = row

    return pd.DataFrame(rows)


def add_local_offsets(bsms: pd.DataFrame) -> None:
    """Add east_m / north_m columns, measured from each sender's first valid fix."""
    bsms["east_m"] = float("nan")
    bsms["north_m"] = float("nan")
    for _, group in bsms.dropna(subset=["lat_deg", "lon_deg"]).groupby("src"):
        ref_lat, ref_lon = group.iloc[0][["lat_deg", "lon_deg"]]
        metres_per_degree = EARTH_RADIUS_M * math.radians(1)
        bsms.loc[group.index, "east_m"] = (
            metres_per_degree * (group["lon_deg"] - ref_lon) * math.cos(math.radians(ref_lat))
        )
        bsms.loc[group.index, "north_m"] = metres_per_degree * (group["lat_deg"] - ref_lat)


def analyze_capture(
    pcap_path: Path,
    output_dir: Path,
    title: str,
    signatures: set[str] | None = None,
) -> pd.DataFrame:
    """Write bsm_positions.csv and bsm_gps_track.png for the BSMs received in one capture.

    Args:
        pcap_path: Capture taken on the receiving device.
        output_dir: Directory for the outputs.
        title: Plot title.
        signatures: If given, keep only signed BSMs with one of these signatures.
    """
    bsms = load_received_bsms(pcap_path, signatures)
    if bsms.empty or bsms[["lat_deg", "lon_deg"]].dropna().empty:
        logging.warning("No BSMs with a position received in %s", pcap_path)
        return bsms

    bsms = bsms.sort_values("timestamp", ignore_index=True)
    add_local_offsets(bsms)
    output_dir.mkdir(parents=True, exist_ok=True)
    bsms.to_csv(output_dir / "bsm_positions.csv", index=False, float_format="%.7f")
    plot_bsm_track(bsms, output_dir, title=title)

    for src, group in bsms.groupby("src"):
        logging.info(
            "%s from %s: %d BSMs (%d copies), track spans %.0f m E-W x %.0f m N-S",
            title, src, len(group), int(group["copies"].sum()),
            group["east_m"].max() - group["east_m"].min(),
            group["north_m"].max() - group["north_m"].min(),
        )
    return bsms


def run_bsm_gps_analysis(input_dir: Path, results_dir: Path) -> int:
    """Plot the positions of the BSMs sent by DUT 1 and received by DUT 2 for one run.

    Returns:
        0 on success or when the run lacks the DUT 1 or DUT 2 capture, 1 on error.
    """
    pcap_root = input_dir / "pcap"
    if not pcap_root.is_dir():
        return 0
    try:
        captures = get_pcaps(pcap_root)
        if SENDER_CAPTURE not in captures or CAPTURE not in captures:
            logging.info("Skipping BSM GPS analysis: need %s and %s captures", SENDER_CAPTURE, CAPTURE)
            return 0
        analyze_capture(captures[CAPTURE], results_dir / OUTPUT_SUBDIR,
                        title=PLOT_TITLE,
                        signatures=sent_signatures(captures[SENDER_CAPTURE]))
        return 0
    except Exception:
        logging.exception("BSM GPS analysis failed for run %s", input_dir.name)
        return 1


def main() -> int:
    """Plot the positions of the BSMs a sender capture sent, as received in another capture."""
    parser = argparse.ArgumentParser(
        description="Plot GPS positions of BSMs sent in one PCAP and received in another.")
    parser.add_argument("--sender-pcap", type=Path, required=True,
                        help="Capture taken on the sending device (e.g. DUT 1).")
    parser.add_argument("--receiver-pcap", type=Path, required=True,
                        help="Capture taken on the receiving device (e.g. DUT 2).")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for the CSV and plot.")
    parser.add_argument("--title", default=PLOT_TITLE, help="Plot title.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bsms = analyze_capture(args.receiver_pcap, args.output_dir, title=args.title,
                           signatures=sent_signatures(args.sender_pcap))
    return 0 if not bsms.empty else 1


if __name__ == "__main__":
    sys.exit(main())
