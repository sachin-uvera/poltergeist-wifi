"""
core/state.py – room state machine.

Spec: .kiro/specs/core_state.md

Consumes active_links from RoomPipeline.active_links() and emits Events on
every state transition.  All time thresholds come from config.toml [state].

States
------
  empty → present → moving → possible_fall → fall
                           ↘ inactive_too_long
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

# ── Config ────────────────────────────────────────────────────────────────────

def _load_cfg() -> dict:
    with open(Path(__file__).parent / "config.toml", "rb") as fh:
        return tomllib.load(fh)


def _s_to_ms(seconds: float) -> int:
    return int(seconds * 1000)


# ── State enum ────────────────────────────────────────────────────────────────

class State(str, Enum):
    EMPTY             = "empty"
    PRESENT           = "present"
    MOVING            = "moving"
    POSSIBLE_FALL     = "possible_fall"
    FALL              = "fall"
    INACTIVE_TOO_LONG = "inactive_too_long"


# ── Event dataclass ───────────────────────────────────────────────────────────

@dataclass
class Event:
    kind:         str         # "fall", "possible_fall", "inactive", "present",
                              # "moving", "empty", "reset"
    state:        str         # new state name (lower-case)
    wall_ms:      int         # wall-clock time of transition (ms since epoch)
    active_links: list[str]   # links active at transition time
    note:         str = ""    # human-readable detail


# ── State machine ─────────────────────────────────────────────────────────────

class StateMachine:
    """Room-level state machine driven by active link sets from RoomPipeline."""

    def __init__(self, demo: bool = False) -> None:
        self._demo     = demo
        self._cfg      = _load_cfg()["state"]
        self._state    = State.EMPTY
        self._since_ms = 0          # wall_ms when current state was entered
        self._callbacks: list[Callable[[Event], None]] = []

        # Burst tracking: wall_ms when high-activity burst started, None if not in burst
        self._burst_start_ms:  int | None = None
        self._burst_peak_links: int = 0     # max simultaneous active links during burst
        self._burst_end_ms:    int | None = None   # when the burst ended (all quiet)

        # Inactivity tracking: wall_ms of last movement while in room
        self._last_move_ms:  int = 0
        # Quiet tracking: wall_ms when all links last went quiet (for EMPTY check)
        self._all_quiet_since_ms: int | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def push(self, wall_ms: int, active_links: set[str]) -> State:
        """Advance the machine by one tick.  Returns the current State."""
        n_active = len(active_links)
        links    = sorted(active_links)

        # Track all-quiet window (used by PRESENT→EMPTY and MOVING→PRESENT)
        if n_active > 0:
            self._all_quiet_since_ms = None   # reset whenever any link is active
        elif self._all_quiet_since_ms is None:
            self._all_quiet_since_ms = wall_ms  # start counting from first quiet tick

        cfg = self._cfg
        burst_ms        = _s_to_ms(cfg["fall_burst_secs"])
        still_ms        = _s_to_ms(cfg["fall_still_secs"])
        confirm_ms      = _s_to_ms(cfg["fall_confirm_secs"])
        fall_links_min  = cfg["fall_links_min"]
        empty_ms        = _s_to_ms(cfg["empty_secs"])
        inactive_ms     = _s_to_ms(
            cfg["inactive_secs_demo"] if self._demo else cfg["inactive_secs"]
        )

        quiet_duration = (wall_ms - self._all_quiet_since_ms) if self._all_quiet_since_ms is not None else 0

        # ── EMPTY ─────────────────────────────────────────────────────────────
        if self._state == State.EMPTY:
            if n_active > 0:
                self._last_move_ms = wall_ms
                self._transition(State.PRESENT, wall_ms, links, "present", "")

        # ── PRESENT ───────────────────────────────────────────────────────────
        elif self._state == State.PRESENT:
            if n_active > 0:
                self._last_move_ms = wall_ms
                self._reset_burst(wall_ms, n_active)
                self._transition(State.MOVING, wall_ms, links, "moving", "")
            elif quiet_duration >= empty_ms:
                self._transition(State.EMPTY, wall_ms, links, "empty", "all links quiet")
            elif self._last_move_ms > 0 and wall_ms - self._last_move_ms >= inactive_ms:
                self._transition(
                    State.INACTIVE_TOO_LONG, wall_ms, links, "inactive",
                    f"no movement for {(wall_ms - self._last_move_ms) // 1000}s"
                )

        # ── MOVING ────────────────────────────────────────────────────────────
        elif self._state == State.MOVING:
            if n_active > 0:
                self._last_move_ms = wall_ms
                # Track burst: how many links active at once
                if self._burst_start_ms is None:
                    self._burst_start_ms = wall_ms
                self._burst_peak_links = max(self._burst_peak_links, n_active)
                self._burst_end_ms = None   # still in burst
            else:
                # All quiet — record when burst ended
                if self._burst_end_ms is None and self._burst_start_ms is not None:
                    self._burst_end_ms = wall_ms

                quiet_ms = quiet_duration

                # Check for fall: qualifying burst followed by sustained stillness
                burst_duration = (
                    (self._burst_end_ms - self._burst_start_ms)
                    if self._burst_start_ms and self._burst_end_ms
                    else 0
                )
                burst_qualifies = (
                    burst_duration >= burst_ms
                    and self._burst_peak_links >= fall_links_min
                )

                if burst_qualifies and quiet_ms >= still_ms:
                    note = (
                        f"burst {burst_duration / 1000:.1f}s "
                        f"({self._burst_peak_links} links), "
                        f"still {quiet_ms / 1000:.1f}s"
                    )
                    self._transition(State.POSSIBLE_FALL, wall_ms, links, "possible_fall", note)

                elif quiet_ms >= still_ms:
                    # Long quiet without a qualifying burst → back to present
                    self._transition(State.PRESENT, wall_ms, links, "present", "movement ended")

                elif wall_ms - self._last_move_ms >= inactive_ms:
                    self._transition(
                        State.INACTIVE_TOO_LONG, wall_ms, links, "inactive",
                        f"no movement for {(wall_ms - self._last_move_ms) // 1000}s"
                    )

        # ── POSSIBLE_FALL ─────────────────────────────────────────────────────
        elif self._state == State.POSSIBLE_FALL:
            if n_active > 0:
                # Person got up — false alarm
                self._last_move_ms = wall_ms
                self._reset_burst(wall_ms, n_active)
                self._transition(State.MOVING, wall_ms, links, "moving", "possible fall cleared")
            elif wall_ms - self._since_ms >= confirm_ms:
                self._transition(
                    State.FALL, wall_ms, links, "fall",
                    f"still for {(wall_ms - self._since_ms) // 1000}s after possible fall"
                )

        # ── FALL ──────────────────────────────────────────────────────────────
        elif self._state == State.FALL:
            pass  # stays in FALL until explicit reset()

        # ── INACTIVE_TOO_LONG ─────────────────────────────────────────────────
        elif self._state == State.INACTIVE_TOO_LONG:
            if n_active > 0:
                # Movement again — clear inactivity
                self._last_move_ms = wall_ms
                self._reset_burst(wall_ms, n_active)
                self._transition(State.MOVING, wall_ms, links, "moving", "inactivity cleared")

        return self._state

    def reset(self) -> None:
        """Acknowledge an alert (FALL or INACTIVE_TOO_LONG) and return to EMPTY."""
        self._transition(State.EMPTY, self._since_ms, [], "reset", "acknowledged")
        self._last_move_ms       = 0
        self._all_quiet_since_ms = None
        self._burst_start_ms     = None
        self._burst_end_ms       = None
        self._burst_peak_links   = 0

    def on_event(self, cb: Callable[[Event], None]) -> None:
        """Register a callback, called on every state transition."""
        self._callbacks.append(cb)

    @property
    def state(self) -> State:
        return self._state

    @property
    def state_since_ms(self) -> int:
        return self._since_ms

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _transition(
        self,
        new_state: State,
        wall_ms: int,
        active_links: list[str],
        kind: str,
        note: str,
    ) -> None:
        prev_state = self._state
        self._state    = new_state
        self._since_ms = wall_ms
        # Reset burst tracking whenever we leave MOVING (not when entering it)
        if prev_state == State.MOVING and new_state != State.MOVING:
            self._burst_start_ms   = None
            self._burst_end_ms     = None
            self._burst_peak_links = 0
        # When entering MOVING fresh (not from MOVING), start a new burst window
        if new_state == State.MOVING and prev_state != State.MOVING:
            self._burst_start_ms   = wall_ms if active_links else None
            self._burst_end_ms     = None
            self._burst_peak_links = len(active_links)
        ev = Event(
            kind=kind,
            state=new_state.value,
            wall_ms=wall_ms,
            active_links=active_links,
            note=note,
        )
        for cb in self._callbacks:
            cb(ev)

    def _reset_burst(self, wall_ms: int, n_active: int) -> None:
        self._burst_start_ms   = wall_ms if n_active > 0 else None
        self._burst_end_ms     = None
        self._burst_peak_links = n_active
