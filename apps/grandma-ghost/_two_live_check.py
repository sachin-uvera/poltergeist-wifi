"""
End-to-end check of the two-ghost path through the real hub in live mode.

Sends synthetic CSI over UDP in the firmware's format, as if the boards were streaming:
  phase 1 (6 s): only the top wall (A-B) is disturbed      -> expect 1 ghost
  phase 2 (8 s): top wall AND bottom wall (C-D) disturbed  -> expect 2 ghosts
  phase 3 (8 s): only the top wall again                   -> expect back to 1 ghost

All packets come from 127.0.0.1, so the board letter is taken from the line prefix
we inject (the hub maps unknown IPs to the IP string). To make each packet count as
the right board, we send a "# board X" announcement before each board's batch.
"""
import asyncio
import json
import random
import socket
import time
import urllib.request

import websockets

# A separate port, so the real boards (which send to 5005) can't mix into the test.
# Start the hub with:  ... app.py --udp-port 5099
HUB = ("127.0.0.1", 5099)
BOARDS = "ABCD"
SUB = 64


def frame(disturbed: bool, rng: random.Random) -> str:
    """One CSI value string: 64 subcarriers as interleaved imag,real int8."""
    vals = []
    for k in range(SUB):
        base = 20 + 6 * ((k % 7) - 3) / 3
        amp = base * (1 + (rng.uniform(-0.45, 0.45) if disturbed else rng.uniform(-0.01, 0.01)))
        vals += [int(max(-127, min(127, amp * 0.6))), int(max(-127, min(127, amp * 0.8)))]
    return " ".join(map(str, vals))


def send_phase(sock, seconds: float, busy: set, rng: random.Random):
    """busy: set of frozenset pairs that are disturbed, e.g. {frozenset('AB')}."""
    end = time.time() + seconds
    ms = 0
    while time.time() < end:
        for rx in BOARDS:
            lines = [f"# board {rx} mac 00:00:00:00:00:00 ch=6 ip=127.0.0.1"]
            for tx in BOARDS:
                if tx == rx:
                    continue
                d = frozenset((rx, tx)) in busy
                lines.append(f"CSI-{tx},{ms},-60,128,{frame(d, rng)}")
            sock.sendto(("\n".join(lines) + "\n").encode(), HUB)
        ms += 20
        time.sleep(0.02)   # ~50 packets/s per link


def post(path):
    req = urllib.request.Request("http://127.0.0.1:8080" + path, data=b"{}",
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


async def watch(seconds: float, label: str, log: list):
    async with websockets.connect("ws://127.0.0.1:8765") as ws:
        end = time.time() + seconds
        while time.time() < end:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            except asyncio.TimeoutError:
                continue
            if msg["type"] == "tick":
                log.append((label, msg["room_state"], [(g["x"], g["y"]) for g in msg["ghosts"]]))


async def main():
    print("live mode ->", post("/api/live"))
    time.sleep(1.5)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rng = random.Random(1)
    log: list = []
    phases = [("one person (top wall)", 6, {frozenset("AB")}),
              ("two people (top + bottom wall)", 8, {frozenset("AB"), frozenset("CD")}),
              ("one person again (top wall)", 8, {frozenset("AB")})]
    for label, secs, busy in phases:
        await asyncio.gather(asyncio.to_thread(send_phase, sock, secs, busy, rng),
                             watch(secs, label, log))
    post("/api/stop")

    for label, _, _ in phases:
        rows = [r for r in log if r[0] == label]
        counts = [len(r[2]) for r in rows]
        last = rows[-1] if rows else None
        print(f"{label:32s} ghosts per tick {counts}")
        if last:
            print(f"{'':32s} last tick: state={last[1]} ghosts={last[2]}")


if __name__ == "__main__":
    asyncio.run(main())
