"""
apps/grandma-ghost/position.py – where the ghost stands on the map.

The boards stand in the room corners (A top-left, B top-right, D bottom-left,
C bottom-right). Keep in step with BOARD_XY in static/index.html. Each pair of boards is a line across the room. A person who
crosses a line disturbs it, so the ghost is placed ON the most disturbed line.

Along that line the position is a guess: it starts at the middle and leans toward
the end whose other links are also disturbed. Only the resulting point (x, y,
each 0 to 1) reaches the browser, never any CSI.
"""
from __future__ import annotations

import re

# Board positions in room coordinates (x right, y down)
BOARDS: dict[str, tuple[float, float]] = {
    "A": (0.0, 0.0),
    "B": (1.0, 0.0),
    "C": (1.0, 1.0),
    "D": (0.0, 1.0),
}

_LINK = re.compile(r"^([A-D])/CSI-([A-D])$")

Pair = tuple[str, str]

# A line must be at least this far above its empty-room baseline to count.
# Below it the room is treated as still and the ghost stays where it was.
MIN_WEIGHT = 0.004

# How far along a line the ghost may lean toward one end (0.25 = a quarter of the way)
MAX_LEAN = 0.25


def link_weights(excess: dict[str, float]) -> dict[Pair, float]:
    """Merge the two directions of each link (A/CSI-B and B/CSI-A) into one weight."""
    out: dict[Pair, float] = {}
    for key, e in excess.items():
        m = _LINK.match(key)
        if not m or m.group(1) == m.group(2):
            continue
        pair = tuple(sorted((m.group(1), m.group(2))))
        out[pair] = max(out.get(pair, 0.0), max(0.0, e))
    return out


class Tracker:
    """Keeps one ghost on its line and smooths its movement."""

    def __init__(self, alpha: float = 0.4, switch_ratio: float = 1.3) -> None:
        self.alpha = alpha                # higher follows faster, lower is steadier
        self.switch_ratio = switch_ratio  # a new line must be this much stronger to take over
        self.pair: Pair | None = None
        self.xy: tuple[float, float] | None = None

    def reset(self) -> None:
        self.pair = None
        self.xy = None

    def update(self, excess: dict[str, float]) -> tuple[float, float] | None:
        """Feed {link_key: score minus baseline}. Returns the ghost position, or the
        last one when nothing is moving (None if there never was one)."""
        weights = link_weights(excess)
        if not weights:
            return self.xy

        best = max(weights, key=weights.get)
        if weights[best] < MIN_WEIGHT:
            return self.xy

        # Hysteresis: stay on the current line unless another is clearly stronger
        if (self.pair in weights and best != self.pair
                and weights[best] < self.switch_ratio * weights[self.pair]):
            best = self.pair
        return self.place(best, weights)

    def place(self, best: Pair, weights: dict[Pair, float]) -> tuple[float, float]:
        """Put the ghost on line `best` and ease it toward the new spot."""
        self.pair = best
        a, b = best
        # Disturbance on the other links touching each end shows which end is closer
        wa = sum(w for p, w in weights.items() if p != best and a in p)
        wb = sum(w for p, w in weights.items() if p != best and b in p)
        total = wa + wb
        t = 0.5 if total < 1e-9 else 0.5 + MAX_LEAN * (wb - wa) / total

        (ax, ay), (bx, by) = BOARDS[a], BOARDS[b]
        target = (ax + t * (bx - ax), ay + t * (by - ay))

        if self.xy is None:
            self.xy = target
        else:
            self.xy = (self.xy[0] + self.alpha * (target[0] - self.xy[0]),
                       self.xy[1] + self.alpha * (target[1] - self.xy[1]))
        return self.xy


# ── Two people ────────────────────────────────────────────────────────────────
# One person can disturb several lines at once (near a corner they touch three; in
# the middle they cross both diagonals), so the number of busy lines says little about
# the number of people. The one clear signal is two busy lines that do not touch or
# cross each other. In a square room those are two opposite walls. A single person
# cannot be next to both walls, so that pattern is read as two people.

SECOND_RATIO = 0.5   # the second line must be at least this fraction of the strongest
SECOND_MIN = 0.08    # ...and at least this far above baseline. In the single-person recordings
                     # (Nov 25) the busiest independent line never passed 0.068, so this sits
                     # just above anything one person produced. Re-check with a two-person recording.
PERSIST_TICKS = 3    # ticks the pattern must hold before a second ghost appears or leaves


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def independent(p: Pair, q: Pair) -> bool:
    """True when two board-to-board lines share no board and do not cross."""
    if set(p) & set(q):
        return False
    a, b = BOARDS[p[0]], BOARDS[p[1]]
    c, d = BOARDS[q[0]], BOARDS[q[1]]
    crossing = (_cross(a, b, c) * _cross(a, b, d) < 0) and (_cross(c, d, a) * _cross(c, d, b) < 0)
    return not crossing


class MultiTracker:
    """Follows one ghost, or two when two people are on opposite sides of the room."""

    def __init__(self) -> None:
        self.first = Tracker()
        self.second = Tracker()
        self.two = False
        self._streak = 0   # consecutive ticks the current answer (one vs two) has been contradicted

    def reset(self) -> None:
        self.first.reset()
        self.second.reset()
        self.two = False
        self._streak = 0

    def update(self, excess: dict[str, float]) -> list[tuple[float, float]]:
        """Feed {link_key: score minus baseline}. Returns one or two ghost positions."""
        weights = link_weights(excess)
        top = max(weights, key=weights.get) if weights else None
        if top is None or weights[top] < MIN_WEIGHT:
            return self._positions()          # nothing moving: hold

        # Is there a second, independent line that is clearly busy?
        rival = None
        for pair, w in weights.items():
            if independent(top, pair) and w >= max(SECOND_MIN, SECOND_RATIO * weights[top]):
                if rival is None or w > weights[rival]:
                    rival = pair
        want_two = rival is not None

        # Change the answer only after it has been contradicted several ticks in a row
        if want_two != self.two:
            self._streak += 1
            if self._streak >= PERSIST_TICKS:
                self.two = want_two
                self._streak = 0
                if not self.two:
                    self.second.reset()
        else:
            self._streak = 0

        if not (self.two and rival is not None):
            self.first.update(excess)
            return self._positions()

        # Two people: give each of the two lines to the ghost already nearest to it
        pairs = [top, rival]
        if self.first.pair in pairs:
            mine = self.first.pair
        elif self.first.xy is not None:
            mine = min(pairs, key=lambda p: self._dist_to_line(self.first.xy, p))
        else:
            mine = top
        theirs = rival if mine == top else top
        self.first.place(mine, weights)
        self.second.place(theirs, weights)
        return self._positions()

    def _positions(self) -> list[tuple[float, float]]:
        out = [t.xy for t in ((self.first, self.second) if self.two else (self.first,)) if t.xy]
        return out

    @staticmethod
    def _dist_to_line(xy, pair: Pair) -> float:
        (ax, ay), (bx, by) = BOARDS[pair[0]], BOARDS[pair[1]]
        mx, my = (ax + bx) / 2, (ay + by) / 2
        return (xy[0] - mx) ** 2 + (xy[1] - my) ** 2
