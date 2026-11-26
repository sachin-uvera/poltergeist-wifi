"""Connect to the running hub, watch the WebSocket for a while, and summarise what the UI would see."""
import asyncio
import json
import sys

import websockets


async def main(seconds: int):
    counts: dict[str, int] = {}
    events: list[str] = []
    states: list[str] = []
    leaked: list[str] = []
    positions: list = []
    async with websockets.connect("ws://127.0.0.1:8765") as ws:
        end = asyncio.get_event_loop().time() + seconds
        while asyncio.get_event_loop().time() < end:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                continue
            msg = json.loads(raw)
            counts[msg["type"]] = counts.get(msg["type"], 0) + 1
            if msg["type"] == "event":
                events.append(msg["event"]["text"])
            if msg.get("room_state") and (not states or states[-1] != msg["room_state"]):
                states.append(msg["room_state"])
            if msg["type"] == "tick":
                pos = msg.get("position")
                positions.append(None if not pos else (pos["x"], pos["y"]))
            # privacy check: nothing but scores/states should be here
            if any(k in msg for k in ("values", "csi", "raw")):
                leaked.append(msg["type"])
    print("message counts:", counts)
    print("room_state sequence:", " -> ".join(states))
    print("events:")
    for e in events:
        print("  ", e)
    print("ghost position every 4th tick (x, y; None = no ghost):")
    print("  ", positions[::4])
    print("raw-CSI keys leaked:", leaked or "none")


asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 60))
