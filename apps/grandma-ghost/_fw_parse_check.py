"""Check the hub's parser and pipeline on live packets, per receiving board.

    uv run --with numpy python apps/grandma-ghost/_fw_parse_check.py [seconds]

Receive only (shares UDP 5005 with a running hub). Prints counts and motion scores, never CSI values.
"""
import collections
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.ingest import parse_line
from core.pipeline import RoomPipeline

secs = int(sys.argv[1]) if len(sys.argv) > 1 else 15
IPS = {"192.168.29.87": "A", "192.168.29.37": "B", "192.168.29.137": "C", "192.168.29.249": "D"}

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("0.0.0.0", 5005))
s.settimeout(0.5)

room = RoomPipeline()
lines = collections.Counter()
parsed = collections.Counter()
lens = collections.defaultdict(set)
end = time.time() + secs
while time.time() < end:
    try:
        data, (ip, _) = s.recvfrom(65535)
    except socket.timeout:
        continue
    rx = IPS.get(ip, ip)
    for line in data.decode(errors="replace").splitlines():
        if not line.startswith("CSI-"):
            continue
        lines[rx] += 1
        pk = parse_line(rx, line)
        if pk is not None:
            pk.wall_ms = int(time.time() * 1000)
            parsed[rx] += 1
            lens[rx].add(pk.values.size)
            room.push(pk)

print(f"{'receiver':<9} {'CSI lines':>9} {'parsed':>7} {'values/line':>12}")
for rx in sorted(lines):
    print(f"{rx:<9} {lines[rx]:>9} {parsed[rx]:>7} {sorted(lens[rx])!s:>12}")
print("\nsmoothed motion score per link (room not being walked through):")
scores = room.scores()
for rx in sorted({k[0] for k in scores}):
    row = {k: round(v, 3) for k, v in sorted(scores.items()) if k.startswith(rx + "/")}
    print(f"  {rx}: {row}")
