# Spec: core state machine

Consumes the zone activity output of `RoomPipeline` and produces a room state. All apps import this; none implement their own state logic.

---

## States

```
         ┌─────────────────────────────────────────────────┐
         │                                                 ▼
      EMPTY ──presence──▶ PRESENT ──movement──▶ MOVING ──burst+still──▶ POSSIBLE_FALL
         ▲                   │                    │                           │
         │                   │                    └──────no movement──────▶ INACTIVE_TOO_LONG
         │                   └──no presence (all links quiet long enough)──┘
         │                                                 │
         └─────────────────────────────────────────────────┘
                                                           │ more stillness
                                                           ▼
                                                         FALL
```

| State | Meaning |
|---|---|
| `EMPTY` | No one in the room |
| `PRESENT` | Someone is in the room, not moving |
| `MOVING` | Active movement detected on at least one link |
| `POSSIBLE_FALL` | Sharp burst on multiple links followed by sustained stillness |
| `FALL` | `POSSIBLE_FALL` confirmed: stillness continues past the confirm window |
| `INACTIVE_TOO_LONG` | Present but no movement for the inactivity threshold |

---

## Transition rules

All time thresholds come from `config.toml [state]`. No magic numbers in `state.py`.

### EMPTY → PRESENT
Any link becomes active.

### PRESENT → MOVING
Any link active.

### MOVING → PRESENT
All links have been quiet for at least `fall_still_secs` without a prior burst.

### MOVING → POSSIBLE_FALL
All of:
1. At least `fall_links_min` links were active simultaneously during the burst (burst = any window where `n_active >= fall_links_min`).
2. The burst lasted at least `fall_burst_secs`.
3. All links have been quiet for at least `fall_still_secs` after the burst ended.

### POSSIBLE_FALL → FALL
All links remain quiet for a further `fall_confirm_secs` with no movement.

### POSSIBLE_FALL → MOVING (false alarm cleared)
Any link becomes active again during the confirm window — person got up.

### PRESENT or MOVING → INACTIVE_TOO_LONG
No link has been active for `inactive_secs` (or `inactive_secs_demo` when demo mode is on) while the state has been PRESENT or MOVING at least once since entering the room. EMPTY does not count toward inactivity.

### Any state → EMPTY
All links quiet for `empty_secs`. Resets the inactivity clock.

### FALL or INACTIVE_TOO_LONG → EMPTY
Explicit `reset()` call (e.g. user acknowledges the alert in the UI).

---

## Events emitted

The state machine emits an `Event` whenever a state transition occurs.

```python
@dataclass
class Event:
    kind:       str        # "fall", "possible_fall", "inactive", "present", "moving", "empty", "reset"
    state:      str        # new state name, lower-case
    wall_ms:    int        # wall clock time of the transition (ms since epoch)
    active_links: list[str]  # which links were active at transition time
    note:       str        # human-readable, e.g. "burst 0.8s, still 3.2s"
```

Consumers (apps) subscribe via a callback registered with `StateMachine.on_event()`.

---

## API

```python
class StateMachine:
    def __init__(self, demo: bool = False) -> None: ...

    def push(self, wall_ms: int, active_links: set[str]) -> State: ...
    # Called once per pipeline tick with the current active link set.
    # Returns the current State. Emits Events on transitions.

    def reset(self) -> None: ...
    # Acknowledge an alert; transition back to EMPTY.

    def on_event(self, cb: Callable[[Event], None]) -> None: ...
    # Register a callback. Multiple callbacks allowed.

    @property
    def state(self) -> State: ...

    @property
    def state_since_ms(self) -> int: ...
    # wall_ms when the current state was entered
```

`State` is a `str` enum: `"empty"`, `"present"`, `"moving"`, `"possible_fall"`, `"fall"`, `"inactive_too_long"`.

---

## Config keys used

All from `config.toml [state]`:

| Key | Default | Meaning |
|---|---|---|
| `fall_burst_secs` | 0.5 | Minimum burst duration to qualify as a fall candidate |
| `fall_still_secs` | 3.0 | Stillness after burst → POSSIBLE_FALL |
| `fall_confirm_secs` | 10.0 | Further stillness → FALL |
| `fall_links_min` | 2 | Minimum simultaneous active links during burst |
| `inactive_secs` | 1200 | Inactivity window (20 min) |
| `inactive_secs_demo` | 30 | Inactivity window in demo mode |
| `empty_secs` | 10.0 | All-quiet window to declare room EMPTY |

Add `fall_links_min` and `empty_secs` to `config.toml`.

---

## Acceptance criteria

- [ ] Replaying `fall_*.csv` through pipeline + state machine produces at least one `"fall"` or `"possible_fall"` event.
- [ ] Replaying `walk_*.csv` produces no `"fall"` or `"possible_fall"` event.
- [ ] Replaying `fan_*.csv` produces no `"fall"` or `"possible_fall"` event.
- [ ] Replaying `empty_*.csv` stays in `"empty"` state throughout.
- [ ] Replaying `sitting_*.csv` reaches `"present"` and never reaches `"moving"` or higher.
- [ ] Setting `demo=True` uses `inactive_secs_demo` instead of `inactive_secs`.
- [ ] `reset()` from `"fall"` transitions to `"empty"` and emits a `"reset"` event.
- [ ] All state tests pass with `realtime=False` replay (fast path).
