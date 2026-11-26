"""Replay the fall, acknowledge the alert, and check what the browser would receive."""
import asyncio
import json
import urllib.error
import urllib.request

import websockets

BASE = "http://127.0.0.1:8080"


def post(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


async def main():
    print("ack with nothing to acknowledge ->", post("/api/acknowledge"))
    print("start replay ->", post("/api/replay", {"recording": "fall"}))

    async with websockets.connect("ws://127.0.0.1:8765") as ws:
        # wait for the alert
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=90))
            if msg.get("room_state") == "possible_fall" and msg["type"] == "tick":
                print("alert reached; ghost at", msg["position"], "state", msg["room_state"])
                break

        status, body = post("/api/acknowledge")
        print("acknowledge ->", status, body)

        seen = []
        for _ in range(6):
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if msg["type"] == "event":
                seen.append(("event", msg["event"]["kind"], msg["event"]["text"].encode("ascii", "replace").decode()))
            elif msg["type"] == "tick":
                seen.append(("tick", msg["room_state"], msg["position"]))
        for s in seen:
            print("  after ack:", s)

    print("ack again (already cleared) ->", post("/api/acknowledge"))
    print("restart replay ->", post("/api/replay", {"recording": "fall_20261125_070405.csv"}))


asyncio.run(main())
