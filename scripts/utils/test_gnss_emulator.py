# Send replay raw PCAP using UDP
import socket
from time import sleep
import os
import sys

# =================================
# Global Configurations
# =================================
LOCAL_ADDRESS = os.getenv("VUG_LOCAL_ADDRESS")
HWIL_GNSS_EMULATOR_SEND_ADDRESS = os.getenv("HWIL_GNSS_EMULATOR_SEND_ADDRESS")
HWIL_GNSS_EMULATOR_SEND_PORT = int(os.getenv("HWIL_GNSS_EMULATOR_SEND_PORT", 51928))
HWIL_GNSS_EMULATOR_COMMAND_PORT = int(os.getenv("HWIL_GNSS_EMULATOR_COMMAND_PORT", 9000))


def main():
  sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  start_command = bytes("start", 'utf-8')
  stop_command = bytes("stop", 'utf-8')

  sk.sendto(start_command,(LOCAL_ADDRESS,HWIL_GNSS_EMULATOR_COMMAND_PORT))
  print(f'Sent command \"start\" to HWIL_GNSS_EMULATOR at {LOCAL_ADDRESS}:{HWIL_GNSS_EMULATOR_COMMAND_PORT}. Press Ctrl-C to stop and exit')
  print(f'Server listening on {HWIL_GNSS_EMULATOR_SEND_ADDRESS}:{HWIL_GNSS_EMULATOR_SEND_PORT} for TCP data...')
  sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  sock.bind((HWIL_GNSS_EMULATOR_SEND_ADDRESS, HWIL_GNSS_EMULATOR_SEND_PORT))
  sock.listen(1)
  conn, addr = sock.accept()

  try:
    while True:
      data = conn.recv(65536)
      if not data:
          break
      print(f"{data.decode('utf-8')}")

  except KeyboardInterrupt:
    print("\nCtrl+C detected! Cleaning up and exiting safely.")
    sk.sendto(stop_command,(LOCAL_ADDRESS,HWIL_GNSS_EMULATOR_COMMAND_PORT))

  finally:
    conn.close()
    sock.close()


if __name__ == "__main__":
  main()
