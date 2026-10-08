import json
import socket
import sys

try:
    # Confirm the emulator's TCP input listener is accepting connections.
    with socket.create_connection(("127.0.0.1", 5000), timeout=2):
        pass

    # Confirm GPSD responds using its client protocol.
    with socket.create_connection(("127.0.0.1", 2947), timeout=2) as client:
        client.settimeout(2)
        with client.makefile("rb") as stream:
            response = json.loads(stream.readline(4096))
        if response.get("class") != "VERSION":
            raise ValueError("GPSD did not return VERSION")
except (OSError, ValueError) as error:
    print(f"GPSD not ready: {error}", file=sys.stderr)
    sys.exit(1)
