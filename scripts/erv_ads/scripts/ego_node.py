#!/usr/bin/env python3
"""Drive an ego in a shared CARLA scene (e.g. the VOICES cohort world) from
V2X received over UDP. Never changes world settings; it follows whatever
clock the scene owner runs (sync or async) via wait_for_tick.

Inputs it accepts on the UDP port, auto-detected per datagram:
  * UPER J2735 MessageFrame (raw or ASCII hex), optionally wrapped in a
    WSMP / 1609.2 / vendor header (the decoder scans for the frame start)
  * the JSON form produced by this repo (no ASN.1 needed)

Typical uses:
  # attach to an ego someone else spawned, ERV BSMs from erv_broadcaster.py
  python scripts/ego_node.py --role ego_av --dest 120.5,-48.2

  # spawn our own ego at spawn point 12, listen to a bench OBU forwarding
  # real RF (channel model off, wall clock for secMark ages)
  python scripts/ego_node.py --spawn 12 --set v2x.channel.enabled=false --set clock.kind=wall
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import carla  # noqa: E402

from erv_ego import build as B  # noqa: E402
from erv_ego import carla_compat as cc  # noqa: E402
from erv_ego.config import load_config, set_dotted  # noqa: E402
from erv_ego.ego.agent import ErvAwareAgent  # noqa: E402
from erv_ego.evidence import Evidence, Metrics  # noqa: E402
from erv_ego.geo import CarlaGeoRef  # noqa: E402
from erv_ego.v2x.transport import UdpReceiver, UdpSender  # noqa: E402

log = logging.getLogger("ego_node")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=None)
    p.add_argument("--role", default=None, help="attach to the vehicle with this role_name")
    p.add_argument("--spawn", type=int, default=None, help="spawn our own ego at this spawn-point index")
    p.add_argument("--dest", default=None, help="x,y[,z] in CARLA coordinates; default: far spawn point")
    p.add_argument("--duration", type=float, default=0.0, help="seconds of sim time (0 = until Ctrl-C)")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    for kv in args.set:
        k, v = kv.split("=", 1)
        set_dotted(cfg, k, v)

    client = carla.Client(cfg["carla"]["host"], int(cfg["carla"]["port"]))
    client.set_timeout(float(cfg["carla"]["timeout_s"]))
    world = client.get_world()
    cmap = world.get_map()
    role = args.role or cfg["ego"]["role_name"]

    owned = None
    ego = cc.find_actor_by_role(world, role)
    if ego is None:
        if args.spawn is None:
            sys.exit(f"no vehicle with role_name={role}; pass --spawn N to create one")
        bp = cc.find_blueprint(world.get_blueprint_library(), cfg["ego"]["blueprint"])
        bp.set_attribute("role_name", role)
        ego = world.spawn_actor(bp, cmap.get_spawn_points()[args.spawn])
        owned = ego
    log.info("ego actor %d (%s)", ego.id, ego.type_id)

    georef = CarlaGeoRef.from_carla_map(cmap)
    evidence = Evidence(cfg["evidence"]["out_dir"], time.strftime("%Y%m%d-%H%M%S-ego_node"))
    evidence.write_json("config.json", cfg)
    metrics = Metrics()
    u = cfg["v2x"]["udp"]
    rx = UdpReceiver(u["ego_rx_bind"], u["ego_rx_port"], multicast_group=u.get("multicast_group"))
    tx = UdpSender(u["ego_tx_host"], u["ego_tx_port"])
    clock = B.clock_from_cfg(cfg)
    codec = B.codec_from_cfg(cfg)
    receiver = B.receiver_from_cfg(cfg, [rx], codec, georef, world, evidence)
    tracker = B.tracker_from_cfg(cfg, clock, evidence)
    policy = B.policy_from_cfg(cfg, evidence)
    _, GRP = cc.import_agents()
    grp = GRP(cmap, 2.0)
    tx_tuple = (B.ego_generator_from_cfg(cfg, georef, clock), tx, codec) if cfg["ego"].get("broadcast_bsm") else None
    agent = ErvAwareAgent(ego, world, cmap, grp, receiver, tracker, policy, georef, cfg["ego"],
                          evidence, metrics, tx_tuple)

    if args.dest:
        xyz = [float(v) for v in args.dest.split(",")]
        dest = carla.Location(xyz[0], xyz[1], xyz[2] if len(xyz) > 2 else 0.0)
    else:
        here = ego.get_location()
        dest = max(cmap.get_spawn_points(), key=lambda sp: sp.location.distance(here)).location
    agent.set_destination(dest)
    log.info("listening on udp %s:%s, codec %s, destination %s", u["ego_rx_bind"], u["ego_rx_port"], codec.name, dest)

    t0 = None
    try:
        while True:
            snap = world.wait_for_tick()
            if t0 is None:
                t0 = snap.timestamp.elapsed_seconds
            t = snap.timestamp.elapsed_seconds - t0
            clock_s = snap.timestamp.elapsed_seconds
            if hasattr(clock, "set_sim_time"):
                clock.set_sim_time(clock_s)
            ego.apply_control(agent.run_step(t))
            if args.duration and t > args.duration:
                break
    except KeyboardInterrupt:
        pass
    finally:
        evidence.write_json("metrics.json", dict(metrics.summary(cfg["evidence"]["criteria"]),
                                                 receiver=receiver.stats, tracker_rejects=tracker.rejected))
        evidence.close()
        if owned is not None:
            owned.destroy()


if __name__ == "__main__":
    main()
