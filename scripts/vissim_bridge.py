import json
import queue
import socket
import threading

def recv_lines(sock):
    """
    Receive newline-delimited messages from a TCP socket.
    """
    buf = b""

    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break

        buf += chunk

        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            yield line.decode("utf-8", errors="replace").strip()


def send_json(sock, obj):
    """
    Send a JSON object over TCP using newline-delimited framing.
    """
    msg = json.dumps(obj) + "\n"
    sock.sendall(msg.encode("utf-8"))

class VissimBridge:

    def __init__(self, host, port):
        self.host = host
        self.port = port

        self.state_lock = threading.Lock()

        # Main state for DT vehicles mirrored into VISSIM
        # DT identifier -> vehicle information ("UTC-M-1"  ->  {"bridge_id": 1, "vissim_id": 37})
        self.dt_vehicles = {}

        # Reverse lookup index
        # bridge ID -> DT identifier (1 -> "UTC-M-1")
        self.bridge_to_dt = {}

        # Next numeric ID used by the existing VISSIM TCP protocol
        self.next_bridge_vehicle_id = 1

        # Latest state of VISSIM-owned vehicles to be published to DT
        # VISSIM vehicle ID -> latest vehicle message
        self.latest_vissim_vehicle_spawn = {}
        self.latest_vissim_vehicle_states = {}

        # VISSIM-originated vehicle mappings
        self.vissim_to_dt = {}   # VISSIM VehicleID -> DT identifier (exp:  8: "UTC-VISSIM-M-1",12: "UTC-VISSIM-M-2")
        self.dt_to_vissim = {}   # DT identifier -> VISSIM VehicleID (exp: "UTC-VISSIM-M-1": 8,"UTC-VISSIM-M-2": 12,)

        self.next_vissim_dt_id = 1

        # VISSIM vehicles whose DT registration has already been confirmed
        self.registered_vissim_vehicles = set()



        # Messages waiting to be sent to VISSIM
        self.outgoing_messages = queue.Queue()

        self.running = True

    def start(self):
        threading.Thread(target=self._server_main, name="VissimServerThread", daemon=True).start()

    def _server_main(self):
        """
        Start the TCP server used by the Windows VISSIM client.
        """
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        server.bind((self.host, self.port))
        server.listen(1)

        print(
            f"[VISSIM Bridge] Listening on "
            f"{self.host}:{self.port}"
        )

        while self.running:
            sock, addr = server.accept()
            print(f"[VISSIM Bridge] VISSIM client connected: {addr}")
            threading.Thread(target=self._handle_client, args=(sock, addr), daemon=True).start()

    def _handle_client(self, sock, addr):
        """
        Handle bidirectional communication with the VISSIM client.
        """

        def sender_thread():
            while self.running:
                try:
                    msg = self.outgoing_messages.get(timeout=0.1)
                    send_json(sock, msg)

                except queue.Empty:
                    continue

                except Exception as e:
                    print(f"[VISSIM Bridge] Sender error: {e}")
                    break

        def receiver_thread():
            try:
                for line in recv_lines(sock):
                    if not line:
                        continue

                    try:
                        msg = json.loads(line)

                    except json.JSONDecodeError:
                        send_json(sock, {"ok": False,"error": "bad_json","op": "response"})
                        continue

                    op = msg.get("op")

                    if op == "ping":
                        print("[VISSIM Bridge] Received VISSIM ping")
                        send_json(sock, {"ok": True,"msg": "pong","op": "response"})
                        print("[VISSIM Bridge] Sent pong")

                    elif op == "spawn_carla_vehicle" and msg.get("ok"):
                        bridge_id = msg.get("carla_actor_id")
                        vissim_id = msg.get("vissim_id")

                        with self.state_lock:
                            dt_identifier = self.bridge_to_dt.get(bridge_id)
                            if dt_identifier is not None:
                                self.dt_vehicles[dt_identifier]["vissim_id"] = vissim_id

                        if dt_identifier is None:
                            print(
                                f"[VISSIM Bridge] Unknown bridge ID "
                                f"in spawn response: {bridge_id}"
                            )                            
                        else:
                            print(
                                f"[VISSIM Bridge] DT vehicle {dt_identifier} "
                                f"spawned in VISSIM as {vissim_id}"
                            )
                    elif op == "spawn_vehicle":
                        vissim_id = int(msg["id"])

                        with self.state_lock:
                            dt_identifier = self.vissim_to_dt.get(vissim_id)

                            if dt_identifier is None:
                                dt_identifier = f"UTC-BG-{self.next_vissim_dt_id}"
                                self.next_vissim_dt_id += 1

                                self.vissim_to_dt[vissim_id] = dt_identifier
                                self.dt_to_vissim[dt_identifier] = vissim_id

                            self.latest_vissim_vehicle_spawn[vissim_id] = msg

                        print(
                            f"[VISSIM Bridge] Received VISSIM vehicle spawn: "
                            f"{vissim_id} -> {dt_identifier}"
                        )

                    elif op == "update_vehicle":
                        vissim_id = int(msg["id"])

                        with self.state_lock:
                            self.latest_vissim_vehicle_states[vissim_id] = msg

                        print(
                            f"\n[VISSIM-UPDATE-DEBUG] id={vissim_id}, "
                            f"x={msg['x']:.3f}, y={msg['y']:.3f}, z={msg['z']:.3f}"
                            f"yaw={msg['yaw']:.3f}, "
                            f"vx={msg['vx']:.3f}, vy={msg['vy']:.3f}"
                        )
            

            except (ConnectionError, socket.timeout) as e:
                print(f"[VISSIM Bridge] VISSIM client disconnected: {e}")

            finally:
                sock.close()
                print(f"[VISSIM Bridge] Connection closed: {addr}")

        threading.Thread(target=sender_thread, daemon=True).start()
        threading.Thread(target=receiver_thread, daemon=True).start()

    def get_or_create_bridge_id(self, dt_identifier):
        with self.state_lock:
            if dt_identifier in self.dt_vehicles:
                return self.dt_vehicles[dt_identifier]["bridge_id"]

            bridge_id = self.next_bridge_vehicle_id
            self.next_bridge_vehicle_id += 1

            self.dt_vehicles[dt_identifier] = {"bridge_id": bridge_id, "vissim_id": None}

            self.bridge_to_dt[bridge_id] = dt_identifier

            return bridge_id

    def process_dt_landvehicle(self, msg):
        dt_identifier = msg["id"]

        with self.state_lock:
            vehicle = self.dt_vehicles.get(dt_identifier)

            if vehicle is None:
                bridge_id = self.next_bridge_vehicle_id
                self.next_bridge_vehicle_id += 1

                self.dt_vehicles[dt_identifier] = {
                    "bridge_id": bridge_id,
                    "vissim_id": None
                }

                self.bridge_to_dt[bridge_id] = dt_identifier

                is_new_vehicle = True

            else:
                bridge_id = vehicle["bridge_id"]
                is_new_vehicle = False

        vissim_msg = msg.copy()
        vissim_msg["id"] = bridge_id

        if is_new_vehicle:
            vissim_msg["op"] = "carla_spawn_vehicle"

            print(
                f"[VISSIM Bridge] New DT vehicle {dt_identifier} "
                f"-> bridge ID {bridge_id}"
            )
        else:
            vissim_msg["op"]="carla_update_vehicle"

        self.outgoing_messages.put(vissim_msg)

    def get_vissim_vehicle_spawns(self):
        with self.state_lock:
            spawns = []

            for vissim_id, msg in self.latest_vissim_vehicle_spawn.items():

                if vissim_id in self.registered_vissim_vehicles:
                    continue

                dt_identifier = self.vissim_to_dt[vissim_id]

                spawns.append({
                    "vissim_id": vissim_id,
                    "dt_identifier": dt_identifier,
                    "msg": msg.copy()
                })

            return spawns


    def confirm_vissim_vehicle_registered(self, dt_identifier):
        with self.state_lock:
            vissim_id = self.dt_to_vissim.get(dt_identifier)

            if vissim_id is None:
                return False

            if vissim_id in self.registered_vissim_vehicles:
                return False

            self.registered_vissim_vehicles.add(vissim_id)

        self.outgoing_messages.put({
            "op": "vissim_vehicle_registered",
            "vissim_id": vissim_id,
            "dt_identifier": dt_identifier
        })

        return True

    def get_vissim_vehicle_states(self):
        with self.state_lock:
            states = []

            for vissim_id, msg in self.latest_vissim_vehicle_states.items():
                dt_identifier = self.vissim_to_dt.get(vissim_id)

                if dt_identifier is None:
                    continue

                states.append({
                    "vissim_id": vissim_id,
                    "dt_identifier": dt_identifier,
                    "msg": msg.copy()
                })

            return states







