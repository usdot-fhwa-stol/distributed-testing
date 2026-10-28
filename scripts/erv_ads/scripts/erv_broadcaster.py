#!/usr/bin/env python3
"""Give any emergency vehicle in a CARLA scene a J2735 radio.

Attaches to an existing actor (by role_name or id) - for example the
apparatus another cohort member spawned - reads its live state and light
bar every 100 ms of sim time and sends BSMs over UDP. Optionally spawns and
drives the ERV itself (--spawn / --drive-to).

Lightbar state comes from the actor (CARLA VehicleLightState.Special1);
siren is a flag (--siren / --no-siren) because CARLA has no audio model.

    python scripts/erv_broadcaster.py --role erv_1
    python scripts/erv_broadcaster.py --spawn 30 --kind ambulance --drive-to 85,-20 --profile full
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import carla  # noqa: E402

from erv_ego import build as B  # noqa: E402
from erv_ego import carla_compat as cc  # noqa: E402
from erv_ego.config import load_config, set_dotted  # noqa: E402
from erv_ego.geo import CarlaGeoRef  # noqa: E402
from erv_ego.v2x.transport import UdpSender  # noqa: E402

log = logging.getLogger("erv_broadcaster")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=None)
    p.add_argument("--role", default=None)
    p.add_argument("--actor-id", type=int, default=None)
    p.add_argument("--spawn", type=int, default=None, help="spawn an ERV at this spawn-point index")
    p.add_argument("--kind", default=None, help="firetruck | ambulance | police | responder")
    p.add_argument("--profile", default=None, help="stol_sample | full")
    p.add_argument("--drive-to", default=None, help="x,y[,z]: drive Code 3 to this location")
    p.add_argument("--siren", dest="siren", action="store_true", default=True)
    p.add_argument("--no-siren", dest="siren", action="store_false")
    p.add_argument("--force-lightbar", action="store_true", help="turn the actor's lightbar on")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    for kv in args.set:
        k, v = kv.split("=", 1)
        set_dotted(cfg, k, v)
    if args.kind:
        cfg["erv"]["kind"] = args.kind
    if args.profile:
        cfg["erv"]["bsm_profile"] = args.profile

    client = carla.Client(cfg["carla"]["host"], int(cfg["carla"]["port"]))
    client.set_timeout(float(cfg["carla"]["timeout_s"]))
    world = client.get_world()
    cmap = world.get_map()

    owned = None
    if args.actor_id is not None:
        erv = world.get_actor(args.actor_id)
    else:
        erv = cc.find_actor_by_role(world, args.role or cfg["erv"]["role_name"])
    if erv is None:
        if args.spawn is None:
            sys.exit("ERV actor not found; pass --role/--actor-id, or --spawn N")
        lib = world.get_blueprint_library()
        bp = cc.find_blueprint(lib, cc.ERV_BLUEPRINT_PATTERNS.get(cfg["erv"]["kind"], ["*firetruck*"]))
        bp.set_attribute("role_name", args.role or cfg["erv"]["role_name"])
        erv = world.spawn_actor(bp, cmap.get_spawn_points()[args.spawn])
        owned = erv
    log.info("ERV actor %d (%s)", erv.id, erv.type_id)

    georef = CarlaGeoRef.from_carla_map(cmap)
    clock = B.clock_from_cfg(cfg)
    codec = B.codec_from_cfg(cfg)
    gen = B.erv_generator_from_cfg(cfg, georef, clock)
    u = cfg["v2x"]["udp"]
    tx = UdpSender(u["erv_tx_host"], u["erv_tx_port"], broadcast=u["erv_tx_host"].endswith(".255"))
    period = 1.0 / float(cfg["erv"]["bsm_rate_hz"])
    wheel = cc.max_road_wheel_deg(erv)

    driver = None
    if args.drive_to:
        from erv_ego.erv.driver import ErvDriver
        _, GRP = cc.import_agents()
        driver = ErvDriver(erv, world, cmap, GRP(cmap, 2.0), dict(cfg["erv"], code3=True))
        xyz = [float(v) for v in args.drive_to.split(",")]
        driver.set_destination(carla.Location(xyz[0], xyz[1], xyz[2] if len(xyz) > 2 else 0.0))
    elif args.force_lightbar:
        cc.set_lights(erv, {"position", "low_beam", "lightbar"})

    log.info("sending %s BSMs (%s profile) to %s:%s at %.0f Hz", codec.name, cfg["erv"]["bsm_profile"],
             u["erv_tx_host"], u["erv_tx_port"], 1 / period)
    last = -1e9
    n = 0
    t0 = None
    try:
        while True:
            snap = world.wait_for_tick()
            if t0 is None:
                t0 = snap.timestamp.elapsed_seconds
            t = snap.timestamp.elapsed_seconds - t0
            if hasattr(clock, "set_sim_time"):
                clock.set_sim_time(snap.timestamp.elapsed_seconds)
            if driver is not None:
                erv.apply_control(driver.run_step())
            if t - last >= period - 1e-6:
                state = cc.vehicle_state(erv, siren=args.siren and "lightbar" in cc.light_names(erv.get_light_state()),
                                         max_wheel_deg=wheel)
                tx.send(codec.encode_bsm(gen.build(state, t)))
                last = t
                n += 1
                if n % 50 == 0:
                    log.info("%d BSMs sent; lights=%s speed=%.1f m/s", n, sorted(state.lights), state.speed_mps)
    except KeyboardInterrupt:
        pass
    finally:
        if owned is not None:
            owned.destroy()


if __name__ == "__main__":
    main()
