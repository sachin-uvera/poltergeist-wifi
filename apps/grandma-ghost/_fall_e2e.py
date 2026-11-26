"""
End-to-end fall test: synthetic CSI -> real hub (live mode) -> state machine -> Telegram.

Start a separate hub first, on ports that don't clash with the normal one:
    uv run --with websockets --with python-dotenv --with numpy apps/grandma-ghost/app.py \
        --port 8081 --ws-port 8766 --udp-port 5099

Then run this. It streams, as if from the four boards:
  3 s   someone walks across the top wall (A-B disturbed)
  1.5 s a sharp burst on several links (the fall)
  then stillness until the hub confirms the fall (about 10 s + 15 s)
and prints every event the hub reports. A confirmed fall makes the hub send the
real Telegram alert.
"""
import asyncio
import json
import random
import socket
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _two_live_check import send_phase   # same packet format as the live check

import websockets

HTTP = "http://127.0.0.1:8081"
WS = "ws://127.0.0.1:8766"
import _two_live_check as tl
tl.HUB = ("127.0.0.1", 5099)


def post(path):
    req = urllib.request.Request(HTTP + path, data=b"{}", headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


async def watch(stop: asyncio.Event, log: list):
    async with websockets.connect(WS) as ws:
        t0 = time.time()
        while not stop.is_set():
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
            except asyncio.TimeoutError:
                continue
            if msg["type"] == "event":
                e = msg["event"]
                text = e["text"].encode("ascii", "ignore").decode().strip()
                log.append(e["kind"])
                print(f"  +{time.time() - t0:5.1f}s  {e['kind']:14s} {text}", flush=True)
                if e["kind"] == "fall":
                    stop.set()


async def main():
    print("live mode ->", post("/api/live"))
    time.sleep(1.5)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rng = random.Random(7)
    stop = asyncio.Event()
    log: list = []
    watcher = asyncio.create_task(watch(stop, log))

    walk = {frozenset("AB")}
    fall = {frozenset(p) for p in ("AB", "AD", "BC", "BD", "AC", "CD")}
    await asyncio.to_thread(send_phase, sock, 3.0, walk, rng)
    await asyncio.to_thread(send_phase, sock, 1.5, fall, rng)

    # Stillness: keep streaming quiet packets until the fall is confirmed (max 40 s)
    end = time.time() + 40
    while not stop.is_set() and time.time() < end:
        await asyncio.to_thread(send_phase, sock, 1.0, set(), rng)
    stop.set()
    await watcher
    post("/api/stop")
    print("events:", log)
    print("RESULT:", "fall confirmed -> Telegram alert should be on your phone" if "fall" in log
          else "no fall confirmed")


asyncio.run(main())
