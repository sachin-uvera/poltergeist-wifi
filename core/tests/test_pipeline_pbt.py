"""
Property-based tests for core/pipeline.py signal math.

Spec: .kiro/specs/core_pipeline.md § Property-based tests

Run:  uv run --with hypothesis --with numpy pytest core/tests/test_pipeline_pbt.py -v
"""
import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.pipeline import amplitudes, clip_amplitudes, motion_score

# ── Helpers ───────────────────────────────────────────────────────────────────

# int8 arrays with even length (interleaved imag/real pairs)
int8_values = st.lists(
    st.integers(min_value=-128, max_value=127),
    min_size=2,
    max_size=128,
).filter(lambda x: len(x) % 2 == 0).map(lambda x: np.array(x, dtype=np.int8))

# A single amplitude array (output of amplitudes())
amp_array = int8_values.map(amplitudes)

# A list of amplitude arrays all the same length
def same_shape_frames(draw):
    n_sub = draw(st.integers(min_value=2, max_value=64))
    n_frames = draw(st.integers(min_value=2, max_value=100))
    frames = [
        draw(
            st.lists(
                st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
                min_size=n_sub,
                max_size=n_sub,
            ).map(lambda x: np.array(x, dtype=np.float32))
        )
        for _ in range(n_frames)
    ]
    return frames


# ── Tests ─────────────────────────────────────────────────────────────────────

@given(int8_values)
@settings(max_examples=200)
def test_no_nan(values):
    """motion_score never returns NaN for any valid input."""
    amps = amplitudes(values)
    score = motion_score([amps] * 10)
    assert math.isfinite(score), f"got non-finite score {score} for values {values[:8]}…"


@given(st.data())
@settings(max_examples=200)
def test_score_rises(data):
    """Adding high-variance frames to a low-variance window increases the score."""
    n_sub = 64
    # low-variance baseline: all values ~1.0
    low = [np.ones(n_sub, dtype=np.float32) + np.random.default_rng(i).random(n_sub) * 0.01
           for i in range(20)]
    score_before = motion_score(low)

    # high-variance frames: random large amplitudes
    high = [np.random.default_rng(100 + i).random(n_sub).astype(np.float32) * 50.0
            for i in range(20)]
    score_after = motion_score(low + high)

    assert score_after >= score_before, (
        f"score did not rise: before={score_before:.4f} after={score_after:.4f}"
    )


@given(int8_values)
@settings(max_examples=200)
def test_amplitudes_nonneg(values):
    """amplitudes() always returns non-negative values."""
    amps = amplitudes(values)
    assert (amps >= 0).all(), f"negative amplitude found in {amps}"


@given(amp_array, st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=200)
def test_clip_bounds(amps, z):
    """clip_amplitudes() output is within [0, mean + z*std + small epsilon]."""
    clipped = clip_amplitudes(amps, z=z)
    mu  = amps.mean()
    sig = amps.std()
    upper = mu + z * sig + 1e-4   # small epsilon for float rounding
    assert (clipped >= 0).all(), "clip produced negative values"
    assert (clipped <= upper).all(), (
        f"clip exceeded bound: max={clipped.max():.4f} bound={upper:.4f}"
    )


# ── Smoke tests against real recordings ──────────────────────────────────────

@pytest.mark.parametrize("label,csv_glob", [
    ("empty",  "recordings/empty_*.csv"),
    ("walk",   "recordings/walk_*.csv"),
    ("fall",   "recordings/fall_*.csv"),
])
def test_no_nan_in_recordings(label, csv_glob, tmp_path):
    """No NaN score appears when replaying any real recording."""
    from pathlib import Path
    from core.ingest import iter_csv
    from core.pipeline import RoomPipeline

    matches = sorted(Path(".").glob(csv_glob))
    if not matches:
        pytest.skip(f"no {label} recording found")

    room = RoomPipeline()
    for packet in iter_csv(matches[0]):
        scores = room.push(packet)
        for key, score in scores.items():
            assert math.isfinite(score), f"NaN/Inf score for link {key} in {label} recording"


def test_empty_score_lower_than_walk():
    """Motion scores from the empty recording are lower on average than from the walk recording."""
    from pathlib import Path
    from core.ingest import iter_csv
    from core.pipeline import RoomPipeline

    empty_files = sorted(Path(".").glob("recordings/empty_*.csv"))
    walk_files  = sorted(Path(".").glob("recordings/walk_*.csv"))
    if not empty_files or not walk_files:
        pytest.skip("missing empty or walk recording")

    def collect_scores(path):
        room = RoomPipeline()
        all_scores = []
        for packet in iter_csv(path):
            scores = room.push(packet)
            all_scores.extend(scores.values())
        return all_scores

    empty_scores = collect_scores(empty_files[0])
    walk_scores  = collect_scores(walk_files[0])

    assert empty_scores, "no scores from empty recording"
    assert walk_scores,  "no scores from walk recording"

    assert np.mean(empty_scores) < np.mean(walk_scores), (
        f"empty mean={np.mean(empty_scores):.4f} not lower than walk mean={np.mean(walk_scores):.4f}"
    )
