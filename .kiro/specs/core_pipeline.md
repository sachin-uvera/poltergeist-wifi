# Spec: core signal pipeline

Shared sensing skeleton used by both apps. Reads CSI from recordings or live serial ports, cleans the signal, computes a motion score per link, and outputs zone activity.

---

## Source material

- Spike motion score algorithm: `spike/live_plot.py` → `amplitudes()` and `motion_score()`
- Spike recorder: `spike/udp_recv.py` (CSV format: `wall_time_ms, board_ip, board, raw_line`)
- Recordings: `recordings/*.csv`

## File layout

```
core/
├── ingest.py      # parse CSV rows or live serial; yield Packet dataclass
├── pipeline.py    # amplitudes → motion score → smoothing → zone activity
├── replay.py      # replay a recordings/ CSV at real speed through the same pipeline
├── state.py       # state machine (separate spec)
└── config.toml    # all tunable values; read at startup, re-read by MCP server
```

---

## config.toml

All thresholds and tunable values in one file. No magic numbers anywhere in `core/`.

```toml
[pipeline]
window         = 50      # packets per motion-score window (~0.5 s at 100 Hz)
smooth_alpha   = 0.3     # exponential smoothing factor (0 = no smoothing, 1 = no memory)
clip_z         = 4.0     # clip amplitudes beyond this many std-devs from the mean
baseline_secs  = 60      # seconds of empty-room data to capture for calibration

[zones]
# motion_threshold is compared against the smoothed, baseline-normalised score.
# A link is "active" when its score exceeds this value.
motion_threshold = 0.08

[state]
fall_burst_secs      = 0.5   # minimum seconds of high motion before a fall candidate
fall_still_secs      = 3.0   # seconds of stillness after burst → possible_fall
fall_confirm_secs    = 10.0  # more seconds of stillness → fall
inactive_secs        = 1200  # 20 min of present-but-no-movement → inactive_too_long
inactive_secs_demo   = 30    # short value for demos
```

---

## ingest.py

### Packet dataclass

```python
@dataclass
class Packet:
    wall_ms:  int        # milliseconds since epoch (laptop clock)
    board_ms: int        # millis() on the board
    board:    str        # board letter: "A", "B", "C", or "D"
    rssi:     int        # dBm
    link:     str        # e.g. "CSI" (router mode) or "CSI-B" (mesh tx board)
    values:   np.ndarray # int8 array, length 128
```

### parse_line(board, raw_line) → Packet | None

Parses one `raw_line` value from the CSV (or one line from serial). Returns `None` for comment lines, heartbeat lines, malformed lines, or lines with the wrong number of values.

- `raw_line` may or may not be quoted (CSV wrapping). Strip outer quotes before parsing.
- Split on `,` with `maxsplit=4`. Field 0 must start with `CSI`.
- `board` is the board letter from the CSV `board` column (or from the `MAC,` line for live serial).
- `link` is field 0 (`CSI` or `CSI-B`, `CSI-A`, etc.).
- `values` is a `np.array` of `int8` parsed from field 4 (space-separated).

### iter_csv(path) → Iterator[Packet]

Reads a recordings CSV, yields `Packet` objects in file order. Skips header, comment rows, and unparseable lines without raising.

---

## pipeline.py

### amplitudes(values: np.ndarray) → np.ndarray

Converts interleaved `[imag, real, imag, real, …]` int8 array to per-subcarrier amplitude:

```
amp[i] = sqrt(values[2i]² + values[2i+1]²)
```

Returns a float32 array of length `len(values) // 2` (64 for LLTF).

Raises `ValueError` if `values` is empty or has odd length.

### clip_amplitudes(amps: np.ndarray, z: float) → np.ndarray

Clips each amplitude to `mean ± z * std` across subcarriers. Uses the z value from `config.toml [pipeline] clip_z`. Returns float32.

### motion_score(frames: list[np.ndarray]) → float

Identical to the spike algorithm:
1. Stack frames into a 2-D array `(n_frames, n_subcarriers)`.
2. Normalise each frame by its mean: `frame / (frame.mean() + 1e-6)`.
3. Return `std over time, then mean over subcarriers`.

Requires at least 2 frames. Returns `0.0` for fewer.

### class LinkPipeline

One instance per link (e.g. `"A/CSI"`, `"D/CSI-B"`). Maintains a rolling window and an exponential smoother.

```python
def push(self, packet: Packet) -> float:
    """Accept one packet; return the current smoothed motion score."""

def set_baseline(self, score: float) -> None:
    """Set the empty-room baseline score for this link."""

def active(self) -> bool:
    """True when smoothed score > baseline * threshold multiplier."""
```

- Window size, smooth alpha, and motion threshold come from `config.toml`.
- If no baseline has been set, `active()` compares against the raw threshold.

### class RoomPipeline

Owns one `LinkPipeline` per link seen. Dispatches incoming packets and exposes zone status.

```python
def push(self, packet: Packet) -> dict[str, float]:
    """Return {link_key: smoothed_score} after updating."""

def active_links(self) -> set[str]:
    """Set of link keys currently above threshold."""

def set_baseline(self, baselines: dict[str, float]) -> None:
    """Install per-link baselines from calibration."""
```

---

## replay.py

### replay(path, callback, *, realtime=True)

Reads `path` with `iter_csv`, calls `callback(packet)` for each packet.

- When `realtime=True`: sleep between packets to match the original `wall_ms` timestamps (1× real speed). Never sleep more than 2 s per gap to avoid stalling on long pauses in the recording.
- When `realtime=False`: deliver all packets as fast as possible (for tests).

The callback receives the same `Packet` type as the live path. No other differences.

---

## Property-based tests (Hypothesis)

Located at `core/tests/test_pipeline_pbt.py`.

| Test | Property |
|---|---|
| `test_no_nan` | `motion_score` never returns NaN for any non-empty list of valid amplitude arrays |
| `test_score_rises` | Adding frames with high-variance values to a window of low-variance frames increases the score |
| `test_amplitudes_nonneg` | `amplitudes()` always returns non-negative values |
| `test_clip_bounds` | `clip_amplitudes()` output is always within `[0, mean + z*std + ε]` |

---

## Acceptance criteria

- [ ] `iter_csv` replays the `empty` recording without raising.
- [ ] Motion scores from the `empty` recording are consistently lower than scores from the `walk` recording.
- [ ] Motion scores from the `fall` recording show at least one peak ≥ 3× the median `empty` score.
- [ ] `replay(realtime=False)` processes all rows of a recording faster than real time.
- [ ] `replay(realtime=True)` delivers packets with timing within ±100 ms of the original wall clock gaps.
- [ ] All four property-based tests pass with at least 100 examples each.
- [ ] No NaN appears in any score computed from the existing recordings.
