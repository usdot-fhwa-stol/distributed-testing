#!/usr/bin/env python3
import time
import socket
import argparse
from argparse import RawTextHelpFormatter

# ---------------------------------------------------------------------------
# Static configuration:
# ---------------------------------------------------------------------------

# DELAVE_MAP_CONFIG = [
#     {"intersection_id": 1, "payload": "00128119380730203000021d4d4bd7223e227a25104602dc0514f8196010a0000010000863e2274919a97af0c63e2273199a97af2c63e22713d9a97afd063e226ec09a97b14e63e226c939a97b2a463e226a9c9a97b4020b0480002012c011400000280010c7c44e923352f58f0c7c44e669352f5930c7c44e261352f5a8cc7c44dd4b352f5d88c7c44d8f3352f601cc7c44d455352f62f016070000402300844000004000298f889f9226a5ebfe98f889ff1a6a5ec0398f88a06726a5ec0918f88a0d766a5ec0e18f88a15da6a5ec1098f88a1eda6a5ec1598f88a29726a5ec188c01910000010000863e227e5c9a97ad6663e2280e79a97ad9a63e2283069a97ada463e2285409a97adc263e2287f39a97ade263e228a4e9a97adec0"},
#     {"intersection_id": 2, "payload": "0012810c38053020300004154d4bd8df3e22bbfa102802dc0514f8196010a0000018000863e22b7589a97b15c63e22b47d9a97b15c63e22b1d79a97b15263e22aee89a97b14863e22ab959a97b134e3e22a71a9a97b11e050502c120000804b0045000000a000431f115baa4d4bd77031f115a3ccd4bd76b31f1158edcd4bd76631f115772cd4bd75b31f1155c5cd4bd75671f11538bcd4bd7470282816070000402300644000004000218f88b065a6a5ec3198f88b0de66a5ec4398f88b19be6a5ec6018f88b23b26a5ec7498f88b2d3a6a5ec8918f88b3c1a6a5eca80c02110000010000663e22c1759a97b35a63e22c3de9a97b3c263e22c7319a97b45263e22cba59a97b51663e22cf649a97b59c"},
#     {"intersection_id": 3, "payload": "0012811038053020300006154d4bdd193e22ea28102802dc0514f8196008a0000010000863e22e7e19a97b6fc63e22e5c29a97b6b463e22e4369a97b68063e22e2109a97b62e63e22df649a97b5d263e22dc839a97b56a0b0580002012c021400000200010c7c45cf3d352f72d0c7c45cb41352f7240c7c45c7d9352f71d8c7c45c3a9352f7148c7c45be5f352f7078c7c45b89b352f6fac160d0000402300a44000004000218f88bb5f26a5edf598f88bc01a6a5ee0c98f88bca466a5ee2118f88bd19a6a5ee3398f88bdbfa6a5ee4a98f88be3a26a5ee5c8c03110000010000863e22ed5a9a97ba4063e22ef9b9a97ba9463e22f24e9a97bafa63e22f4029a97bb3863e22f6cf9a97bba063e22f8979a97bbde"},
#     {"intersection_id": 4, "payload": "001280f638023020300008094d4be6463e235d81000002dc0514f8196008a0000014000663e2359499a97c9a063e23574c9a97c96c63e23548c9a97c91063e2352739a97c8c663e234fac9a97c8560b0380002012c021400000300010c7c46b25d352f987cc7c46ae3b352f9800c7c46a9ef352f975cc7c46a4bf352f968cc7c469f25352f95c0c7c469b0d352f9518120900004300644000004000198f88d89366a5f2de18f88d93e66a5f2fc98f88d9bc26a5f31418f88da3ba6a5f32b18f88dad0e6a5f3428c02110000010000663e23621e9a97cdf663e2365009a97ce7e63e2367b39a97cef863e2369e69a97cf6063e236ba79a97cfa80"},
#     {"intersection_id": 5, "payload": "001280ed3803302030000a0c4d4bec343e23b20202dc0514f8196008a00000140006e3e23ada29a97d674050518f88eb23e6a5f59298f88eab8a6a5f58098f88ea37a6a5f56e98f88e98ae6a5f55482c0e0000804b0085000000c000271f11d6c74d4bec6502828c7c4756c3352fb0dcc7c474f53352fafa4c7c474925352fae98160900004023006440000040001b8f88edae66a5f5c10141463e23b89c9a97d74c63e23ba859a97d79463e23bc0a9a97d7d263e23bdfa9a97d8103008440000040001b8f88eda5e6a5f6638141463e23b8379a97d9cc63e23ba279a97da1463e23bb9f9a97da5263e23bd9c9a97da860"},
#     {"intersection_id": 6, "payload": "001281733806302030000c194d4bef4a3e2404b20ff602dc0514f829601920000008000663e23fc849a97e09663e23f9f79a97e12e63e23f6949a97e20263e23f37b9a97e24063e23ef889a97e2020b0640002012c021400000200010c7c47fdfb352fb7b8c7c47f99d352fb9e4c7c47f2c7352fbd14c7c47eb77352fc018c7c47e5bf352fc190c7c47dfc1352fc278160b0000402580228000005000218f88ff9a66a5f62b18f88fed826a5f6a018f88fe22a6a5f71098f88fd5aa6a5f76598f88fca3a6a5f79418f88fbf4e6a5f7a002c1200008046010c8000008000431f1206414d4bea3d31f120790cd4be97931f12093dcd4be8b031f120a8d4d4be82031f120c1d4d4be7ad31f120e20cd4be75318053200000200014c7c481a11352fad50c7c481e79352fab20c7c48234b352fa8e0c7c4828bd352fa69cc7c482ded352fa4ecc7c48347d352fa2f0c7c483883352fa284601908000008000131f1202a1cd4bf6a331f1201f34d4bfd7f31f12014d4d4c031e0"},
#     {"intersection_id": 7, "payload": "001281243803302030000e0c4d4be9fd3e243baa02dc0514f8196008a0000010000a63e24398a9a97d17463e2436f99a97d0f663e24345b9a97d09a63e24319b9a97d03263e242e699a97cfac63e242c009a97cf4e63e242a249a97cf100b0380002012c021400000200014c7c4872ab352fa810c7c486dcb352fa754c7c486865352fa698c7c48630d352fa5ccc7c485c4b352fa4fcc7c485795352fa458c7c48542d352fa3dc16090000402300644000004000218f890f9066a5f49f98f89102266a5f4b118f8910f3e6a5f4d038f89119d26a5f4e48141463e2448e49a97d3f063e244be19a97d476300844000004000218f890f8826a5f56918f89100fe6a5f57d98f8910ada6a5f58f38f89115da6a5f5a60141463e2448439a97d70063e244b909a97d77c0"},
#     {"intersection_id": 8, "payload": "0012811538063020300010194d4bbf403e248c7b0ff602dc0514f8196008a0000014000a63e2488659a977bf063e2486199a977b7063e2483d19a977af463e24812c9a977ad663e247e9b9a977b3c63e247c179a977c2a63e247a199a977d740b0380002012c021400000300014c7c491035352efd04c7c490c8f352efc34c7c490745352efb14c7c4901fb352efb3cc7c48fd69352efc00c7c48f911352efd5cc7c48f4e3352effe816090000402300644000004000198f89244f26a5df9398f8924b866a5dfa5b8f89256d66a5dfc2013ec63e24997b9a977fb663e249cf69a978066300844000004000198f89243466a5e04298f8924ae66a5e05298f892555e6a5e069b8f892654a6a5e090013ec63e249cba9a9782e60"},
# ]

MAP_CONFIG = [
    {},
]


def build_active_message(hex_payload, msg_type="MAP", psid="0x8002"):
    return (
        "Version=0.7\n"
        f"Type={msg_type}\n"
        f"PSID={psid}\n"
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


def main():
    parser = argparse.ArgumentParser(
        formatter_class=RawTextHelpFormatter,
        description=(
            "Broadcast static J2735 MAP payloads as AMF over UDP.\n"
            "Each intersection is staggered evenly across the period.\n"
        ),
    )

    parser.add_argument(
        "--period",
        type=float,
        default=1.0,
        help="Total cycle period in seconds (default: 1.0).",
    )

    parser.add_argument(
        "--ip",
        type=str,
        default="127.0.0.1",
        help="Destination IP for AMF UDP (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=56702,
        help="Destination UDP port for AMF (default: 56702)",
    )

    parser.add_argument(
        "--type",
        type=str,
        default="MAP",
        help="AMF Type field (default: MAP)",
    )
    parser.add_argument(
        "--psid",
        type=str,
        default="0x8002",
        help="AMF PSID field (default: 0x8002 for MAP)",
    )

    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress per-send log lines",
    )

    args = parser.parse_args()

    if not MAP_CONFIG:
        print("MAP_CONFIG is empty – no intersections to send.")
        return

    num_intersections = len(MAP_CONFIG)
    period = args.period
    spacing = period / num_intersections

    sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = (args.ip, args.port)

    print("Press Ctrl+C to stop\n")
    print(
        f"Configured intersections: {[c['intersection_id'] for c in MAP_CONFIG]}\n"
        f"Cycle period: {period:.3f}s | Spacing: {spacing:.3f}s\n"
        f"UDP target: {args.ip}:{args.port}\n"
    )

    try:
        while True:
            cycle_start = time.time()

            for idx, cfg in enumerate(MAP_CONFIG):
                send_start = time.time()

                amf_text = build_active_message(
                    hex_payload=cfg["payload"],
                    msg_type=args.type,
                    psid=args.psid,
                )
                sk.sendto(amf_text.encode("ascii"), target)

                if not args.quiet:
                    print(
                        f"[MAP-AMF] Sent intersection {cfg['intersection_id']} "
                        f"to {args.ip}:{args.port} | payload len={len(cfg['payload'])}"
                    )

                elapsed = time.time() - send_start
                wait = spacing - elapsed
                if idx != num_intersections - 1 and wait > 0:
                    time.sleep(wait)

            # keep cycle aligned to the period
            total_elapsed = time.time() - cycle_start
            remaining = period - total_elapsed
            if remaining > 0:
                time.sleep(remaining)

    except KeyboardInterrupt:
        print("\nStopped MAP AMF broadcaster.")


if __name__ == "__main__":
    main()
