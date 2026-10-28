"""Event 3 Move Over inside the running DT stack: the carla-erv-ego ego as AMG-M-1, hearing the ERV over TENA.

What talks to what:
  * ERV = plain CARLA ambulance AMG-ERV-1 (spawn_erv_actor.py). The DT CARLA adapter publishes it to the TENA execution
    and generates its BSMs (emergency Part II). Nothing here sends anything to the ego directly.
  * Those BSMs leave TENA through the DT V2X adapter; tena_bsm_relay.py (WSL) hands them to this script on UDP 47347.
  * Ego = a CARLA Lincoln named AMG-M-1 (listed in the scenario), so the CARLA adapter publishes it to TENA as well.
  * SUMO: sumo-dt mirrors every CARLA vehicle into SUMO; SUMO's own cars come into CARLA through the JSON Publisher/TENA.

The world is NOT put in synchronous mode (the DT adapters own it): this follows the server's ticks in real time.

    python dt_event3_ego.py [--back 150] [--record] [--keep]
"""
import argparse
import logging
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# inside the repo (carla-erv-ego/dt/) or next to it (tools/erv-ego/ beside carla-erv-ego/)
REPO = next((p for p in (os.path.join(HERE, ".."), os.path.join(HERE, "..", "..", "carla-erv-ego"))
             if os.path.isdir(os.path.join(p, "erv_ego"))), os.path.join(HERE, ".."))
REPO = os.path.abspath(REPO)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
os.environ.setdefault("CARLA_ROOT", r"C:\carla-0.10.0")

import carla  # noqa: E402

from erv_ego import build as B  # noqa: E402
from erv_ego import carla_compat as cc  # noqa: E402
from erv_ego import scenarios  # noqa: E402
from erv_ego.config import load_config, set_dotted  # noqa: E402
from erv_ego.ego.agent import ErvAwareAgent  # noqa: E402
from erv_ego.ego.policy import Mode  # noqa: E402
from erv_ego.evidence import Evidence, Metrics  # noqa: E402
from erv_ego.geo import CarlaGeoRef  # noqa: E402
from erv_ego.v2x.transport import UdpReceiver  # noqa: E402
from run_scenario import Recorder, follow_cam  # noqa: E402

log = logging.getLogger("dt_event3_ego")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--role", default="AMG-M-1")
    ap.add_argument("--erv-role", default="AMG-ERV-1")
    ap.add_argument("--back", type=float, default=150.0, help="start this far before the ERV")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--cam", default="exposure_mode=manual,fstop=2.0,shutter_speed=500,iso=100",
                    help="camera attributes for --record. The generated OpenDRIVE world has no sky or ground, so "
                         "auto-exposure drifts to black: a fixed exposure is the default")
    ap.add_argument("--keep", action="store_true", help="leave the ego in CARLA at the end")
    ap.add_argument("--no-erv", action="store_true",
                    help="control run: no ERV in CARLA; same start and destination, taken from --erv-pose")
    ap.add_argument("--erv-pose", default="66.959,-127.476,7.17,-70.93", help="where the ERV stands / would stand")
    ap.add_argument("--tag", default="dt_event3", help="suffix of the run folder name")
    ap.add_argument("--spawn-only", action="store_true",
                    help="put the ego at its start, hand brake on, and exit (so the CARLA adapter publishes it before the run)")
    ap.add_argument("--attach", action="store_true",
                    help="drive the vehicle that already has --role instead of spawning one; it is left in CARLA at the end. "
                         "The CARLA adapter does not publish a vehicle again after a respawn, so use this at an event")
    ap.add_argument("--own-bsm-ids", default="11111111,00000000",
                    help="BSM ids the CARLA adapter gives our own vehicle (AMG-M-1, VW-M-1): ignored by the tracker")
    ap.add_argument("--max-s", type=float, default=150.0)
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cfg = load_config(None)
    for k, v in (("clock.kind", "wall"), ("v2x.channel.enabled", "false"), ("v2x.codec", "json"),
                 ("tracker.max_age_ms", "3000"), ("tracker.stale_s", "2.0"), ("tracker.drop_s", "5.0"),
                 ("ego.broadcast_bsm", "false"), ("ego.role_name", a.role)):
        set_dotted(cfg, k, v)
    for kv in a.set:
        k, v = kv.split("=", 1)
        set_dotted(cfg, k, v)

    client = carla.Client("127.0.0.1", 2000)
    client.set_timeout(30)
    world = client.get_world()
    cmap = world.get_map()
    erv = cc.find_actor_by_role(world, a.erv_role)
    ex, ey, ez, _ = [float(v) for v in a.erv_pose.split(",")]
    if a.no_erv:
        if erv is not None:
            sys.exit(f"{a.erv_role} is in CARLA: remove it first (spawn_erv_actor.py --remove) for the control run")
    elif erv is None:
        sys.exit(f"no {a.erv_role} in CARLA: run spawn_erv_actor.py first")
    existing = [v for v in world.get_actors().filter("vehicle.*") if v.attributes.get("role_name") == a.role]
    if a.attach:
        if not existing:
            sys.exit(f"--attach: no vehicle named {a.role} in CARLA (run with --spawn-only first)")
    else:
        for old in existing:
            old.destroy()

    erv_wp = cmap.get_waypoint(erv.get_location() if erv is not None else carla.Location(ex, ey, ez))
    start, got = cc.walk_straight(erv_wp, a.back, forward=False)
    dest = scenarios._dest(erv_wp, 170.0)
    tf = start.transform
    tf.location.z += 0.5
    bp = cc.find_blueprint(world.get_blueprint_library(), cfg["ego"]["blueprint"])
    bp.set_attribute("role_name", a.role)
    if a.attach:
        ego = existing[0]
        a.keep = True
        got = ego.get_location().distance(erv_wp.transform.location)
    else:
        ego = world.spawn_actor(bp, tf)
    if a.spawn_only:
        ego.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))
        log.info("spawned %s (actor %d) %.0f m before the ERV position at %.1f, %.1f and left it parked", a.role, ego.id,
                 got, tf.location.x, tf.location.y)
        return
    log.info("ego %s actor %d %.0f m before %s (road %d lane %d); destination %.1f, %.1f", a.role, ego.id, got,
             a.erv_role, start.road_id, start.lane_id, dest.x, dest.y)

    evidence = Evidence(os.path.join(REPO, cfg["evidence"]["out_dir"]), time.strftime("%Y%m%d-%H%M%S-") + a.tag)
    evidence.write_json("config.json", cfg)
    metrics = Metrics()
    georef = CarlaGeoRef.from_carla_map(cmap)
    u = cfg["v2x"]["udp"]
    rx = UdpReceiver(u["ego_rx_bind"], u["ego_rx_port"])
    clock = B.clock_from_cfg(cfg)
    codec = B.codec_from_cfg(cfg)
    receiver = B.receiver_from_cfg(cfg, [rx], codec, georef, world, evidence)
    tracker = B.tracker_from_cfg(cfg, clock, evidence)
    for own in a.own_bsm_ids.split(","):                    # our own BSM, generated by the CARLA adapter
        tracker.own_ids.add(bytes.fromhex(own.strip()))
    policy = B.policy_from_cfg(cfg, evidence)
    _, GRP = cc.import_agents()
    grp = GRP(cmap, 2.0)

    col = world.spawn_actor(world.get_blueprint_library().find("sensor.other.collision"), carla.Transform(), attach_to=ego)
    now = {"t": 0.0}

    def on_collision(ev):
        rec = {"other": ev.other_actor.type_id, "other_role": ev.other_actor.attributes.get("role_name"),
               "impulse": math.sqrt(ev.normal_impulse.x ** 2 + ev.normal_impulse.y ** 2 + ev.normal_impulse.z ** 2)}
        if not metrics.collisions or now["t"] - metrics.collisions[-1]["t"] > 1.0:
            metrics.collisions.append(dict(rec, t=now["t"]))
            evidence.event("collision", now["t"], **rec)

    col.listen(on_collision)
    recorder = None
    if a.record:
        attrs = dict(kv.split("=", 1) for kv in a.cam.split(",") if "=" in kv)
        recorder = Recorder(world, ego, evidence.dir, attrs=attrs)

    world.wait_for_tick()
    agent = ErvAwareAgent(ego, world, cmap, grp, receiver, tracker, policy, georef, cfg["ego"], evidence, metrics, None)
    agent.set_destination(dest)
    spectator = world.get_spectator()
    t0, resume_t, end, last_log = None, None, "max_duration", -10.0
    try:
        while True:
            snap = world.wait_for_tick()
            if t0 is None:
                t0 = snap.timestamp.elapsed_seconds
            t = snap.timestamp.elapsed_seconds - t0
            now["t"] = t
            ego.apply_control(agent.run_step(t))
            follow_cam(spectator, ego)
            act = agent.last_action
            mode = act.mode if act else None
            v = ego.get_velocity()
            near = min(agent.last_threats, key=lambda th: th.range_m) if agent.last_threats else None
            if recorder is not None:
                others = sorted(x.attributes.get("role_name", "?") for x in world.get_actors().filter("vehicle.*")
                                if x.id != ego.id)
                recorder.caption = "t=%5.1fs %-10s %3.0f km/h" % (t, mode.value if mode else "", 3.6 * math.hypot(v.x, v.y)) \
                    + ("  ERV via TENA: %s %.0f m" % (near.relation.value, near.range_m) if near else "  no ERV heard") \
                    + "  | in CARLA: " + ", ".join(others)
            if t - last_log >= 5.0:
                last_log = t
                log.info("t=%5.1f %-12s %4.1f m/s  rx %s  %s", t, mode.value if mode else "", math.hypot(v.x, v.y),
                         receiver.stats.get("delivered"),
                         "ERV %s %.0f m" % (near.relation.value, near.range_m) if near else "no ERV track")
            if mode == Mode.RESUME and resume_t is None:
                resume_t = t
            if resume_t is not None and t - resume_t > 8.0:
                end = "resumed_after_erv"
                break
            # same stopping point for every run, so runs with and without the ERV can be compared
            el = ego.get_location()
            fw = erv_wp.transform.get_forward_vector()
            if (el.x - ex) * fw.x + (el.y - ey) * fw.y > 95.0:
                end = "passed_the_scene"
                break
            if ego.get_location().distance(dest) < 5.0:
                end = "ego_reached_destination"
                break
            if t > a.max_s:
                break
    except KeyboardInterrupt:
        end = "interrupted"
    finally:
        if recorder is not None:
            recorder.close()
        col.stop()
        col.destroy()
        summary = metrics.summary(cfg["evidence"]["criteria"])
        summary.update(end_reason=end, receiver=receiver.stats, tracker_rejects=tracker.rejected,
                       tracks=[{"track": tr.track_id, "id": tr.temp_id.hex(), "msgs": tr.msgs, "role": tr.bsm.role,
                                "class": tr.bsm.vehicle_class, "active": tr.active} for tr in tracker.all()],
                       v2x_path="CARLA adapter -> TENA -> V2X adapter -> tena_bsm_relay -> UDP json")
        path = evidence.write_json("metrics.json", summary)
        evidence.close()
        log.info("result: %s (%s) -> %s", "PASS" if summary["pass"] else "FAIL", end, path)
        for k, val in summary["checks"].items():
            log.info("  %-24s %s", k, val)
        log.info("  modes %s | receiver %s | tracker rejects %s", summary["modes_visited"], receiver.stats, tracker.rejected)
        if not a.keep:
            ego.destroy()
        else:                       # park it: the last control would otherwise keep it rolling off the end of the map
            ego.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))


if __name__ == "__main__":
    main()
