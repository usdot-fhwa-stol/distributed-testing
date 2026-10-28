"""Move the existing ego back to its start (--back metres before the ERV, same lane) WITHOUT respawning it, so the DT CARLA
adapter keeps publishing it.   python repark_ego.py [--role VW-M-1] [--erv-role PATH-M-1] [--back 150]"""
import argparse, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
# inside the repo (carla-erv-ego/dt/) or next to it (tools/erv-ego/ beside carla-erv-ego/)
REPO = os.path.abspath(next((p for p in (os.path.join(HERE, ".."), os.path.join(HERE, "..", "..", "carla-erv-ego"))
                             if os.path.isdir(os.path.join(p, "erv_ego"))), os.path.join(HERE, "..")))
sys.path.insert(0, REPO)
import carla
from erv_ego import carla_compat as cc

ap = argparse.ArgumentParser()
ap.add_argument("--role", default="VW-M-1")
ap.add_argument("--erv-role", default="PATH-M-1")
ap.add_argument("--back", type=float, default=150.0)
a = ap.parse_args()
c = carla.Client("127.0.0.1", 2000); c.set_timeout(30); w = c.get_world(); m = w.get_map()
ego, erv = cc.find_actor_by_role(w, a.role), cc.find_actor_by_role(w, a.erv_role)
if ego is None or erv is None:
    sys.exit("missing in CARLA: " + ", ".join(r for r, x in ((a.role, ego), (a.erv_role, erv)) if x is None))
start, got = cc.walk_straight(m.get_waypoint(erv.get_location()), a.back, forward=False)
tf = start.transform; tf.location.z += 0.5
ego.set_target_velocity(carla.Vector3D()); ego.set_target_angular_velocity(carla.Vector3D())
ego.set_transform(tf)
ego.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))
time.sleep(2.0)
t = ego.get_transform()
print("re-parked %s (actor %d) %.0f m before %s at %.1f, %.1f, %.1f" % (a.role, ego.id, got, a.erv_role, t.location.x, t.location.y, t.location.z))
