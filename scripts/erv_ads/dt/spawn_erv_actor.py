"""Put the stationary ERV into CARLA as a plain actor named AMG-ERV-1 (the name the scenario file lists), lightbar on.
The DT CARLA adapter publishes it to the TENA execution and generates its BSMs (with emergency Part II). Ctrl+C / --remove
destroys it.   python spawn_erv_actor.py [--pose x,y,z,yaw] [--remove]"""
import argparse, sys, time
import carla

ap = argparse.ArgumentParser()
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--role", default="AMG-ERV-1")
ap.add_argument("--pose", default="66.959,-127.476,7.17,-70.93", help="Event 3 ERV pose on Egret Way northbound")
ap.add_argument("--remove", action="store_true")
ap.add_argument("--dark", action="store_true", help="lightbar and siren lights OFF: the vehicle is there but is not announcing an emergency")
ap.add_argument("--hold", action="store_true", help="stay attached and destroy the actor on Ctrl+C")
a = ap.parse_args()
c = carla.Client(a.host, 2000); c.set_timeout(30); w = c.get_world()
old = [v for v in w.get_actors().filter("vehicle.*") if v.attributes.get("role_name") == a.role]
for v in old:
    v.destroy()
if a.remove:
    print("removed", len(old)); sys.exit(0)
x, y, z, yaw = [float(s) for s in a.pose.split(",")]
bp = w.get_blueprint_library().find("vehicle.ambulance.ford"); bp.set_attribute("role_name", a.role)
erv = w.spawn_actor(bp, carla.Transform(carla.Location(x, y, z), carla.Rotation(yaw=yaw)))
L = carla.VehicleLightState
erv.set_light_state(carla.VehicleLightState(L.Position) if a.dark else
                    carla.VehicleLightState(L.Special1 | L.Special2 | L.LowBeam | L.Position | L.LeftBlinker | L.RightBlinker))
erv.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))
for _ in range(3):
    w.wait_for_tick(10.0)
t = erv.get_transform()
try:
    ls = erv.get_light_state()
except RuntimeError as e:
    ls = "unavailable (%s)" % e
print("spawned", a.role, erv.id, "at %.2f %.2f %.2f yaw %.1f" % (t.location.x, t.location.y, t.location.z, t.rotation.yaw), "lights", ls)
if a.hold:
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        erv.destroy()
