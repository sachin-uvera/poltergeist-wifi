"""Listen on the hub's UDP port and show who hears whom: receiving board IP -> sending board letter.

    uv run python apps/grandma-ghost/_udp_matrix.py [seconds]

Receive only. Counts lines by their "CSI-<tx>" prefix and never reads or prints CSI values.
Shares the port with a running hub (SO_REUSEADDR), so it does not disturb it.
"""
import collections
import socket
import sys
import time

secs = int(sys.argv[1]) if len(sys.argv) > 1 else 8
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("0.0.0.0", 5005))
s.settimeout(0.5)

heard: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
packets = collections.Counter()
sizes: dict[str, list[int]] = collections.defaultdict(list)
board_of: dict[str, str] = {}
end = time.time() + secs
while time.time() < end:
    try:
        data, (ip, _) = s.recvfrom(65535)
    except socket.timeout:
        continue
    packets[ip] += 1
    sizes[ip].append(len(data))
    for line in data.decode(errors="replace").splitlines():
        if line.startswith("CSI-"):
            heard[ip][line[4:5]] += 1
        elif line.startswith("# board "):
            board_of[ip] = line.split()[2]
        elif line.startswith("# heartbeat board="):
            board_of[ip] = line.split()[1][6:]

print(f"{'receiver':<16} {'board':<6} {'datagrams/s':>11} {'avg bytes':>9}   lines per second, by sender")
for ip in sorted(packets):
    per = {k: round(v / secs, 1) for k, v in sorted(heard[ip].items())}
    avg = sum(sizes[ip]) // len(sizes[ip])
    print(f"{ip:<16} {board_of.get(ip, '?'):<6} {packets[ip] / secs:>11.1f} {avg:>9}   {per}")
