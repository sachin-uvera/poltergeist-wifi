"""
apps/grandma-ghost/app.py – Grandma Ghost web app hub.

Serves the browser UI over HTTP and streams real-time updates via WebSocket.
Runs the core pipeline + state machine in a background thread.

Run:
    uv run --with websockets --with python-dotenv --with numpy apps/grandma-ghost/app.py
    uv run --with websockets --with python-dotenv --with numpy apps/grandma-ghost/app.py --replay fall
    uv run --with websockets --with python-dotenv --with numpy apps/grandma-ghost/app.py --live

Privacy: raw CSI never leaves this process. Only scores, states and events
reach the browser via WebSocket.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# ── Repo root on sys.path so core/ imports work ───────────────────────────────
_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from core.ingest import iter_csv, parse_line
from core.pipeline import RoomPipeline
from core.state import Event, StateMachine

sys.path.insert(0, str(Path(__file__).parent))
import position    # apps/grandma-ghost/position.py
import tombstones  # apps/grandma-ghost/tombstones.py

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("grandma-ghost")

_RECORDINGS = _ROOT / "recordings"
_STATIC     = Path(__file__).parent / "static"
_UDP_PORT   = 5005
_IMAGES     = {"/ghost.png": "ghost.png", "/ghost-red.png": "ghost-red.png"}

# Board IP → letter, learned from boot/heartbeat lines (matches firmware)
_BOARD_IPS: dict[str, str] = {
    "192.168.29.87":  "A",
    "192.168.29.37":  "B",
    "192.168.29.137": "C",
    "192.168.29.249": "D",
}

# ── Shared state (written by pipeline thread, read by HTTP/WebSocket) ─────────
_lock = threading.Lock()
_state: dict[str, Any] = {
    "mode":            "idle",   # "live" | "replay" | "idle"
    "recording":       "",
    "room_state":      "empty",
    "active_links":    [],
    "scores":          {},       # {link_key: float}; scores only, never raw CSI
    "ghosts":          [],       # [{"x","y"}] room coordinates 0..1, one per person (max 2)
    "events":          [],       # tombstones, newest first
    "calibrating":     False,
    "calib_secs_left": 0,
    "calibrated":      False,
}

# Only one pipeline runs at a time. Starting a new one bumps the id and the old
# loop exits on its next iteration.
_run_id = 0

# Baselines from "Exorcise the room". Pipelines pick up a new version on the next tick.
_baselines: dict[str, float] = {}
_baseline_version = 0

# While calibrating, the live loop feeds this extra RoomPipeline.
_calib_room: RoomPipeline | None = None

# The running state machine and ghost tracker. "Acknowledge" resets them from the
# HTTP thread, even after a replay has finished, so they are shared and lock-guarded.
_sm_lock = threading.RLock()
_sm: StateMachine | None = None
_tracker = position.MultiTracker()

_queue: asyncio.Queue[dict] | None = None
_loop: asyncio.AbstractEventLoop | None = None
_clients: set[Any] = set()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _post(msg: dict) -> None:
    """Thread-safe post to the asyncio broadcaster."""
    if _loop is not None and _queue is not None and not _loop.is_closed():
        _loop.call_soon_threadsafe(_queue.put_nowait, msg)


def _set_mode(mode: str, recording: str = "") -> None:
    with _lock:
        _state["mode"] = mode
        _state["recording"] = recording
    _post({"type": "mode", "mode": mode, "recording": recording})


def _new_run() -> int:
    global _run_id
    with _lock:
        _run_id += 1
        return _run_id


def _is_current(run_id: int) -> bool:
    return run_id == _run_id


def _empty_baselines() -> dict[str, float]:
    """Baseline from the recorded empty room (used for replay only)."""
    empties = sorted(_RECORDINGS.glob("empty_*.csv"))
    if not empties:
        log.warning("No empty recording found; replaying without a baseline.")
        return {}
    room = RoomPipeline()
    for p in iter_csv(empties[-1]):
        room.push(p)
    return room.scores()


def _publish(room: RoomPipeline, sm: StateMachine, baselines: dict[str, float]) -> None:
    raw = room.scores()
    scores = {k: round(v, 5) for k, v in raw.items()}
    active = sorted(room.active_links())
    excess = {k: v - baselines.get(k, 0.0) for k, v in raw.items()}

    with _sm_lock:
        ghosts = position.place_ghosts(_tracker, sm.state.value, excess)

    with _lock:
        _state["scores"] = scores
        _state["active_links"] = active
        _state["room_state"] = sm.state.value
        _state["ghosts"] = ghosts
    _post({"type": "tick", "scores": scores, "active_links": active,
           "room_state": sm.state.value, "ghosts": ghosts})


def _on_event(event: Event) -> None:
    """Called by the StateMachine on every state transition."""
    now  = datetime.now()
    ts   = now.strftime("%H:%M")
    d = tombstones.describe(event)
    label = d["label"]

    tombstone = {"icon": d["icon"], "text": f"{d['text']}, {ts}", "kind": event.kind,
                 "ts": ts, "note": event.note}
    with _lock:
        _state["room_state"] = event.state
        _state["events"].insert(0, tombstone)
        del _state["events"][100:]

    _post({"type": "event", "event": tombstone, "room_state": event.state})

    if event.kind in ("fall", "inactive"):
        msg = f"Poltergeist: {label}, {now.strftime('%Y-%m-%d %H:%M:%S')}"
        threading.Thread(target=_send_telegram, args=(msg,), daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# Pipelines
# ─────────────────────────────────────────────────────────────────────────────

def _run_replay(path: Path, run_id: int) -> None:
    """Replay a recording at real speed through the same pipeline as live data."""
    log.info("Replay: %s", path.name)
    with _lock:
        _state["events"] = []
        _state["room_state"] = "empty"
        _state["ghosts"] = []
    _set_mode("replay", path.name)

    global _sm
    baselines = _empty_baselines()
    room = RoomPipeline()
    room.set_baseline(baselines)
    sm = StateMachine()
    sm.on_event(_on_event)
    with _sm_lock:
        _sm = sm
        _tracker.reset()

    max_gap_s = 2.0
    prev_wall_ms: int | None = None
    prev_mono = time.monotonic()
    last_pub = 0.0

    for packet in iter_csv(path):
        if not _is_current(run_id):
            return
        if prev_wall_ms is not None and packet.wall_ms > 0:
            gap = min((packet.wall_ms - prev_wall_ms) / 1000.0, max_gap_s)
            sleep = gap - (time.monotonic() - prev_mono)
            if sleep > 0:
                time.sleep(sleep)

        room.push(packet)
        with _sm_lock:
            sm.push(packet.wall_ms, room.active_links())
        prev_wall_ms = packet.wall_ms
        prev_mono = time.monotonic()

        # Publish about once a second (the UI updates every second)
        if prev_mono - last_pub >= 1.0:
            _publish(room, sm, baselines)
            last_pub = prev_mono

    _publish(room, sm, baselines)
    if _is_current(run_id):
        log.info("Replay finished: %s (final state %s)", path.name, sm.state.value)
        _set_mode("idle", path.name)   # remember it so the UI can offer "Restart replay"


def _run_live(run_id: int) -> None:
    """Listen for UDP packets from the boards and feed the pipeline."""
    global _calib_room, _sm
    log.info("Live mode: listening on UDP :%d", _UDP_PORT)
    with _lock:
        _state["events"] = []
        _state["room_state"] = "empty"
        _state["ghosts"] = []
    _set_mode("live")

    room = RoomPipeline()
    sm = StateMachine()
    sm.on_event(_on_event)
    with _sm_lock:
        _sm = sm
        _tracker.reset()
    seen_version = -1

    try:
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        udp.bind(("0.0.0.0", _UDP_PORT))
    except OSError as exc:
        log.error("Cannot listen on UDP %d: %s", _UDP_PORT, exc)
        _set_mode("idle")
        return
    udp.settimeout(0.5)
    last_pub = 0.0

    try:
        while _is_current(run_id):
            if seen_version != _baseline_version:
                baselines = dict(_baselines)
                room.set_baseline(baselines)
                seen_version = _baseline_version

            try:
                data, (ip, _) = udp.recvfrom(65535)
            except socket.timeout:
                data = b""

            if data:
                board = _BOARD_IPS.get(ip, ip)
                for line in data.decode(errors="replace").splitlines():
                    if line.startswith("# board "):
                        parts = line.split()
                        if len(parts) >= 3:
                            board = _BOARD_IPS[ip] = parts[2]
                    elif line.startswith("# heartbeat board="):
                        board = _BOARD_IPS[ip] = line.split()[2][6:]
                    packet = parse_line(board, line)
                    if packet is None:
                        continue
                    packet.wall_ms = int(time.time() * 1000)
                    room.push(packet)
                    calib = _calib_room
                    if calib is not None:
                        calib.push(packet)
                    with _sm_lock:
                        sm.push(packet.wall_ms, room.active_links())

            now = time.monotonic()
            if now - last_pub >= 1.0:
                _publish(room, sm, baselines)
                last_pub = now
    finally:
        udp.close()
        if _is_current(run_id):
            _set_mode("idle")


def _run_calibration() -> None:
    """Record an empty-room baseline from the live feed, then install it."""
    global _calib_room, _baselines, _baseline_version
    with open(_ROOT / "core" / "config.toml", "rb") as fh:
        secs = int(tomllib.load(fh)["pipeline"].get("baseline_secs", 60))

    log.info("Calibration: %d s", secs)
    room = RoomPipeline()
    with _lock:
        _state["calibrating"] = True
        _state["calib_secs_left"] = secs
    _calib_room = room

    deadline = time.monotonic() + secs
    while time.monotonic() < deadline:
        left = max(0, int(deadline - time.monotonic()))
        with _lock:
            _state["calib_secs_left"] = left
        _post({"type": "calibrating", "secs_left": left})
        time.sleep(0.5)

    _calib_room = None
    baselines = room.scores()
    with _lock:
        _baselines = baselines
        _baseline_version += 1
        _state["calibrating"] = False
        _state["calib_secs_left"] = 0
        _state["calibrated"] = bool(baselines)
    _post({"type": "calibrated", "links": len(baselines)})
    log.info("Calibration done: %d links", len(baselines))


_ACKABLE = ("possible_fall", "fall", "inactive_too_long")


def _acknowledge() -> bool:
    """Family member acknowledged the alert: reset the state machine to 'empty'
    and clear the ghost. Monitoring carries on from a clean slate."""
    with _sm_lock:
        if _sm is None or _sm.state.value not in _ACKABLE:
            return False
        _sm.reset()            # emits a "reset" event, which _on_event records
        _tracker.reset()
    with _lock:
        _state["room_state"] = "empty"
        _state["ghosts"] = []
        _state["active_links"] = []
        scores = dict(_state["scores"])
    _post({"type": "tick", "scores": scores, "active_links": [],
           "room_state": "empty", "ghosts": []})
    log.info("Alert acknowledged")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Telegram
# ─────────────────────────────────────────────────────────────────────────────

def _send_telegram(message: str) -> bool:
    """Send one message to the family chat. Returns True on success.

    Never raises: a network problem must not stop the hub. The token is part of
    the URL, so errors are logged by Telegram's description, never by URL.
    """
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        log.warning("Telegram not configured (set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env). "
                    "Would have sent: %s", message)
        return False
    url  = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, method="POST"),
                                    timeout=10) as resp:
            log.info("Telegram sent (HTTP %d): %s", resp.status, message)
            return True
    except urllib.error.HTTPError as exc:
        # Telegram explains the problem in the body, e.g. "Unauthorized" or "chat not found"
        try:
            desc = json.loads(exc.read()).get("description", "")
        except Exception:
            desc = ""
        log.warning("Telegram rejected the message (HTTP %d): %s", exc.code, desc or "no reason given")
    except Exception as exc:  # DNS, timeout, no internet
        log.warning("Telegram send failed: %s", type(exc).__name__)
    return False


# ─────────────────────────────────────────────────────────────────────────────
# HTTP server (static UI + small control API)
# ─────────────────────────────────────────────────────────────────────────────

def _recordings() -> list[dict[str, str]]:
    return [{"filename": f.name, "label": f.stem.rsplit("_", 2)[0]}
            for f in sorted(_RECORDINGS.glob("*.csv"))]


def _snapshot() -> dict[str, Any]:
    with _lock:
        return dict(_state)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._file(_STATIC / "index.html", "text/html; charset=utf-8")
        elif path in _IMAGES:            # fixed whitelist, never a path from the request
            self._file(_STATIC / _IMAGES[path], "image/png")
        elif path == "/api/state":
            self._json({**_snapshot(), "recordings": _recordings()})
        elif path == "/api/recordings":
            self._json(_recordings())
        else:
            self.send_error(404)

    def do_POST(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(length)) if length else {}
        except json.JSONDecodeError:
            self._json({"error": "invalid JSON"}, 400)
            return

        if path == "/api/replay":
            name = str(body.get("recording", ""))
            # Only match files inside recordings/ by label or filename prefix
            matches = [f for f in sorted(_RECORDINGS.glob("*.csv"))
                       if f.name == name or f.name.startswith(name + "_")]
            if not name or not matches:
                self._json({"error": f"recording not found: {name}"}, 404)
                return
            rid = _new_run()
            threading.Thread(target=_run_replay, args=(matches[-1], rid), daemon=True).start()
            self._json({"started": matches[-1].name})

        elif path == "/api/live":
            rid = _new_run()
            threading.Thread(target=_run_live, args=(rid,), daemon=True).start()
            self._json({"started": True})

        elif path == "/api/acknowledge":
            if not _acknowledge():
                self._json({"error": "nothing to acknowledge"}, 409)
                return
            self._json({"acknowledged": True})

        elif path == "/api/stop":
            _new_run()
            _set_mode("idle")
            self._json({"stopped": True})

        elif path == "/api/calibrate":
            if _snapshot()["mode"] != "live":
                self._json({"error": "Calibration needs live mode (boards streaming). "
                                     "Switch the toggle to Live first."}, 409)
                return
            if _snapshot()["calibrating"]:
                self._json({"error": "already calibrating"}, 409)
                return
            threading.Thread(target=_run_calibration, daemon=True).start()
            self._json({"started": True})

        else:
            self.send_error(404)

    def _file(self, path: Path, content_type: str):
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj: Any, code: int = 200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket (asyncio)
# ─────────────────────────────────────────────────────────────────────────────

async def _broadcaster():
    assert _queue is not None
    while True:
        msg = await _queue.get()
        if not _clients:
            continue
        data = json.dumps(msg)
        for ws in list(_clients):
            try:
                await ws.send(data)
            except Exception:
                _clients.discard(ws)


async def _ws_handler(websocket):
    _clients.add(websocket)
    try:
        await websocket.send(json.dumps({"type": "init", **_snapshot(),
                                         "recordings": _recordings()}))
        async for _ in websocket:
            pass
    except Exception:
        pass
    finally:
        _clients.discard(websocket)


async def _serve_ws(host: str, port: int):
    import websockets
    global _loop, _queue
    _loop = asyncio.get_running_loop()
    _queue = asyncio.Queue()
    async with websockets.serve(_ws_handler, host, port):
        await _broadcaster()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Grandma Ghost hub")
    parser.add_argument("--port",    type=int, default=8080)
    parser.add_argument("--ws-port", type=int, default=8765)
    parser.add_argument("--host",    default="127.0.0.1",
                        help="bind address (default localhost; use 0.0.0.0 to share on the LAN)")
    parser.add_argument("--replay",  default="", help="start replaying this label/filename")
    parser.add_argument("--live",    action="store_true", help="start in live UDP mode")
    parser.add_argument("--udp-port", type=int, default=5005,
                        help="UDP port the boards send to (default 5005, as in the firmware)")
    args = parser.parse_args()

    global _UDP_PORT
    _UDP_PORT = args.udp_port

    httpd = ThreadingHTTPServer((args.host, args.port), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    log.info("HTTP  -> http://localhost:%d", args.port)
    log.info("WS    -> ws://localhost:%d", args.ws_port)

    def _autostart():
        time.sleep(1.0)   # let the WebSocket loop come up first
        if args.replay:
            matches = [f for f in sorted(_RECORDINGS.glob("*.csv"))
                       if f.name == args.replay or f.name.startswith(args.replay + "_")]
            if matches:
                rid = _new_run()
                _run_replay(matches[-1], rid)
            else:
                log.warning("Recording not found: %s", args.replay)
        elif args.live:
            _run_live(_new_run())

    if args.replay or args.live:
        threading.Thread(target=_autostart, daemon=True).start()

    asyncio.run(_serve_ws(args.host, args.ws_port))


if __name__ == "__main__":
    main()
