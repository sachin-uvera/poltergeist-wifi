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
import sys
import threading
import time
import tomllib
import tomli_w
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
from mcp.server.mcpserver import MCPServer

# ── Repo root (two levels up from this file) ──────────────────────────────────
_ROOT = Path(__file__).parent.parent
_RECORDINGS = _ROOT / "recordings"
_CONFIG     = Path(__file__).parent / "config.toml"

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
        "Return the current motion score per link, the room state, and the set "
        "of active links. Works in both live mode (boards streaming) and after "
        "a replay() call. Motion scores only — raw CSI is never returned."
    ),
)
def get_live_stats() -> dict[str, Any]:
    room, sm = _ensure_live()
    with _lock:
        scores       = room.scores()
        active       = sorted(room.active_links())
        state        = sm.state.value
        state_since  = sm.state_since_ms

    return {
        "state":        state,
        "state_since_ms": state_since,
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

    allowed_zones = set(cfg.get("zones", {}).keys())
    allowed_state = set(cfg.get("state", {}).keys())
    allowed       = allowed_zones | allowed_state

    rejected = {k: v for k, v in updates.items() if k not in allowed}
    if rejected:
        return {
            "status":   "error",
            "message":  f"Unknown keys (not in [zones] or [state]): {list(rejected.keys())}",
            "allowed":  sorted(allowed),
        }

    applied: dict[str, Any] = {}
    for key, value in updates.items():
        if key in allowed_zones:
            cfg["zones"][key] = value
            applied[key] = value
        elif key in allowed_state:
            cfg["state"][key] = value
            applied[key] = value

    with open(_CONFIG, "wb") as fh:
        tomli_w.dump(cfg, fh)

    reload_config()

    return {
        "status":  "ok",
        "applied": applied,
        "config":  {"zones": cfg["zones"], "state": cfg["state"]},
    }


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
