#!/usr/bin/env python3
import time
import json
import socket
from datetime import datetime
import argparse
from argparse import RawTextHelpFormatter

import j2735_202409

MessageFrame = j2735_202409.MessageFrame.MessageFrame


def compute_moy_and_time_mark():
    """
    Compute:
      - Minute of year (moy)
      - TimeMark in 0.1s units from the top of the current UTC hour (0..35999)
    """
    now = datetime.utcnow()

    # Minute of year (unchanged)
    moy = ((now.timetuple().tm_yday - 1) * 24 * 60) + now.hour * 60 + now.minute

    # Seconds since top of the hour
    seconds_since_hour = now.minute * 60 + now.second
    ms_since_hour = seconds_since_hour * 1000 + now.microsecond // 1000

    # TimeMark: 0.1 s units from top of the current hour, should be 0..35999
    time_mark = ms_since_hour // 100
    if time_mark > 35999:
        # Should not normally happen, but be safe
        time_mark = 35999

    return moy, int(time_mark)


def get_phase_states(cycle_pos, cfg):
    """
    Given a position within the cycle (seconds) and timing config,
    return (main_state, main_remaining, side_state, side_remaining).
    """
    gm, ym, rm = cfg["green_main"], cfg["yellow_main"], cfg["red_main"]
    gs, ys, rs = cfg["green_side"], cfg["yellow_side"], cfg["red_side"]

    main_len = gm + ym + rm
    side_len = gs + ys + rs
    cycle_len = main_len + side_len

    pos = cycle_pos % cycle_len

    if pos < gm:
        main_state = "protected-Movement-Allowed"
        main_remaining = gm - pos
        side_state = "stop-And-Remain"
        side_remaining = main_len - pos

    elif pos < gm + ym:
        main_state = "protected-clearance"
        main_remaining = gm + ym - pos
        side_state = "stop-And-Remain"
        side_remaining = main_len - pos

    elif pos < main_len:
        main_state = "stop-And-Remain"
        side_state = "stop-And-Remain"
        main_remaining = main_len - pos
        side_remaining = main_len - pos

    else:
        side_pos = pos - main_len

        if side_pos < gs:
            side_state = "protected-Movement-Allowed"
            side_remaining = gs - side_pos
            main_state = "stop-And-Remain"
            main_remaining = cycle_len - pos

        elif side_pos < gs + ys:
            side_state = "protected-clearance"
            side_remaining = gs + ys - side_pos
            main_state = "stop-And-Remain"
            main_remaining = cycle_len - pos

        else:
            side_state = "stop-And-Remain"
            main_state = "stop-And-Remain"
            main_remaining = cycle_len - pos
            side_remaining = cycle_len - pos

    return main_state, main_remaining, side_state, side_remaining


def build_spat_for_intersection(
    intersection_id,
    moy,
    time_mark,
    main_state,
    main_rem,
    side_state,
    side_rem,
):
    """
    Build a SPaT JER dict for a single intersection, given existing timing/state info.
    """

    def make_state(signal_group, event_state, remaining_seconds):
        # Convert remaining time to 0.1 s units, keep as INTEGER
        delta_mark = int(round(remaining_seconds * 10.0))

        # TimeMark is relative to top of hour; wrap at 36000 to indicate "next hour"
        end_mark = time_mark + delta_mark
        if end_mark >= 36000:
            end_mark -= 36000  # wrap into 0..35999 range (next hour)

        # Enforce bounds per spec (0..36111, but we stay in 0..35999 normal range)
        if end_mark < 0:
            end_mark = 0
        elif end_mark > 35999:
            end_mark = 35999

        return {
            "signalGroup": signal_group,
            "state-time-speed": [
                {
                    "eventState": event_state,
                    "timing": {
                        # Both are INTEGER TimeMark values
                        "minEndTime": int(end_mark),
                        "maxEndTime": int(end_mark),
                    },
                }
            ],
        }

    states = []
    # Main street: groups 2 and 6
    for sg in (2, 6):
        states.append(make_state(sg, main_state, main_rem))
    # Side street: groups 4 and 8
    for sg in (4, 8):
        states.append(make_state(sg, side_state, side_rem))

    spat = {
        "messageId": 19,
        "value": {
            "timeStamp": int(time_mark),  # DSecond-ish; still 0.1s from hour, but valid INTEGER
            "intersections": [
                {
                    "id": {"id": int(intersection_id)},
                    "revision": 0,
                    "status": "0000",
                    "moy": int(moy),
                    "timeStamp": int(time_mark),
                    "states": states,
                }
            ],
        },
    }

    return spat


def encode_spat_to_uper_hex(spat_dict):
    jer_str = json.dumps(spat_dict, separators=(",", ":"))
    msg = MessageFrame
    msg.from_jer(jer_str)
    uper_bytes = msg.to_uper()
    return uper_bytes.hex()


def build_active_message(hex_payload):
    """
    Build Active Message Format (AMF) text with the given hex payload.
    """
    return (
        "Version=0.7\n"
        "Type=SPAT\n"
        "PSID=0x8003\n"
        "Priority=7\n"
        "TxMode=CONT\n"
        "TxChannel=183\n"
        "TxInterval=0\n"
        "DeliveryStart=\n"
        "DeliveryStop=\n"
        "Signature=True\n"
        "Encryption=False\n"
        f"Payload={hex_payload}\n"
    )


def print_frame_log(intersection_id, debug_info, hex_str):
    print(
        f"[SPaT] Int {intersection_id} | "
        f"{debug_info['timestamp']} | "
        f"Main: {debug_info['main_state']} ({debug_info['main_remaining']}s) | "
        f"Side: {debug_info['side_state']} ({debug_info['side_remaining']}s)\n"
        f"   HEX: {hex_str}\n"
    )


def main():
    parser = argparse.ArgumentParser(
        formatter_class=RawTextHelpFormatter, description=(
            "Generate SPaT (2/4/6/8 groups) for one or more intersections and send "
            "as Active Message Format over UDP.\n\n"
            "Run outside the container (requires Python 3.8+ for j2735):\n"
            "  1) Install deps from this folder: ./install_dependencies.sh\n"
            "  2) Run with your options: ./spat_generator.py [args]\n\n"
            "Adapter Configuration:\n"
            "  - To publish encoded J2735 hex over TENA V2X Messages: \n"
            "    - Set VUG_DOCKER_START_V2X_ADAPTER=true in your site config \n"
            "    - Match IP/port with adapter: VUG_V2X_ADAPTER_RECEIVE_ADDRESS should equal --ip and \n"
            "      VUG_V2X_ADAPTER_RECEIVE_PORT should equal --port - you can pass them directly: \n"
            "        --ip $VUG_V2X_ADAPTER_RECEIVE_ADDRESS --port $VUG_V2X_ADAPTER_RECEIVE_PORT\n\n"
            "  - To convert the TENA V2X Messages into Traffic Signal Controller data for visualization: \n"
            "    - Set VUG_DOCKER_START_ENTITY_GENERATOR=true \n"
            "    - Ensure every intersection ID you send exists in the scenario XML under \n"
            "      intersectionSignalControllers and phaseSignalMappings\n\n"
            "Examples:\n"
            "  - Single intersection to a local receiver:\n"
            "      ./spat_generator.py --intersection-ids 100 --ip 127.0.0.1 --port 1516\n\n"
            "  - Multiple intersections with custom timings and slower rate:\n"
            "      ./spat_generator.py --intersection-ids 100 101 --hz 5 \\\n"
            "        --green-main 25 --yellow-main 4 --red-main 3 \\\n"
            "        --green-side 15 --yellow-side 4 --red-side 3\n\n"
            "Press Ctrl+C to stop the generator."
        )
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print raw SPaT JER payloads before encoding",
    )

    # Multiple intersection IDs
    parser.add_argument(
        "--intersection-ids",
        type=int,
        nargs="+",
        default=[100],
        help="Space-separated list of intersection IDs to emit (default: 100)",
    )

    parser.add_argument(
        "--hz",
        type=float,
        default=10.0,
        help="Output rate in Hz for all intersections (default: 10.0)",
    )

    # UDP target
    parser.add_argument(
        "--ip",
        type=str,
        default="127.0.0.1",
        help="Destination IP for Active Message Format UDP (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=56700,
        help="Destination UDP port for Active Message Format (default: 56700)",
    )

    # Main street timings
    parser.add_argument(
        "--green-main",
        type=float,
        default=20.0,
        help="Main street green time in seconds (default: 20.0)",
    )
    parser.add_argument(
        "--yellow-main",
        type=float,
        default=4.0,
        help="Main street yellow time in seconds (default: 4.0)",
    )
    parser.add_argument(
        "--red-main",
        type=float,
        default=2.0,
        help="Main street red/all-red dwell in seconds (default: 2.0)",
    )

    # Side street timings
    parser.add_argument(
        "--green-side",
        type=float,
        default=15.0,
        help="Side street green time in seconds (default: 15.0)",
    )
    parser.add_argument(
        "--yellow-side",
        type=float,
        default=4.0,
        help="Side street yellow time in seconds (default: 4.0)",
    )
    parser.add_argument(
        "--red-side",
        type=float,
        default=2.0,
        help="Side street red/all-red dwell in seconds (default: 2.0)",
    )

    args = parser.parse_args()

    cfg = {
        "green_main": args.green_main,
        "yellow_main": args.yellow_main,
        "red_main": args.red_main,
        "green_side": args.green_side,
        "yellow_side": args.yellow_side,
        "red_side": args.red_side,
    }

    interval = 1.0 / args.hz
    sim_start_time = time.time()

    # UDP socket
    sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = (args.ip, args.port)

    print("Press Ctrl+C to stop\n")
    print(
        f"Intersections: {args.intersection_ids} | "
        f"Main G/Y/R = {cfg['green_main']}/{cfg['yellow_main']}/{cfg['red_main']} s | "
        f"Side G/Y/R = {cfg['green_side']}/{cfg['yellow_side']}/{cfg['red_side']} s | "
        f"Rate: {args.hz} Hz | "
        f"UDP target: {args.ip}:{args.port}\n"
    )

    try:
        while True:
            loop_start = time.time()

            # Compute controller state ONCE per tick
            now = time.time()
            cycle_pos = now - sim_start_time
            main_state, main_rem, side_state, side_rem = get_phase_states(cycle_pos, cfg)
            moy, time_mark = compute_moy_and_time_mark()

            debug_info = {
                "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                "main_state": main_state,
                "main_remaining": round(main_rem, 2),
                "side_state": side_state,
                "side_remaining": round(side_rem, 2),
            }

            # Build, encode, log, and send for each intersection
            for intersection_id in args.intersection_ids:
                spat_jer = build_spat_for_intersection(
                    intersection_id,
                    moy,
                    time_mark,
                    main_state,
                    main_rem,
                    side_state,
                    side_rem,
                )
                if args.verbose:
                    print(f"spat_jer: {spat_jer}")
                hex_str = encode_spat_to_uper_hex(spat_jer)

                # Human-readable log
                print_frame_log(intersection_id, debug_info, hex_str)

                # Build AMF text and send via UDP
                amf_text = build_active_message(hex_str)
                sk.sendto(amf_text.encode("ascii"), target)

            # Rate control
            sleep_time = interval - (time.time() - loop_start)
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\nStopped SPaT generator.")


if __name__ == "__main__":
    main()
