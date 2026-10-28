#!/usr/bin/env python3
"""Relay the BSMs the DT V2X adapter emits (everything the TENA execution carries) to the carla-erv-ego ego.

    TENA execution -> TENAV2XMessageAdapter -> UDP <WSL IP>:5398 (UPER J2735, raw or AMF) -> THIS -> UDP <Windows>:47347 (JSON)

Runs in WSL (host python3.10 has j2735_202409 + pycrate + carla). Two things are changed on the way, nothing else:
  * encoding: UPER -> the JSON form carla-erv-ego reads (the repo has no licensed J2735 ASN.1 for UPER)
  * position frame: the CARLA adapter writes lat/lon as metres from the scenario MapOrigin (0,0) on a flat earth
    (lat = north/110574, lon = east/111320); the ego converts lat/lon with the CARLA map's own georeference. The relay
    turns the adapter's lat/lon back into CARLA x/y and asks the CARLA map for the matching lat/lon.

    python3 tena_bsm_relay.py [--to 172.29.0.1:47347] [--bind 172.29.6.73:5398]
"""
import argparse
import json
import socket
import sys
import time

import carla
import j2735_202409

MF = j2735_202409.MessageFrame.MessageFrame


def conv(v, key=None):
    """pycrate value -> the JSON value structure carla-erv-ego's JsonCodec expects."""
    if isinstance(v, dict):
        return {k: conv(x, k) for k, x in v.items()}
    if isinstance(v, list):
        return [conv(x, key) for x in v]
    if isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], str):
        return conv(v[1], key) if key in ("partII-Value", "value") else {v[0]: conv(v[1])}     # open type / CHOICE
    if isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], int) and isinstance(v[1], int):
        n = (v[1] + 7) // 8                                                                     # BIT STRING, left aligned
        return {"value": (v[0] << (n * 8 - v[1])).to_bytes(n, "big").hex(), "length": v[1]}
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).hex()
    return v


def payload_of(data):
    if data[:8] == b"Version=":
        for line in data.decode("ascii", "replace").splitlines():
            if line.startswith("Payload="):
                return bytes.fromhex(line[8:].strip())
        return b""
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bind", default="172.29.6.73:5398")
    ap.add_argument("--to", default="172.29.0.1:47347")
    ap.add_argument("--carla", default="172.29.0.1:2000")
    a = ap.parse_args()
    ch, cp = a.carla.split(":")
    cmap = carla.Client(ch, int(cp))
    cmap.set_timeout(20)
    cmap = cmap.get_world().get_map()
    bh, bp = a.bind.split(":")
    th, tp = a.to.split(":")
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    rx.bind((bh, int(bp)))
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"relaying TENA V2X {a.bind} -> {a.to} (JSON), map {cmap.name}", flush=True)
    n, bad, ids, last = 0, 0, {}, time.time()
    while True:
        data, _ = rx.recvfrom(65535)
        try:
            MF.from_uper(payload_of(data))
            v = MF.get_val()
            if v["messageId"] != 20:
                continue
            bsm = conv(v["value"][1])
            c = bsm["coreData"]
            east, north = c["long"] * 1e-7 * 111320.0, c["lat"] * 1e-7 * 110574.0
            geo = cmap.transform_to_geolocation(carla.Location(east, -north, c["elev"] / 10.0))
            c["lat"], c["long"] = int(round(geo.latitude * 1e7)), int(round(geo.longitude * 1e7))
            tx.sendto(json.dumps({"messageId": 20, "value": bsm}, separators=(",", ":")).encode(), (th, int(tp)))
            n += 1
            ids[c["id"]] = ids.get(c["id"], 0) + 1
        except Exception as e:                                  # one bad datagram must not stop the relay
            bad += 1
            if bad <= 3:
                print("skip:", repr(e)[:200], flush=True)
        if time.time() - last > 5:
            last = time.time()
            print(f"[{time.strftime('%H:%M:%S')}] relayed {n} BSMs {ids} bad {bad}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
