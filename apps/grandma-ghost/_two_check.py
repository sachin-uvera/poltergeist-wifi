"""Checks for MultiTracker (two ghosts), synthetic cases first, then the real single-person recordings."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import position as p

# Layout: A top-left, B top-right, C bottom-right, D bottom-left
print("independent lines:",
      sorted(f"{a}{b}-{c}{d}" for (a, b) in [("A", "B"), ("A", "C"), ("A", "D"), ("B", "C"), ("B", "D"), ("C", "D")]
             for (c, d) in [("A", "B"), ("A", "C"), ("A", "D"), ("B", "C"), ("B", "D"), ("C", "D")]
             if (a, b) < (c, d) and p.independent((a, b), (c, d))))

TOP = {"A/CSI-B": .2, "B/CSI-A": .2}          # top wall
BOTTOM = {"C/CSI-D": .2, "D/CSI-C": .2}       # bottom wall
DIAGS = {"A/CSI-C": .2, "B/CSI-D": .2}        # person in the middle crosses both diagonals

# 1. one person: one ghost
t = p.MultiTracker()
for _ in range(6):
    out = t.update(TOP)
assert len(out) == 1, out
print("one person            ->", len(out), "ghost")

# 2. two opposite walls: second ghost appears only after PERSIST_TICKS
t = p.MultiTracker()
counts = [len(t.update({**TOP, **BOTTOM})) for _ in range(6)]
print("two walls, per tick   ->", counts, "(1,1,then 2 once it has held)")
assert counts[0] == 1 and counts[-1] == 2

# 3. the two ghosts sit on their own walls
a, b = t.update({**TOP, **BOTTOM})
ys = sorted([round(a[1], 2), round(b[1], 2)])
print("ghost heights         ->", ys, "(one on the top wall y=0, one on the bottom wall y=1)")
assert ys[0] < 0.1 and ys[1] > 0.9

# 4. a person in the middle (both diagonals) is still ONE person
t = p.MultiTracker()
for _ in range(8):
    out = t.update(DIAGS)
assert len(out) == 1
print("both diagonals        ->", len(out), "ghost (diagonals cross, so same person)")

# 5. one flicker of a second wall does not create a ghost
t = p.MultiTracker()
for _ in range(4):
    t.update(TOP)
out = t.update({**TOP, **BOTTOM})
assert len(out) == 1
print("single-tick flicker   ->", len(out), "ghost")

# 6. a weak second wall (below half the strong one) is ignored
t = p.MultiTracker()
for _ in range(8):
    out = t.update({"A/CSI-B": .30, "C/CSI-D": .05})
assert len(out) == 1
print("weak second wall      ->", len(out), "ghost")

# 7. second person leaves: back to one ghost, and the first ghost keeps its place
t = p.MultiTracker()
for _ in range(6):
    t.update({**TOP, **BOTTOM})
assert t.two
for _ in range(6):
    out = t.update(TOP)
assert len(out) == 1 and not t.two
print("second leaves         ->", len(out), "ghost")

# 8. quiet room holds position, no crash on empty input
assert t.update({}) == t._positions()
print("synthetic checks passed\n")

# ── Real recordings: all single-person, so a second ghost here is a false alarm ──
from core.ingest import iter_csv
from core.pipeline import RoomPipeline

empties = sorted((ROOT / "recordings").glob("empty_*.csv"))
base = RoomPipeline()
for pk in iter_csv(empties[-1]):
    base.push(pk)
baselines = base.scores()

for label in ["empty", "sitting", "fan", "walk", "fall"]:
    f = sorted((ROOT / "recordings").glob(f"{label}_*.csv"))[-1]
    room = RoomPipeline()
    room.set_baseline(baselines)
    tr = p.MultiTracker()
    ticks = two = n = 0
    for pk in iter_csv(f):
        room.push(pk)
        n += 1
        if n % 100 == 0:     # about one tick per second at 100 packets/s
            ex = {k: v - baselines.get(k, 0.0) for k, v in room.scores().items()}
            out = tr.update(ex)
            ticks += 1
            two += len(out) == 2
    print(f"{label:8s} ticks={ticks:4d}  ticks with two ghosts={two}")
