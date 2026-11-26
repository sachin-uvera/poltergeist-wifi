"""Sanity checks for position.Tracker."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import position as p


def r(xy):
    return None if xy is None else (round(xy[0], 2), round(xy[1], 2))


def on_line(xy, a, b, tol=0.02):
    """True if the point lies on the segment between boards a and b."""
    (ax, ay), (bx, by) = p.BOARDS[a], p.BOARDS[b]
    cross = (bx - ax) * (xy[1] - ay) - (by - ay) * (xy[0] - ax)
    return abs(cross) < tol


t = p.Tracker()
print("A-B line only    ->", r(t.update({"A/CSI-B": .2, "B/CSI-A": .18})), "(on the top edge, middle)")
assert on_line(t.xy, "A", "B")

t = p.Tracker()
print("diagonal C-B     ->", r(t.update({"C/CSI-B": .2, "B/CSI-C": .2})), "(on the C-B diagonal)")
assert on_line(t.xy, "B", "C")

t = p.Tracker()
t.update({"A/CSI-B": .2, "A/CSI-C": .05})   # A-B strongest; A also disturbed elsewhere
print("A-B, A also busy ->", r(t.xy), "(leans toward A, x < 0.5)")
assert t.xy[0] < 0.5 and on_line(t.xy, "A", "B")

# Hysteresis: a slightly stronger rival must not steal the ghost
t = p.Tracker()
t.update({"A/CSI-B": .20})
t.update({"A/CSI-B": .20, "C/CSI-D": .22})
print("rival 10% stronger stays on", t.pair, "(expect ('A','B'))")
assert t.pair == ("A", "B")

# A clearly stronger line takes over, and the ghost glides rather than jumps
for i in range(4):
    t.update({"A/CSI-B": .05, "C/CSI-D": .30})
    print("  glide ->", t.pair, r(t.xy))
assert t.pair == ("C", "D")

# Still room: ghost stays; noise below baseline never moves it or gives NaN
before = t.xy
assert t.update({"C/CSI-D": 0.0}) == before
assert p.Tracker().update({"A/CSI-B": -0.05, "weird": 1.0}) is None
print("still / noise handled")
print("all position checks passed")
