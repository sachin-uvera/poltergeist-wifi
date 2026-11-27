"""
core/mcp_server.py – "spirit box" MCP server for Poltergeist.

Exposes five tools to Kiro chat:
  get_live_stats      – motion score per link, current state, active links
  list_recordings     – all CSVs in recordings/ with label and duration
  replay              – replay a named recording and return every event it produced
  get_thresholds      – read [zones] and [state] from config.toml
  set_thresholds      – write [zones] and/or [state] keys, then reload config

Privacy: motion scores and events reach MCP. Raw CSI never does.

Run (stdio, for Kiro MCP):
    uv run --with "mcp[cli]" --with numpy python -m core.mcp_server

The server keeps a single shared RoomPipeline + StateMachine instance.
In live mode the hub feeds packets in; in replay mode recordings do the same.
Both paths are identical from the state machine's point of view.
"""
from __future__ import annotations

import csv
import json
import os
import re
import threading
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

# ── Repo root (two levels up from this file) ──────────────────────────────────
_ROOT = Path(__file__).parent.parent
_RECORDINGS = _ROOT / "recordings"
_CONFIG     = Path(__file__).parent / "config.toml"

# The Grandma Ghost hub that owns the live boards. This server runs in its own process
# (Kiro starts it), so it cannot see the hub's memory; it asks the hub's local HTTP API,
# which serves scores and states only, never raw CSI.
_HUB_URL = os.environ.get("GG_HUB_URL", "http://127.0.0.1:8080").rstrip("/")


def _hub(path: str, post: bool = False, timeout: float = 2.0) -> dict | None:
    """Call the running hub. Returns None if no hub is running."""
    req = urllib.request.Request(_HUB_URL + path, data=b"{}" if post else None,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if post else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None

# ── Lazy imports from core (avoid circular at module level) ───────────────────
def _core():
    from core.pipeline import RoomPipeline, reload_config
    from core.state import StateMachine, Event
    from core.ingest import iter_csv
    from core.replay import replay as _replay_fn
    return RoomPipeline, reload_config, StateMachine, Event, iter_csv, _replay_fn

# ── Shared live state (guarded by _lock) ─────────────────────────────────────
_lock        = threading.Lock()
_room        : Any = None   # RoomPipeline | None
_sm          : Any = None   # StateMachine | None
_last_scores : dict[str, float] = {}

def _ensure_live() -> tuple[Any, Any]:
    """Return (room, sm), initialising them once if needed."""
    global _room, _sm
    RoomPipeline, reload_config, StateMachine, *_ = _core()
    with _lock:
        if _room is None:
            _room = RoomPipeline()
            _sm   = StateMachine()
        return _room, _sm

# ── MCP server ────────────────────────────────────────────────────────────────
server = MCPServer(
    name="spirit-box",
    description=(
        "Poltergeist spirit box: live CSI stats, recording replay, "
        "and threshold tuning for the Grandma Ghost sensing pipeline."
    ),
)

# ─────────────────────────────────────────────────────────────────────────────
# Tool 1: get_live_stats
# ─────────────────────────────────────────────────────────────────────────────

@server.tool(
    name="get_live_stats",
    description=(
        "Return the motion score per link, the room state, the active links and the ghost "
        "positions. Reads the running Grandma Ghost hub (live boards or its replay) over its "
        "local API; if no hub is running, returns the result of this server's last replay() "
        "call. The 'source' field says which. Scores only, never raw CSI."
    ),
)
def get_live_stats() -> dict[str, Any]:
    hub = _hub("/api/state")
    if hub is not None:
        return {
            "source":       f"hub ({hub.get('mode')})",
            "state":        hub.get("room_state"),
            "active_links": hub.get("active_links", []),
            "scores":       {k: round(v, 5) for k, v in sorted(hub.get("scores", {}).items())},
            "ghosts":       hub.get("ghosts", []),
            "calibrated":   hub.get("calibrated"),
            "recent_events": [e.get("text") for e in hub.get("events", [])[:5]],
        }

    room, sm = _ensure_live()
    with _lock:
        scores = room.scores()
        active = sorted(room.active_links())
        state = sm.state.value
    return {
        "source":       "last replay() in this server (no hub running at " + _HUB_URL + ")",
        "state":        state,
        "active_links": active,
        "scores":       {k: round(v, 5) for k, v in sorted(scores.items())},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tool 2: list_recordings
# ─────────────────────────────────────────────────────────────────────────────

@server.tool(
    name="list_recordings",
    description=(
        "List all CSV files in recordings/. "
        "Returns each file's name, label (the part before the first underscore+date), "
        "row count, and wall-clock duration in seconds."
    ),
)
def list_recordings() -> list[dict[str, Any]]:
    results = []
    for path in sorted(_RECORDINGS.glob("*.csv")):
        label = path.stem.rsplit("_", 2)[0]   # "fall_20261125_070405" → "fall"
        rows  = 0
        first_ms: int | None = None
        last_ms:  int | None = None
        try:
            with open(path, newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    rows += 1
                    try:
                        ms = int(row["wall_time_ms"])
                        if first_ms is None:
                            first_ms = ms
                        last_ms = ms
                    except (KeyError, ValueError):
                        pass
        except OSError:
            continue

        duration_s = round((last_ms - first_ms) / 1000, 1) if (first_ms and last_ms) else None
        results.append({
            "filename":   path.name,
            "label":      label,
            "rows":       rows,
            "duration_s": duration_s,
        })
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Tool 3: replay
# ─────────────────────────────────────────────────────────────────────────────

@server.tool(
    name="replay",
    description=(
        "Replay a named recording (filename or label) through the pipeline and "
        "state machine. Uses the empty recording as the baseline calibration. "
        "Returns every state-transition event the recording produced. "
        "Also updates the shared live-stats state so get_live_stats() reflects "
        "the end of the replay."
    ),
)
def replay(recording: str) -> dict[str, Any]:
    """
    Parameters
    ----------
    recording : str
        Either a full filename (e.g. "fall_20261125_070405.csv") or a label
        (e.g. "fall"). When a label is given, the most recent matching file is used.
    """
    global _room, _sm

    RoomPipeline, reload_config, StateMachine, Event, iter_csv, _replay_fn = _core()

    # Resolve path
    path = _resolve_recording(recording)

    # Build baselines from the empty recording
    baselines = _build_baselines(iter_csv)

    # Fresh pipeline + state machine for this replay
    room = RoomPipeline()
    room.set_baseline(baselines)
    sm   = StateMachine()
    events: list[dict[str, Any]] = []
    sm.on_event(lambda e: events.append({
        "kind":         e.kind,
        "state":        e.state,
        "wall_ms":      e.wall_ms,
        "active_links": e.active_links,
        "note":         e.note,
    }))

    packets_delivered = 0
    for packet in iter_csv(path):
        room.push(packet)
        sm.push(packet.wall_ms, room.active_links())
        packets_delivered += 1

    # Update the shared live state so get_live_stats() reflects this replay
    with _lock:
        _room = room
        _sm   = sm

    return {
        "recording":          path.name,
        "packets_delivered":  packets_delivered,
        "final_state":        sm.state.value,
        "events":             events,
        "event_summary":      _summarise(events),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tool 4: get_thresholds
# ─────────────────────────────────────────────────────────────────────────────

@server.tool(
    name="get_thresholds",
    description=(
        "Read the current detection thresholds from core/config.toml. "
        "Returns the [zones] and [state] sections as a flat dict."
    ),
)
def get_thresholds() -> dict[str, Any]:
    with open(_CONFIG, "rb") as fh:
        cfg = tomllib.load(fh)
    return {
        "zones": cfg.get("zones", {}),
        "state": cfg.get("state", {}),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tool 5: set_thresholds
# ─────────────────────────────────────────────────────────────────────────────

@server.tool(
    name="set_thresholds",
    description=(
        "Write one or more threshold values to core/config.toml and immediately "
        "reload the pipeline config so changes take effect without a restart. "
        "Pass a flat dict of key=value pairs; keys must exist in [zones] or [state]. "
        "Example: {\"motion_threshold\": 0.15, \"fall_still_secs\": 12.0}"
    ),
)
def set_thresholds(updates: dict[str, Any]) -> dict[str, Any]:
    """
    Parameters
    ----------
    updates : dict
        Keys from [zones] or [state] in config.toml, with new values.
        Unknown keys are rejected.
    """
    _, reload_config, *_ = _core()

    with open(_CONFIG, "rb") as fh:
        cfg = tomllib.load(fh)

    section_of = {k: "zones" for k in cfg.get("zones", {})}
    section_of.update({k: "state" for k in cfg.get("state", {})})

    rejected = [k for k in updates if k not in section_of]
    if rejected:
        return {
            "status":  "error",
            "message": f"Unknown keys (not in [zones] or [state]): {rejected}",
            "allowed": sorted(section_of),
        }

    # Every value must be a positive number. Keys that are whole numbers (for example
    # fall_links_min) stay whole numbers.
    new_text: dict[str, str] = {}
    for key, value in updates.items():
        old = cfg[section_of[key]][key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            return {"status": "error", "message": f"{key} must be a positive number, got {value!r}"}
        if isinstance(old, int) and not isinstance(old, bool):
            if float(value) != int(value):
                return {"status": "error", "message": f"{key} must be a whole number, got {value!r}"}
            new_text[key] = str(int(value))
        else:
            new_text[key] = repr(float(value))

    # bytes in, bytes out: read_text/write_text would turn the file's line endings into
    # Windows ones on Windows, changing every line
    text = _CONFIG.read_bytes().decode("utf-8")
    text, changed = _replace_values(text, {k: (section_of[k], v) for k, v in new_text.items()})
    missing = sorted(set(new_text) - changed)
    if missing:
        return {"status": "error", "message": f"Could not find these lines in config.toml: {missing}"}

    tmp = _CONFIG.with_suffix(".toml.tmp")
    tmp.write_bytes(text.encode("utf-8"))
    with open(tmp, "rb") as fh:
        check = tomllib.load(fh)       # never leave a broken file behind
    for key, value in new_text.items():
        assert str(check[section_of[key]][key]) == str(tomllib.loads(f"x = {value}")["x"])
    tmp.replace(_CONFIG)

    reload_config()                    # this server: affects replay()
    hub = _hub("/api/reload-config", post=True)   # the running hub: affects live detection

    return {
        "status":  "ok",
        "applied": {k: check[section_of[k]][k] for k in new_text},
        "running_hub": ("reloaded" if hub and hub.get("reloaded")
                        else f"no hub reachable at {_HUB_URL}; restart the hub to apply"),
        "config":  {"zones": check["zones"], "state": check["state"]},
    }


def _replace_values(text: str, updates: dict[str, tuple[str, str]]) -> tuple[str, set[str]]:
    """Replace `key = value` lines inside their [section], keeping spacing and comments."""
    out, done, section = [], set(), None
    for line in text.splitlines(keepends=True):
        head = re.match(r"\s*\[([^\]]+)\]", line)
        if head:
            section = head.group(1).strip()
        m = re.match(r"^(\s*)([A-Za-z_][\w-]*)(\s*=\s*)([^#\r\n]*?)(\s*(#.*)?)(\r?\n?)$", line)
        if m and m.group(2) in updates and updates[m.group(2)][0] == section:
            key = m.group(2)
            line = m.group(1) + key + m.group(3) + updates[key][1] + m.group(5) + m.group(7)
            done.add(key)
        out.append(line)
    return "".join(out), done


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_recording(name: str) -> Path:
    """Return a Path for a filename or label. Raises ValueError if not found."""
    # Exact filename match
    exact = _RECORDINGS / name
    if not exact.suffix:
        exact = _RECORDINGS / (name + ".csv")
    if exact.exists():
        return exact

    # Label match — pick the most recent (lexicographic, since filenames embed date)
    matches = sorted(_RECORDINGS.glob(f"{name}_*.csv"))
    if matches:
        return matches[-1]

    # Also try name as a prefix without date assumption
    matches = sorted(_RECORDINGS.glob(f"*{name}*.csv"))
    if matches:
        return matches[-1]

    available = [p.name for p in sorted(_RECORDINGS.glob("*.csv"))]
    raise ValueError(
        f"Recording {name!r} not found. Available: {available}"
    )


def _build_baselines(iter_csv_fn) -> dict[str, float]:
    """Build per-link baselines from the empty recording."""
    from core.pipeline import RoomPipeline
    empties = sorted(_RECORDINGS.glob("empty_*.csv"))
    if not empties:
        return {}
    room = RoomPipeline()
    for packet in iter_csv_fn(empties[-1]):
        room.push(packet)
    return room.scores()


def _summarise(events: list[dict[str, Any]]) -> dict[str, int]:
    """Count events by kind."""
    summary: dict[str, int] = {}
    for e in events:
        summary[e["kind"]] = summary.get(e["kind"], 0) + 1
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    server.run(transport="stdio")
