"""
json_transmitter.py

Bridges VISSIM vehicles into the distributed-testing JSON Publisher / Streamer.

Two daemon threads run concurrently:
  - transmit_main(): polls the VISSIM bridge for vehicle spawns/states, packs them into
    LandVehicle SDOs (plus a BSM per vehicle) and sends them to the JSON Publisher REST API.
  - receive_main(): listens for SDOs from the JSON Streamer, captures the map origin from the
    Scenario message, and forwards non-VISSIM LandVehicles to the VISSIM bridge.

Configuration is via environment variables (see the Global Configuration section).

Run:  python3 json_transmitter.py        (Ctrl+C for a clean shutdown)
"""

import codecs
import json
import logging
import math
import os
import queue
import socket
import sys
import threading
import time

import requests

import json_templates
from vissim_bridge import VissimBridge

# =================================
# Global Configuration
# =================================
VUG_STREAMER_BIND_IP = os.getenv("VUG_STREAMER_BIND_IP", "0.0.0.0")
VUG_STREAMER_BIND_PORT = int(os.getenv("VUG_STREAMER_BIND_PORT", "8005"))
VUG_PUBLISHER_REST_IP = os.getenv("VUG_PUBLISHER_REST_IP", "127.0.0.1")
VUG_PUBLISHER_REST_PORT = int(os.getenv("VUG_PUBLISHER_REST_PORT", "8004"))
PUBLISHER_ENDPOINT = f"{VUG_PUBLISHER_REST_IP}:{VUG_PUBLISHER_REST_PORT}"

COORDINATE_FORMAT = os.getenv("COORDINATE_FORMAT", "ltpENU")  # "geocentric" or "ltpENU"
DATA_UPDATE_PERIOD = float(os.getenv("DATA_UPDATE_PERIOD", "0.1"))  # seconds
INDIVIDUAL_TRANSMIT_DELAY = 0.002  # seconds between individual REST calls
HTTP_TIMEOUT = 10  # seconds
MAX_RECV_BUFFER_CHARS = 5_000_000  # drop the buffer if it grows past this without a valid JSON

LOGGING_LEVEL = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
LOG_PATH = os.getenv("VUG_LOCAL_DT_PATH")

ENTITY_ID = "03:05"
VEHICLE_LIST = {f"JSON-M-{i}": {"objectID": i} for i in range(1, 6)}
TRAFFICSIGNALCONTROLLER_LIST = {}

# VISSIM bridge
VISSIM_BRIDGE_IP = os.getenv("VISSIM_BRIDGE_IP", "192.168.122.1")
VISSIM_BRIDGE_PORT = int(os.getenv("VISSIM_BRIDGE_PORT", "5000"))

# RFS OpenDRIVE georeference
RFS_ORIGIN_LAT = 37.9150891287087
RFS_ORIGIN_LON = -122.333308830857

BSM_ID_MAP = {
    "UTC-BG-1": "33333331",
    "UTC-BG-2": "33333332",
    "UTC-BG-3": "33333333",
    "UTC-BG-4": "33333334",
    "UTC-BG-5": "33333335",
}
BSM_FALLBACK_BASE = 0x33330000  # used for vehicles not in BSM_ID_MAP: base + objectID

stop_event = threading.Event()


# =================================
# Logging Setup
# =================================
def setup_logging(level=logging.INFO):
    """Log to LOG_PATH/logs/json_script_logs/ if LOG_PATH is set, otherwise to stderr."""
    fmt = "%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s"
    if LOG_PATH:
        log_folder = os.path.join(LOG_PATH, "logs/json_script_logs/")
        os.makedirs(log_folder, exist_ok=True)
        os.chmod(log_folder, 0o755)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        logging.basicConfig(
            filename=os.path.join(log_folder, f"jsonScriptSend_{timestamp}.log"),
            level=level,
            format=fmt,
        )
    else:
        logging.basicConfig(level=level, format=fmt)
        logging.warning("VUG_LOCAL_DT_PATH not set; logging to stderr")
    logging.info("Logging Established")


# =================================
# Helper Functions
# =================================
def wait_for_port(host, port, timeout=30):
    """Wait for a TCP port to accept connections. Returns True on success, False on timeout."""
    start = time.time()
    while time.time() - start < timeout and not stop_event.is_set():
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except OSError:
            time.sleep(1)
    return False


def ensure_entity(EntityMap, dt_identifier, next_ids):
    """Create an EntityMap entry (with a fresh objectID) if this identifier is new."""
    if dt_identifier not in EntityMap:
        EntityMap[dt_identifier] = {"objectID": next_ids["next"]}
        next_ids["next"] += 1
        logging.info(f"New VISSIM entity {dt_identifier} -> objectID {EntityMap[dt_identifier]['objectID']}")
        return True
    return False


def transmit_object_json(object_json_list, EntityMap, session, V2XEntityMap=None):
    """
    POST new objects to the Publisher, PUT updates to existing ones.

    If a PUT returns 404 (e.g. the publisher restarted), the stored URL is discarded and the
    object is re-created with a POST.
    """
    for object_json in object_json_list:
        attributes = object_json["attributes"]

        if attributes.get("binaryContent") is not None:
            object_type = "VUG-V2XMessage-v1.1.4"
            entity_type = "VUG::TV2XMsg::V2X"
            name = attributes["senderIdentifier"]
            if V2XEntityMap is None:
                raise ValueError("V2XEntityMap is required for V2X publishing")
            active_map = V2XEntityMap
            active_map.setdefault(name, {})
        elif attributes.get("landVehicleData") is not None:
            object_type = "VUG-LandVehicle-v1.1.3"
            entity_type = "VUG::Entities::LandVehicle"
            name = attributes["identifier"]
            active_map = EntityMap
        elif attributes.get("trafficSignalPhases") is not None:
            object_type = "VUG-TrafficSignalController-v1.3.5"
            entity_type = "VUG::Entities::TrafficSignalController"
            name = attributes["identifier"]
            active_map = EntityMap
        else:
            raise ValueError(f"Unsupported object attributes: {list(attributes.keys())}")

        base_url = f"http://{PUBLISHER_ENDPOINT}/v1/objects/{object_type}/{entity_type}"
        logging.debug(f"Transmitting {entity_type} {name} to {base_url}")
        entry = active_map[name]

        if "url" in entry:
            resp = session.put(entry["url"], json=object_json, timeout=HTTP_TIMEOUT)
            if resp.status_code == 404:
                logging.warning(f"{name}: PUT returned 404, re-creating object")
                entry.pop("url")
            else:
                resp.raise_for_status()
                logging.debug(f"Response: {resp}")

        if "url" not in entry:
            resp = session.post(base_url, json=object_json, timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            sdo_index = resp.json().get("sdo_index")
            if sdo_index is None:
                raise ValueError(f"Publisher did not return sdo_index for {entity_type} {name}")
            entry["url"] = f"{base_url}/{sdo_index}"
            logging.info(f"Created {entity_type} {name}: {entry['url']}")

        time.sleep(INDIVIDUAL_TRANSMIT_DELAY)


def get_next_bsm_msg_count(dt_identifier, counters):
    count = counters.get(dt_identifier, 0)
    counters[dt_identifier] = (count + 1) % 128
    return count


def get_bsm_id(dt_identifier, EntityMap):
    """Return the 4-byte BSM temporary ID for a vehicle, with a fallback for unmapped vehicles."""
    hex_id = BSM_ID_MAP.get(dt_identifier)
    if hex_id is not None:
        return bytes.fromhex(hex_id)
    object_id = EntityMap.get(dt_identifier, {}).get("objectID", 0)
    fallback = (BSM_FALLBACK_BASE + object_id) & 0xFFFFFFFF
    logging.debug(f"{dt_identifier} not in BSM_ID_MAP; using fallback BSM id {fallback:08X}")
    return fallback.to_bytes(4, "big")


def vissim_vehicle_to_dt_object_data(spawn):
    msg = spawn["msg"]
    return {
        "object_type": "LandVehicle",
        "role_name": spawn["dt_identifier"],
        "x": float(msg["x"]),
        "y": float(msg["y"]),
        "z": float(msg["z"]),
        "yaw": math.radians(float(msg["yaw"])) % (2 * math.pi),
        "pitch": -math.radians(float(msg["pitch"])),
        "roll": math.pi,
        "vx": float(msg["vx"]),
        "vy": float(msg["vy"]),
        "vz": float(msg["vz"]),
    }


def rfs_xy_to_geodetic(x, y):
    """Convert RFS OpenDRIVE local Transverse Mercator meters to WGS84 lat/lon degrees."""
    a = 6378137.0
    f = 1.0 / 298.257223563
    e2 = f * (2.0 - f)
    ep2 = e2 / (1.0 - e2)

    lat0 = math.radians(RFS_ORIGIN_LAT)
    lon0 = math.radians(RFS_ORIGIN_LON)
    k0 = 1.0

    e4 = e2 * e2
    e6 = e4 * e2

    def meridional_arc(phi):
        return a * (
            (1.0 - e2 / 4.0 - 3.0 * e4 / 64.0 - 5.0 * e6 / 256.0) * phi
            - (3.0 * e2 / 8.0 + 3.0 * e4 / 32.0 + 45.0 * e6 / 1024.0) * math.sin(2.0 * phi)
            + (15.0 * e4 / 256.0 + 45.0 * e6 / 1024.0) * math.sin(4.0 * phi)
            - (35.0 * e6 / 3072.0) * math.sin(6.0 * phi)
        )

    m0 = meridional_arc(lat0)
    m = m0 + y / k0
    mu = m / (a * (1.0 - e2 / 4.0 - 3.0 * e4 / 64.0 - 5.0 * e6 / 256.0))
    e1 = (1.0 - math.sqrt(1.0 - e2)) / (1.0 + math.sqrt(1.0 - e2))

    phi1 = (
        mu
        + (3.0 * e1 / 2.0 - 27.0 * e1**3 / 32.0) * math.sin(2.0 * mu)
        + (21.0 * e1**2 / 16.0 - 55.0 * e1**4 / 32.0) * math.sin(4.0 * mu)
        + (151.0 * e1**3 / 96.0) * math.sin(6.0 * mu)
        + (1097.0 * e1**4 / 512.0) * math.sin(8.0 * mu)
    )

    sin_phi1 = math.sin(phi1)
    cos_phi1 = math.cos(phi1)
    tan_phi1 = math.tan(phi1)

    n1 = a / math.sqrt(1.0 - e2 * sin_phi1**2)
    r1 = a * (1.0 - e2) / (1.0 - e2 * sin_phi1**2) ** 1.5

    t1 = tan_phi1**2
    c1 = ep2 * cos_phi1**2
    d = x / (n1 * k0)

    lat = phi1 - (
        n1 * tan_phi1 / r1
        * (
            d**2 / 2.0
            - (5.0 + 3.0 * t1 + 10.0 * c1 - 4.0 * c1**2 - 9.0 * ep2) * d**4 / 24.0
            + (61.0 + 90.0 * t1 + 298.0 * c1 + 45.0 * t1**2 - 252.0 * ep2 - 3.0 * c1**2) * d**6 / 720.0
        )
    )

    lon = lon0 + (
        d
        - (1.0 + 2.0 * t1 + c1) * d**3 / 6.0
        + (5.0 - 2.0 * c1 + 28.0 * t1 - 3.0 * c1**2 + 8.0 * ep2 + 24.0 * t1**2) * d**5 / 120.0
    ) / cos_phi1

    return math.degrees(lat), math.degrees(lon)


def vissim_vehicle_to_bsm_data(vehicle, EntityMap):
    msg = vehicle["msg"]
    dt_identifier = vehicle["dt_identifier"]

    latitude_deg, longitude_deg = rfs_xy_to_geodetic(float(msg["x"]), float(msg["y"]))

    vx, vy, vz = float(msg["vx"]), float(msg["vy"]), float(msg["vz"])
    speed_mps = math.sqrt(vx**2 + vy**2 + vz**2)
    speed_j2735 = min(int(round(speed_mps / 0.02)), 8190)

    heading_deg = (90.0 - float(msg["yaw"])) % 360.0
    heading_j2735 = int(round(heading_deg / 0.0125)) % 28800

    # Assumes the map Z coordinate is elevation in meters; J2735 elevation is in decimeters.
    elevation_j2735 = max(-4095, min(61439, int(round(float(msg["z"]) * 10))))

    return {
        "bsmid": get_bsm_id(dt_identifier, EntityMap),
        "lat": int(round(latitude_deg * 1e7)),
        "long": int(round(longitude_deg * 1e7)),
        "elev": elevation_j2735,
        "speed": speed_j2735,
        "heading": heading_j2735,
    }


def dt_landvehicle_to_vissim_msg(json_data):
    attributes = json_data["attributes"]
    tspi = attributes["tspi"]["attributes"]
    identifier = attributes["identifier"]

    position = tspi["position"]["attributes"]["ltpENU_asTransmitted"]["attributes"]
    orientation = tspi["orientation"]["attributes"]["frdWRTltpENUbodyFixedZYX_asTransmitted"]["attributes"]

    velocity_data = tspi.get("velocity")
    if velocity_data is not None:
        velocity = velocity_data["attributes"]["ltpENU_asTransmitted"]["attributes"]
        vx = float(velocity["vxInMetersPerSecond"])
        vy = float(velocity["vyInMetersPerSecond"])
        vz = float(velocity["vzInMetersPerSecond"])
    else:
        vx = vy = vz = 0.0

    return {
        "op": "carla_spawn_vehicle",  # name kept: the bridge expects this op string
        "id": identifier,
        "type": "car",
        "x": float(position["xInMeters"]),
        "y": float(position["yInMeters"]),
        "z": float(position["zInMeters"]),
        "yaw": math.degrees(float(orientation["rotZinRadians"])),
        "pitch": -math.degrees(float(orientation["rotYinRadians"])),
        "roll": 0.0,
        "vx": vx,
        "vy": vy,
        "vz": vz,
    }


# =================================
# Transmit thread
# =================================
def publish_vehicle_object(object_data, EntityMap, mapOrigin, session):
    object_json_list = json_templates.pack_object_data_into_json(
        [object_data], EntityMap, mapOrigin, COORDINATE_FORMAT, ENTITY_ID
    )
    transmit_object_json(object_json_list, EntityMap, session)


def transmit_main(mapOrigin_queue, stdout_lock, vissim_bridge):
    """Poll VISSIM and publish vehicles + BSMs to the JSON Publisher until stopped."""
    EntityMap = {**VEHICLE_LIST, **TRAFFICSIGNALCONTROLLER_LIST}
    BSMMessageCounts = {}
    V2XEntityMap = {}
    next_ids = {"next": max((e["objectID"] for e in EntityMap.values()), default=0) + 1}

    # Wait for the map origin from the receive thread
    logging.info("Waiting for Map Origin from receive thread...")
    print("Waiting for Map Origin from receive thread...")
    mapOrigin = None
    while mapOrigin is None and not stop_event.is_set():
        try:
            mapOrigin = mapOrigin_queue.get(timeout=5)
        except queue.Empty:
            logging.info("Still waiting for Scenario message / Map Origin...")
    if mapOrigin is None:
        return
    print(f"Map Origin received: {mapOrigin}")

    while not stop_event.is_set():
        if wait_for_port(VUG_PUBLISHER_REST_IP, VUG_PUBLISHER_REST_PORT):
            break
        logging.error("Publisher REST API is not available, retrying...")
    else:
        return

    session = requests.Session()
    next_t = time.monotonic()

    while not stop_event.is_set():
        try:
            # Pick up the newest map origin if a new Scenario arrived
            try:
                while True:
                    mapOrigin = mapOrigin_queue.get_nowait()
                    logging.info(f"Map Origin updated: {mapOrigin}")
            except queue.Empty:
                pass

            # ---- Spawns ----
            for spawn in vissim_bridge.get_vissim_vehicle_spawns():
                try:
                    object_data = vissim_vehicle_to_dt_object_data(spawn)
                    dt_identifier = object_data["role_name"]
                    if ensure_entity(EntityMap, dt_identifier, next_ids):
                        logging.info(
                            f"Spawn {dt_identifier}: x={object_data['x']:.3f} y={object_data['y']:.3f} "
                            f"z={object_data['z']:.3f} yaw={math.degrees(object_data['yaw']):.3f}"
                        )
                    publish_vehicle_object(object_data, EntityMap, mapOrigin, session)
                except Exception:
                    logging.exception(f"Failed to publish spawn: {spawn}")

            # ---- State updates ----
            for state in vissim_bridge.get_vissim_vehicle_states():
                try:
                    object_data = vissim_vehicle_to_dt_object_data(state)
                    dt_identifier = state["dt_identifier"]
                    ensure_entity(EntityMap, dt_identifier, next_ids)  # state may precede spawn

                    logging.debug(
                        f"VISSIM->DT update id={state['vissim_id']} dt={dt_identifier} "
                        f"x={object_data['x']:.3f} y={object_data['y']:.3f} yaw={object_data['yaw']:.6f}"
                    )
                    publish_vehicle_object(object_data, EntityMap, mapOrigin, session)

                    # BSM for this vehicle (failure here must not block the vehicle update)
                    try:
                        bsm_data = vissim_vehicle_to_bsm_data(state, EntityMap)
                        bsm_data["msgCnt"] = get_next_bsm_msg_count(dt_identifier, BSMMessageCounts)
                        bsm_json = json_templates.generate_bsm(bsm_data, dt_identifier)
                        transmit_object_json([bsm_json], EntityMap, session, V2XEntityMap)
                    except Exception:
                        logging.exception(f"Failed to publish BSM for {dt_identifier}")
                except Exception:
                    logging.exception(f"Failed to publish state: {state}")

        except Exception:
            logging.exception("Transmit cycle failed")
            stop_event.wait(1.0)  # avoid a hot error loop

        # Drift-safe pacing: if we overran, resync instead of falling further behind
        now = time.monotonic()
        next_t = max(next_t + DATA_UPDATE_PERIOD, now)
        stop_event.wait(max(0.0, next_t - time.monotonic()))


# =================================
# Receive thread
# =================================
def get_count_of_objects(type_counts, type_name, stdout_lock):
    """Maintain and display a running count of received messages per entity type."""
    type_counts[type_name] = type_counts.get(type_name, 0) + 1
    display = " | ".join(f"{n.split('::')[-1]}: {c}" for n, c in type_counts.items())
    with stdout_lock:
        sys.stdout.write("\033[s\033[999B")
        sys.stdout.write(f"\r{display}  ")
        sys.stdout.write("\033[u")
        sys.stdout.flush()


def handle_message(json_data, mapOrigin_queue, stdout_lock, vissim_bridge, type_counts):
    """Process one decoded JSON message. Exceptions are handled by the caller."""
    type_name = json_data["metadata"]["type_name"]

    if type_name == "VUG::Configuration::Scenario":
        map_origin = json_templates.get_map_origin_from_scenario(json_data)
        logging.info(f"Map Origin received from Scenario: {map_origin}")
        mapOrigin_queue.put(map_origin)

    elif type_name == "VUG::Entities::LandVehicle":
        identifier = json_data["attributes"]["identifier"]

        with vissim_bridge.state_lock:
            is_vissim_originated = identifier in vissim_bridge.dt_to_vissim

        if is_vissim_originated:
            logging.debug(f"[VISSIM LOOPBACK] Ignoring VISSIM-originated vehicle: {identifier}")
            if vissim_bridge.confirm_vissim_vehicle_registered(identifier):
                logging.info(f"[VISSIM->DT REGISTERED] {identifier}")
        else:
            msg = dt_landvehicle_to_vissim_msg(json_data)
            vissim_bridge.process_dt_landvehicle(msg)

    get_count_of_objects(type_counts, type_name, stdout_lock)


def handle_connection(conn, mapOrigin_queue, stdout_lock, vissim_bridge, type_counts):
    """Read JSON objects from one streamer connection until it closes or we are stopped."""
    conn.settimeout(1.0)
    text_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")  # handles split multibyte chars
    json_decoder = json.JSONDecoder()
    buffer_str = ""

    while not stop_event.is_set():
        try:
            data = conn.recv(65536)
        except socket.timeout:
            continue
        if not data:
            logging.info("Streamer closed the connection")
            return

        buffer_str += text_decoder.decode(data)

        while True:
            buffer_str = buffer_str.lstrip()
            if not buffer_str:
                break
            try:
                json_data, index = json_decoder.raw_decode(buffer_str)
            except json.JSONDecodeError:
                if len(buffer_str) > MAX_RECV_BUFFER_CHARS:
                    logging.error("Receive buffer too large without a valid JSON object; discarding")
                    buffer_str = ""
                break  # partial object: go read more data

            buffer_str = buffer_str[index:]  # always consume the object, even if processing fails
            try:
                handle_message(json_data, mapOrigin_queue, stdout_lock, vissim_bridge, type_counts)
            except Exception:
                logging.exception("Failed to process received message")


def receive_main(mapOrigin_queue, stdout_lock, vissim_bridge):
    """TCP server for SDOs from the JSON Streamer; accepts reconnects until stopped."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((VUG_STREAMER_BIND_IP, VUG_STREAMER_BIND_PORT))
    sock.listen(1)
    sock.settimeout(1.0)
    print(f"Server listening on {VUG_STREAMER_BIND_IP}:{VUG_STREAMER_BIND_PORT} for TCP data...")

    type_counts = {}
    try:
        while not stop_event.is_set():
            try:
                conn, addr = sock.accept()
            except socket.timeout:
                continue
            logging.info(f"Streamer connected from {addr}")
            try:
                handle_connection(conn, mapOrigin_queue, stdout_lock, vissim_bridge, type_counts)
            except Exception:
                logging.exception("Receive connection failed")
            finally:
                conn.close()
    finally:
        sock.close()


# =================================
# Main
# =================================
def main():
    setup_logging(LOGGING_LEVEL)

    mapOrigin_queue = queue.Queue()
    stdout_lock = threading.Lock()

    vissim_bridge = VissimBridge(VISSIM_BRIDGE_IP, VISSIM_BRIDGE_PORT)

    receive_thread = threading.Thread(
        target=receive_main, args=(mapOrigin_queue, stdout_lock, vissim_bridge),
        name="ReceiveThread", daemon=True)
    send_thread = threading.Thread(
        target=transmit_main, args=(mapOrigin_queue, stdout_lock, vissim_bridge),
        name="SendThread", daemon=True)

    vissim_bridge.start()
    receive_thread.start()
    send_thread.start()

    try:
        while receive_thread.is_alive() or send_thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        stop_event.set()
        receive_thread.join(timeout=5)
        send_thread.join(timeout=5)
        if hasattr(vissim_bridge, "stop"):
            try:
                vissim_bridge.stop()
            except Exception:
                logging.exception("Error stopping VISSIM bridge")


if __name__ == "__main__":
    main()