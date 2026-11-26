"""Ask the running hub which board-to-board links are receiving data (read-only).

    uv run python apps/grandma-ghost/_hub_links.py [seconds]

Polls /api/state twice a second and counts how often each link's score changes. A link whose
score never changes is getting no packets. Does not touch UDP, so it cannot steal the hub's data.
"""
import json
import sys
import time
import urllib.request

secs = int(sys.argv[1]) if len(sys.argv) > 1 else 15


def state():
    with urllib.request.urlopen("http://127.0.0.1:8080/api/state", timeout=5) as r:
        return json.loads(r.read())


prev = state()["scores"]
changes = {k: 0 for k in prev}
samples = 0
end = time.time() + secs
while time.time() < end:
    time.sleep(0.5)
    s = state()
    samples += 1
    for k, v in s["scores"].items():
        changes.setdefault(k, 0)
        if prev.get(k) != v:
            changes[k] += 1
    prev = s["scores"]

print(f"mode={s['mode']} state={s['room_state']} calibrated={s['calibrated']}  ({samples} samples)")
boards = "ABCD"
print("receiver \\ sender  " + "  ".join(f"{b:>5}" for b in boards))
for rx in boards:
    row = []
    for tx in boards:
        if rx == tx:
            row.append("    -")
            continue
        n = changes.get(f"{rx}/CSI-{tx}")
        row.append("  n/a" if n is None else f"{n:>5}")
    print(f"{rx:>17}  " + "  ".join(row))
dead = [k for k, n in changes.items() if n == 0]
missing = [f"{r}/CSI-{t}" for r in boards for t in boards if r != t and f"{r}/CSI-{t}" not in changes]
print("links with no new data:", dead or "none")
print("links never seen:", missing or "none")
