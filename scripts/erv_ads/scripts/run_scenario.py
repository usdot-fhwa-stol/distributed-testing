#!/usr/bin/env python3
"""Run one ERV-interaction scenario end to end in CARLA 0.10.

Spawns the ego (ErvAwareAgent), an emergency vehicle that drives Code 3 and
broadcasts J2735 BSMs at 10 Hz, and background traffic; runs synchronously
at 20 Hz; writes evidence to runs/<timestamp>-<scenario>/.

    python scripts/run_scenario.py --scenario approach_from_behind
    python scripts/run_scenario.py --scenario stationary_ahead --set erv.bsm_profile=full
    python scripts/run_scenario.py --scenario oncoming --set v2x.transport=udp
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import carla  # noqa: E402

from erv_ego import build as B  # noqa: E402
from erv_ego import carla_compat as cc  # noqa: E402
from erv_ego import scenarios  # noqa: E402
from erv_ego.config import load_config, set_dotted  # noqa: E402
from erv_ego.ego.agent import ErvAwareAgent  # noqa: E402
from erv_ego.ego.policy import Mode  # noqa: E402
from erv_ego.erv.driver import ErvDriver  # noqa: E402
from erv_ego.evidence import Evidence, Metrics  # noqa: E402
from erv_ego.geo import CarlaGeoRef  # noqa: E402
from erv_ego.v2x.transport import InProcessBus  # noqa: E402

log = logging.getLogger("run_scenario")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=None)
    p.add_argument("--scenario", default=None, help="built-in: " + ", ".join(scenarios.BUILDERS)
                   + "; any other name needs the poses pinned in the config")
    p.add_argument("--cam", default=None,
                   help="camera attributes for --record, e.g. exposure_mode=manual,fstop=2.0,shutter_speed=500,iso=100 "
                        "(a generated OpenDRIVE world has no sky or ground and auto-exposure drifts to black)")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--map", default=None)
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="override any config key, e.g. --set policy.yield_trigger_ttr_s=10")
    p.add_argument("--record", action="store_true",
                   help="save chase.mp4 and top.mp4 (10 fps, real-time playback) in the run folder; "
                        "needs a rendering server and opencv-python")
    p.add_argument("--realtime", action="store_true",
                   help="pace the run to wall-clock time so it can be watched in the CARLA window")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def spawn_background(client, world, cmap, n: int, keep_clear, tm_port: int, seed: int):
    if n <= 0:
        return []
    rng = random.Random(seed)
    def four_wheels(bp):
        return not bp.has_attribute("number_of_wheels") or bp.get_attribute("number_of_wheels").as_int() == 4

    bps = [bp for bp in world.get_blueprint_library().filter("vehicle.*")
           if four_wheels(bp)
           and not any(k in bp.id for k in ("firetruck", "ambulance", "police", "bus", "mine", "earth"))]
    sps = cmap.get_spawn_points()
    rng.shuffle(sps)
    batch = []
    for sp in sps:
        if len(batch) >= n:
            break
        if any(sp.location.distance(k) < 35.0 for k in keep_clear):
            continue
        bp = rng.choice(bps)
        bp.set_attribute("role_name", "background")
        batch.append(carla.command.SpawnActor(bp, sp).then(
            carla.command.SetAutopilot(carla.command.FutureActor, True, tm_port)))
    ids = [r.actor_id for r in client.apply_batch_sync(batch, True) if not r.error]
    return list(world.get_actors(ids))


class Recorder:
    """Two RGB cameras on the ego (chase and top-down) written to mp4 as frames arrive."""

    VIEWS = {
        "chase": (carla.Transform(carla.Location(x=-11.0, z=6.0), carla.Rotation(pitch=-20.0)), 90.0),
        "top": (carla.Transform(carla.Location(x=12.0, z=42.0), carla.Rotation(pitch=-90.0)), 70.0),
    }

    def __init__(self, world, ego, out_dir, width=1280, height=720, fps=10, attrs=None):
        import cv2
        import numpy as np
        self._cv2, self._np = cv2, np
        self.sensors, self.writers, self.frames = [], {}, {}
        self.labels = {}
        bp = world.get_blueprint_library().find("sensor.camera.rgb")
        bp.set_attribute("image_size_x", str(width))
        bp.set_attribute("image_size_y", str(height))
        bp.set_attribute("sensor_tick", str(1.0 / fps))
        for k, v in (attrs or {}).items():          # e.g. exposure_compensation on a generated OpenDRIVE world
            bp.set_attribute(k, str(v))
        for name, (tf, fov) in self.VIEWS.items():
            bp.set_attribute("fov", str(fov))
            cam = world.spawn_actor(bp, tf, attach_to=ego)
            path = os.path.join(out_dir, name + ".mp4")
            self.writers[name] = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
            self.frames[name] = 0
            cam.listen(lambda img, n=name: self._on_image(n, img))
            self.sensors.append(cam)
        self.caption = ""

    def _on_image(self, name, img):
        cv2, np = self._cv2, self._np
        arr = np.frombuffer(img.raw_data, dtype=np.uint8).reshape((img.height, img.width, 4))[:, :, :3].copy()
        if self.caption:
            cv2.rectangle(arr, (0, 0), (img.width, 44), (0, 0, 0), -1)
            cv2.putText(arr, self.caption, (14, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
        self.writers[name].write(arr)
        self.frames[name] += 1

    def close(self):
        for s in self.sensors:
            try:
                s.stop()
                s.destroy()
            except Exception:
                pass
        time.sleep(0.5)
        for w in self.writers.values():
            w.release()


def follow_cam(spectator, actor):
    tf = actor.get_transform()
    fwd = tf.get_forward_vector()
    loc = tf.location - fwd * 14.0 + carla.Location(z=7.0)
    spectator.set_transform(carla.Transform(loc, carla.Rotation(pitch=-22.0, yaw=tf.rotation.yaw)))


def main():
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    for kv in args.set:
        k, v = kv.split("=", 1)
        set_dotted(cfg, k, v)
    if args.scenario:
        cfg["scenario"]["name"] = args.scenario
    if args.host:
        cfg["carla"]["host"] = args.host
    if args.port:
        cfg["carla"]["port"] = args.port
    if args.map:
        cfg["carla"]["map"] = args.map
    cc_cfg, sc_cfg = cfg["carla"], cfg["scenario"]

    client = carla.Client(cc_cfg["host"], int(cc_cfg["port"]))
    client.set_timeout(float(cc_cfg["timeout_s"]))
    log.info("CARLA server %s, client %s", cc.server_version(client), getattr(carla, "__version__", "?"))
    world = client.get_world()
    want = cc_cfg.get("map")
    if want and str(want).lower().endswith(".xodr") and not os.path.isabs(want) and not os.path.exists(want):
        want = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), want)   # relative to the repo
    if want and str(want).lower().endswith(".xodr"):
        # an OpenDRIVE file: generate the world from it (roads only), with the settings the DT stack uses.
        # Regenerated only when another map is loaded, or carla.reload_xodr is set.
        if not world.get_map().name.endswith("OpenDriveMap") or cc_cfg.get("reload_xodr"):
            with open(want, encoding="utf-8") as f:
                world = client.generate_opendrive_world(f.read(), carla.OpendriveGenerationParameters(
                    vertex_distance=2.0, max_road_length=500.0, wall_height=0.0, additional_width=0.0,
                    smooth_junctions=False, enable_mesh_visibility=True))
            log.info("generated the world from %s", want)
    elif want and not world.get_map().name.endswith(want):
        world = client.load_world(want)
    cmap = world.get_map()

    original = world.get_settings()
    n_bg = int(sc_cfg.get("background_vehicles", 0))
    tm = None

    evidence = Evidence(cfg["evidence"]["out_dir"], time.strftime("%Y%m%d-%H%M%S-") + sc_cfg["name"])
    evidence.write_json("config.json", cfg)
    metrics = Metrics()
    actors = []
    sensors = []
    try:
        settings = world.get_settings()
        settings.synchronous_mode = bool(cc_cfg.get("synchronous", True))
        settings.fixed_delta_seconds = float(cc_cfg["fixed_delta_s"])
        world.apply_settings(settings)
        if n_bg > 0:                       # the Traffic Manager is only needed for background traffic
            try:
                tm = client.get_trafficmanager(int(cc_cfg["tm_port"]))
            except RuntimeError as exc:
                raise RuntimeError(f"Traffic Manager port {cc_cfg['tm_port']} is not available ({exc}). "
                                   f"Pick another with --set carla.tm_port=8010, or run without background "
                                   f"traffic (--set scenario.background_vehicles=0).") from exc
            tm.set_synchronous_mode(settings.synchronous_mode)
            tm.set_random_device_seed(int(sc_cfg.get("seed") or 0))

        georef = CarlaGeoRef.from_carla_map(cmap)
        geo_err = georef.self_check(cmap)
        log.info("georef origin %.7f, %.7f  model=%s  round-trip error %.3f m  heading offset %.3f deg",
                 georef.lat0, georef.lon0, georef.model, geo_err, georef.heading_offset_deg)
        evidence.event("georef", 0.0, lat0=georef.lat0, lon0=georef.lon0, model=georef.model,
                       model_error_m=georef.model_error_m, self_check_m=geo_err,
                       heading_offset_deg=georef.heading_offset_deg, map=cmap.name)

        _, GRP = cc.import_agents()
        grp = GRP(cmap, 2.0)
        setup = scenarios.build(cmap, sc_cfg)
        log.info("scenario %s: %s", setup.name, setup.note)
        evidence.event("scenario", 0.0, name=setup.name, note=setup.note,
                       ego=[setup.ego_tf.location.x, setup.ego_tf.location.y],
                       erv=[setup.erv_tf.location.x, setup.erv_tf.location.y], erv_stationary=setup.erv_stationary)

        lib = world.get_blueprint_library()
        ego_bp = cc.find_blueprint(lib, cfg["ego"]["blueprint"])
        ego_bp.set_attribute("role_name", cfg["ego"]["role_name"])
        ego = world.spawn_actor(ego_bp, setup.ego_tf)
        actors.append(ego)
        erv_kind = cfg["erv"]["kind"]
        erv_bp = cc.find_blueprint(lib, cc.ERV_BLUEPRINT_PATTERNS.get(erv_kind, ["*firetruck*"]))
        erv_bp.set_attribute("role_name", cfg["erv"]["role_name"])
        erv = world.spawn_actor(erv_bp, setup.erv_tf)
        actors.append(erv)
        log.info("ego %s (%s), ERV %s (%s)", ego.id, ego.type_id, erv.id, erv.type_id)

        col_bp = lib.find("sensor.other.collision")
        col = world.spawn_actor(col_bp, carla.Transform(), attach_to=ego)
        sensors.append(col)
        last_tick = {"t": 0.0}

        def on_collision(ev):
            rec = {"other": ev.other_actor.type_id, "other_id": ev.other_actor.id,
                   "impulse": math.sqrt(ev.normal_impulse.x ** 2 + ev.normal_impulse.y ** 2 + ev.normal_impulse.z ** 2)}
            metrics.collisions.append(dict(rec, t=last_tick["t"]))
            evidence.event("collision", last_tick["t"], **rec)

        col.listen(on_collision)
        cam = args.cam or cc_cfg.get("record_camera")
        cam_attrs = dict(kv.split("=", 1) for kv in cam.split(",") if "=" in kv) if isinstance(cam, str) else (cam or {})
        recorder = Recorder(world, ego, evidence.dir, attrs=cam_attrs) if args.record else None

        bg = spawn_background(client, world, cmap, n_bg,
                              [setup.ego_tf.location, setup.erv_tf.location], int(cc_cfg["tm_port"]),
                              int(sc_cfg.get("seed") or 0))
        actors.extend(bg)
        log.info("background vehicles: %d", len(bg))

        # ---- V2X plumbing ----------------------------------------------------
        clock = B.clock_from_cfg(cfg)
        codec = B.codec_from_cfg(cfg)
        log.info("codec: %s", codec.name)
        transport = cfg["v2x"]["transport"]
        if transport == "udp":
            erv_tx, ego_rx, ego_tx = B.udp_endpoints(cfg)
        else:
            bus = InProcessBus()
            erv_tx = bus.subscribe("erv")
            ego_rx = bus.subscribe("ego")
            ego_tx = ego_rx
        receiver = B.receiver_from_cfg(cfg, [ego_rx], codec, georef, world, evidence)
        tracker = B.tracker_from_cfg(cfg, clock, evidence)
        policy = B.policy_from_cfg(cfg, evidence)
        erv_gen = B.erv_generator_from_cfg(cfg, georef, clock)
        ego_tx_tuple = (B.ego_generator_from_cfg(cfg, georef, clock), ego_tx, codec) \
            if cfg["ego"].get("broadcast_bsm") else None

        world.tick()   # make spawned actors valid for the agents
        agent = ErvAwareAgent(ego, world, cmap, grp, receiver, tracker, policy, georef, cfg["ego"],
                              evidence, metrics, ego_tx_tuple)
        agent.set_destination(setup.ego_dest)

        erv_cfg = dict(cfg["erv"])
        erv_cfg["stationary"] = setup.erv_stationary
        driver = ErvDriver(erv, world, cmap, grp, erv_cfg)
        if setup.erv_dest is not None:
            driver.set_destination(setup.erv_dest, via=setup.erv_via)
        erv_wheel = cc.max_road_wheel_deg(erv)
        erv_period = 1.0 / float(cfg["erv"]["bsm_rate_hz"])

        # ---- what the ERV does during the run, and what the ego is expected to do --------------
        # scenario.erv_script: [{at_s: 12} | {at_range_m: 60}, then any of code3: bool, stop: true, go: true,
        #                        dest: [x, y, z]]   - each step fires once, in any order
        script = [dict(s) for s in (sc_cfg.get("erv_script") or [])]
        expect = dict(sc_cfg.get("expect") or {})
        truth = {"erv_passed_ego": False, "ego_passed_erv": False, "min_gap_m": None}
        rel0 = {}

        def run_script(now, rng):
            for step in script:
                if step.get("_done"):
                    continue
                if ("at_s" in step and now >= float(step["at_s"])) or \
                        ("at_range_m" in step and rng <= float(step["at_range_m"])):
                    step["_done"] = True
                    done = []
                    if "code3" in step:
                        driver.set_code3(bool(step["code3"]))
                        done.append("lights and siren " + ("ON" if step["code3"] else "OFF"))
                    if step.get("stop"):
                        driver.stop()
                        done.append("stops")
                    if step.get("go"):
                        driver.go()
                        done.append("drives on")
                    if step.get("dest"):
                        driver.set_destination(scenarios._point(step["dest"]))
                        done.append("new destination")
                    evidence.event("erv_script", now, action=", ".join(done), range_m=rng)
                    log.info("t=%.1f ERV %s (range %.0f m)", now, ", ".join(done), rng)

        spectator = world.get_spectator()
        t0 = world.get_snapshot().timestamp.elapsed_seconds
        last_erv_tx = -1e9
        resume_seen_t = None
        dt = float(cc_cfg["fixed_delta_s"])
        steps = int(float(sc_cfg["max_duration_s"]) / dt)
        tx_count = 0
        t = 0.0
        end_reason = "max_duration"

        wall0 = time.time()
        for step_i in range(steps):
            if args.realtime:
                ahead = step_i * dt - (time.time() - wall0)
                if ahead > 0:
                    time.sleep(ahead)
            world.tick()
            snap = world.get_snapshot()
            t = snap.timestamp.elapsed_seconds - t0
            last_tick["t"] = t
            clock.set_sim_time(snap.timestamp.elapsed_seconds)

            # ground truth for the expectations: who got past whom, and how close
            etf, rtf = ego.get_transform(), erv.get_transform()
            dxy = (rtf.location.x - etf.location.x, rtf.location.y - etf.location.y)
            gap = math.hypot(*dxy)
            truth["min_gap_m"] = gap if truth["min_gap_m"] is None else min(truth["min_gap_m"], gap)
            ef, rf = etf.get_forward_vector(), rtf.get_forward_vector()
            erv_ahead = dxy[0] * ef.x + dxy[1] * ef.y                # ERV position along the ego's heading
            ego_ahead = -(dxy[0] * rf.x + dxy[1] * rf.y)             # ego position along the ERV's heading
            if gap < 60.0:
                rel0.setdefault("erv_ahead", erv_ahead)
                rel0.setdefault("ego_ahead", ego_ahead)
                if rel0["erv_ahead"] < -3.0 and erv_ahead > 6.0:
                    truth["erv_passed_ego"] = True
                if rel0["ego_ahead"] < -3.0 and ego_ahead > 6.0:
                    truth["ego_passed_erv"] = True
            run_script(t, gap)
            # a generated OpenDRIVE world has ground only under the lanes: a vehicle that leaves them falls
            if rtf.location.z < setup.erv_tf.location.z - 8.0 or etf.location.z < setup.ego_tf.location.z - 8.0:
                truth["left_the_road"] = "ERV" if rtf.location.z < setup.erv_tf.location.z - 8.0 else "ego"
                evidence.event("left_the_road", t, who=truth["left_the_road"])
                end_reason = truth["left_the_road"].lower() + "_left_the_road"
                break

            # ERV: drive + broadcast
            if t < setup.erv_start_delay_s and not setup.erv_stationary:
                erv.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))
            else:
                erv.apply_control(driver.run_step())
            if t - last_erv_tx >= erv_period - 1e-6:
                state = cc.vehicle_state(erv, siren=driver.siren_on, max_wheel_deg=erv_wheel)
                bsm = erv_gen.build(state, t)
                erv_tx.send(codec.encode_bsm(bsm))
                last_erv_tx = t
                tx_count += 1

            # ego
            ego.apply_control(agent.run_step(t))
            if cc_cfg.get("spectator_follow", True):
                follow_cam(spectator, ego)

            mode = agent.last_action.mode if agent.last_action else None
            if recorder is not None:
                v = ego.get_velocity()
                near = min(agent.last_threats, key=lambda th: th.range_m) if agent.last_threats else None
                recorder.caption = "t=%5.1fs  %-20s %4.0f km/h" % (t, mode.value if mode else "", 3.6 * math.hypot(v.x, v.y)) \
                    + ("   ERV %s %.0f m" % (near.relation.value, near.range_m) if near else "   no ERV heard")
            # the encounter is over at the first RESUME that follows a real response:
            # a hold, or (stationary ERV) the slow pass
            if mode == Mode.RESUME and resume_seen_t is None \
                    and (setup.erv_stationary or metrics.stopped_t is not None or sc_cfg.get("end_on_resume")):
                resume_seen_t = t
            if resume_seen_t is not None and t - resume_seen_t > float(sc_cfg.get("end_after_resume_s", 8)):
                end_reason = "resumed_after_erv"
                break
            if ego.get_location().distance(setup.ego_dest) < 5.0:
                end_reason = "ego_reached_destination"
                break
            if metrics.collisions:
                end_reason = "collision"
                break

        summary = metrics.summary(cfg["evidence"]["criteria"])
        summary["checks"]["stayed_on_the_road"] = "left_the_road" not in truth
        summary["pass"] = all(summary["checks"].values())
        if expect:
            visited = set(summary["modes_visited"])
            ev = ego.get_velocity()
            facts = dict(truth, ego_moving_at_end=math.hypot(ev.x, ev.y) > 1.0,
                         final_mode=mode.value if mode else None)
            misses = []
            for m in expect.get("visited", []):
                if m not in visited:
                    misses.append(f"never entered {m}")
            if expect.get("visited_any") and not visited & set(expect["visited_any"]):
                misses.append("entered none of " + "/".join(expect["visited_any"]))
            for m in expect.get("not_visited", []):
                if m in visited:
                    misses.append(f"entered {m}")
            for key in ("erv_passed_ego", "ego_passed_erv", "ego_moving_at_end"):
                if key in expect and bool(expect[key]) != bool(facts[key]):
                    misses.append(f"{key} is {facts[key]}, expected {expect[key]}")
            if "min_gap_at_least_m" in expect and (facts["min_gap_m"] or 0.0) < float(expect["min_gap_at_least_m"]):
                misses.append(f"came within {facts['min_gap_m']:.1f} m (centre to centre)")
            summary["checks"]["as_expected"] = not misses
            summary["pass"] = all(summary["checks"].values())
            summary["expect"] = {"wanted": expect, "facts": facts, "misses": misses}
        summary.update({
            "scenario": setup.name, "map": cmap.name, "end_reason": end_reason, "sim_time_s": round(t, 2),
            "erv_bsm_tx": tx_count, "codec": codec.name, "transport": transport,
            "receiver": receiver.stats,
            "channel": receiver.channel.stats.as_dict() if receiver.channel else None,
            "tracker_rejects": tracker.rejected,
            "tracks": [{"track": tr.track_id, "msgs": tr.msgs, "lost_by_msgcnt": tr.lost,
                        "id_changes": tr.id_changes, "role": tr.bsm.role, "class": tr.bsm.vehicle_class}
                       for tr in tracker.all()],
            "event_counts": evidence.counts,
        })
        path = evidence.write_json("metrics.json", summary)
        log.info("result: %s  (%s)  -> %s", "PASS" if summary["pass"] else "FAIL", end_reason, path)
        for miss in summary.get("expect", {}).get("misses", []):
            log.info("  not as expected: %s", miss)
        for k, v in summary["checks"].items():
            log.info("  %-24s %s", k, v)
    finally:
        if "recorder" in locals() and recorder is not None:
            recorder.close()
            log.info("video: %s", {n: c for n, c in recorder.frames.items()})
        for s in sensors:
            try:
                s.stop()
                s.destroy()
            except Exception:
                pass
        if actors:
            client.apply_batch([carla.command.DestroyActor(a.id) for a in actors])
        world.apply_settings(original)
        if tm is not None:
            try:
                tm.set_synchronous_mode(False)
            except Exception:
                pass
        evidence.close()


if __name__ == "__main__":
    main()
