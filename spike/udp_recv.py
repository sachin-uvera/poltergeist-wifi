"""
Minimal UDP receiver for csi_udp firmware.
Prints every line received, prefixed with which board sent it (from the # boot line).
Run:  uv run python spike/udp_recv.py
"""
import socket, sys

HOST = "0.0.0.0"
PORT = 5005

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((HOST, PORT))
print(f"# listening on UDP {HOST}:{PORT}  (Ctrl-C to stop)", flush=True)

board_ips: dict[str, str] = {}   # ip -> board letter

try:
    while True:
        data, addr = sock.recvfrom(65535)
        ip = addr[0]
        lines = data.decode(errors="replace").splitlines()
        for line in lines:
            # pick up boot / heartbeat lines to map ip -> board letter
            if line.startswith("# board "):
                parts = line.split()
                if len(parts) >= 3:
                    board_ips[ip] = parts[2]
            tag = board_ips.get(ip, ip)
            print(f"[{tag}] {line}", flush=True)
except KeyboardInterrupt:
    print("\n# stopped")
    sock.close()
