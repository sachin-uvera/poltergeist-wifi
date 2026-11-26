"""
apps/grandma-ghost/export_demo.py – build the hosted replay demo into site/.

    uv run --with numpy python apps/grandma-ghost/export_demo.py
    uv run --with numpy python apps/grandma-ghost/export_demo.py --labels fall,walk

Each recording in recordings/ is run through the real pipeline and state machine (the same
code the hub uses) and saved as a small JSON file: one entry per second with the motion score
of each link, the room state and the ghost positions, plus the events. The browser plays that
timeline back. Nothing else is written, so no raw CSI is ever published. The privacy check at
the bottom of `export_one` enforces that.

Output (a plain static site, any host can serve it):
    site/index.html          the same page the hub serves, plus demo-player.js
    site/demo-player.js
    site/ghost.png, ghost-red.png
    site/data/index.json     the recordings list
    site/data/<label>.json   one file per recording
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import app            # the hub, for its empty-room baseline (importing it starts nothing)
import position
import tombstones
from core.ingest import iter_csv
from core.pipeline import RoomPipeline
from core.state import StateMachine

RECORDINGS = ROOT / "recordings"
SITE = ROOT / "site"

# label -> title shown in the page. Order is the order in the dropdown.
TITLES = {
    "fall":    "Fall onto the mat",
    "sitting": "Sitting still",
    "fan":     "Ceiling fan running",
    "walk":    "Walking, with pauses",
    "empty":   "Empty room",
}
# The walk recording has long standing pauses that the state machine reads as a possible
# fall, so it is left out of the public demo until it is re-recorded.
DEFAULT_LABELS = ["fall", "sitting", "fan", "empty"]

TICK_MS = 1000          # one update per second, like the hub
MAX_GAP_MS = 2000       # the hub never waits longer than this between packets

# What may appear in the published files. Anything else stops the export.
TOP_KEYS   = {"label", "title", "filename", "duration_s", "ticks", "events"}
TICK_KEYS  = {"t", "scores", "active", "state", "ghosts"}
EVENT_KEYS = {"t", "kind", "icon", "text", "state", "note"}


def export_one(path: Path, baselines: dict[str, float], label: str) -> dict:
    room = RoomPipeline()
    room.set_baseline(baselines)
    sm = StateMachine()
    tracker = position.MultiTracker()
    ticks: list[dict] = []
    events: list[dict] = []
    clock = {"t": 0.0}

    def on_event(ev) -> None:
        d = tombstones.describe(ev)
        events.append({"t": round(clock["t"], 2), "kind": ev.kind, "icon": d["icon"],
                       "text": d["text"], "state": ev.state, "note": ev.note})

    sm.on_event(on_event)

    def tick() -> None:
        raw = room.scores()
        excess = {k: v - baselines.get(k, 0.0) for k, v in raw.items()}
        ghosts = position.place_ghosts(tracker, sm.state.value, excess)
        ticks.append({"t": round(clock["t"], 2),
                      "scores": {k: round(v, 4) for k, v in sorted(raw.items())},
                      "active": sorted(room.active_links()),
                      "state": sm.state.value,
                      "ghosts": ghosts})

    first = prev = None
    offset = 0
    last_tick_ms = 0
    t_ms = 0
    for pk in iter_csv(path):
        if pk.wall_ms <= 0:
            continue
        if first is None:
            first = prev = pk.wall_ms
        gap = pk.wall_ms - prev
        if gap > MAX_GAP_MS:
            offset -= gap - MAX_GAP_MS      # squash long pauses, as the hub does
        prev = pk.wall_ms
        t_ms = pk.wall_ms - first + offset
        clock["t"] = t_ms / 1000
        room.push(pk)
        sm.push(pk.wall_ms, room.active_links())
        if t_ms - last_tick_ms >= TICK_MS:
            tick()
            last_tick_ms = t_ms
    if t_ms > last_tick_ms:
        tick()

    doc = {"label": label, "title": TITLES.get(label, label), "filename": path.name,
           "duration_s": round(t_ms / 1000, 1), "ticks": ticks, "events": events}

    # Privacy check: only scores, states, positions and event text may leave this script.
    assert set(doc) == TOP_KEYS, set(doc) ^ TOP_KEYS
    for tk in ticks:
        assert set(tk) == TICK_KEYS, set(tk) ^ TICK_KEYS
        assert len(tk["scores"]) <= 12 and all(isinstance(v, float) for v in tk["scores"].values())
    for ev in events:
        assert set(ev) == EVENT_KEYS, set(ev) ^ EVENT_KEYS
    return doc


def build_site() -> None:
    page = (HERE / "static" / "index.html").read_text(encoding="utf-8")
    marker = "<script>\n// ── WebSocket connection"
    assert page.count(marker) == 1, "main script marker not found in static/index.html"
    # The demo player must load first: the page's own script looks for window.GG_BACKEND.
    page = page.replace(marker, '<script src="demo-player.js"></script>\n' + marker)
    (SITE / "index.html").write_text(page, encoding="utf-8", newline="\n")
    shutil.copyfile(HERE / "demo" / "demo-player.js", SITE / "demo-player.js")
    for name in ("ghost.png", "ghost-red.png"):
        shutil.copyfile(HERE / "static" / name, SITE / name)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the hosted replay demo into site/")
    ap.add_argument("--labels", default=",".join(DEFAULT_LABELS),
                    help="comma-separated recording labels to include (default: %(default)s)")
    args = ap.parse_args()
    labels = [x.strip() for x in args.labels.split(",") if x.strip()]

    baselines = app._empty_baselines()
    if not baselines:
        print("No empty recording found: the demo needs recordings/empty_*.csv for its baseline.")
        return 1

    (SITE / "data").mkdir(parents=True, exist_ok=True)
    for old in (SITE / "data").glob("*.json"):
        old.unlink()                      # no stale recordings from an earlier build

    manifest = []
    for label in labels:
        matches = sorted(RECORDINGS.glob(f"{label}_*.csv"))
        if not matches:
            print(f"skip {label}: no recording found")
            continue
        doc = export_one(matches[-1], baselines, label)
        out = SITE / "data" / f"{label}.json"
        out.write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        manifest.append({"label": label, "title": doc["title"], "filename": doc["filename"],
                         "file": f"{label}.json", "duration_s": doc["duration_s"]})
        kinds = " -> ".join(e["kind"] for e in doc["events"]) or "(no events)"
        print(f"{label:8s} {doc['duration_s']:5.1f} s  {len(doc['ticks']):3d} ticks  "
              f"{out.stat().st_size / 1024:5.1f} KB  events: {kinds}")

    (SITE / "data" / "index.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
    build_site()
    total = sum(f.stat().st_size for f in SITE.rglob("*") if f.is_file())
    print(f"site/ ready: {sum(1 for f in SITE.rglob('*') if f.is_file())} files, {total / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
