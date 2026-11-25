"""
core/pipeline.py – signal cleaning, motion score, smoothing, and zone activity.

Spec: .kiro/specs/core_pipeline.md § pipeline.py

Algorithm originates from spike/live_plot.py (amplitudes + motion_score).
"""
from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np
import tomllib

from core.ingest import Packet

# ── Config ────────────────────────────────────────────────────────────────────

def _load_config() -> dict:
    cfg_path = Path(__file__).parent / "config.toml"
    with open(cfg_path, "rb") as fh:
        return tomllib.load(fh)

_cfg = _load_config()
_WINDOW   : int   = _cfg["pipeline"]["window"]
_ALPHA    : float = _cfg["pipeline"]["smooth_alpha"]
_CLIP_Z   : float = _cfg["pipeline"]["clip_z"]
_THRESHOLD: float = _cfg["zones"]["motion_threshold"]


def reload_config() -> None:
    """Re-read config.toml at runtime (called by the MCP server after set_thresholds)."""
    global _cfg, _WINDOW, _ALPHA, _CLIP_Z, _THRESHOLD
    _cfg       = _load_config()
    _WINDOW    = _cfg["pipeline"]["window"]
    _ALPHA     = _cfg["pipeline"]["smooth_alpha"]
    _CLIP_Z    = _cfg["pipeline"]["clip_z"]
    _THRESHOLD = _cfg["zones"]["motion_threshold"]


# ── Pure signal functions ─────────────────────────────────────────────────────

def amplitudes(values: np.ndarray) -> np.ndarray:
    """Interleaved [imag, real, …] int8 → per-subcarrier float32 amplitude.

    Raises ValueError for empty or odd-length input.
    """
    if values.size == 0:
        raise ValueError("values array is empty")
    if values.size % 2 != 0:
        raise ValueError(f"values length {values.size} is odd; expected interleaved imag/real pairs")
    v = values.astype(np.float32)
    return np.hypot(v[0::2], v[1::2])


def clip_amplitudes(amps: np.ndarray, z: float | None = None) -> np.ndarray:
    """Clip amplitudes to mean ± z*std across subcarriers."""
    if z is None:
        z = _CLIP_Z
    mu  = amps.mean()
    sig = amps.std()
    return np.clip(amps, 0.0, mu + z * sig).astype(np.float32)


def motion_score(frames: list[np.ndarray]) -> float:
    """Mean-over-subcarriers of std-over-time, after per-frame gain normalisation.

    Returns 0.0 for fewer than 2 frames.  Never returns NaN.
    """
    if len(frames) < 2:
        return 0.0
    a = np.stack(frames).astype(np.float32)          # (n_frames, n_subcarriers)
    a = a / (a.mean(axis=1, keepdims=True) + 1e-6)   # cancel overall gain swings
    score = float(a.std(axis=0).mean())
    return score if np.isfinite(score) else 0.0


# ── Per-link stateful processor ───────────────────────────────────────────────

class LinkPipeline:
    """Maintains a rolling window and exponential smoother for one link."""

    def __init__(self, link_key: str) -> None:
        self.link_key  = link_key
        self._window   : deque[np.ndarray] = deque(maxlen=_WINDOW)
        self._smoothed : float = 0.0
        self._baseline : float | None = None

    def push(self, packet: Packet) -> float:
        """Accept one packet; return the current smoothed motion score."""
        amps = clip_amplitudes(amplitudes(packet.values))
        self._window.append(amps)
        raw   = motion_score(list(self._window))
        alpha = _ALPHA
        self._smoothed = alpha * raw + (1.0 - alpha) * self._smoothed
        return self._smoothed

    def set_baseline(self, score: float) -> None:
        """Set the empty-room baseline score for this link."""
        self._baseline = score

    def active(self) -> bool:
        """True when smoothed score exceeds the threshold (baseline-relative if set)."""
        ref = self._baseline if self._baseline is not None else 0.0
        return self._smoothed > ref + _THRESHOLD

    @property
    def smoothed_score(self) -> float:
        return self._smoothed


# ── Room-level dispatcher ─────────────────────────────────────────────────────

class RoomPipeline:
    """One LinkPipeline per link seen.  Dispatches packets and reports zone activity."""

    def __init__(self) -> None:
        self._links: dict[str, LinkPipeline] = {}

    def _key(self, packet: Packet) -> str:
        return f"{packet.board}/{packet.link}"

    def push(self, packet: Packet) -> dict[str, float]:
        """Update the matching link; return {link_key: smoothed_score} for all known links."""
        key = self._key(packet)
        if key not in self._links:
            self._links[key] = LinkPipeline(key)
        self._links[key].push(packet)
        return {k: lp.smoothed_score for k, lp in self._links.items()}

    def active_links(self) -> set[str]:
        """Set of link keys currently above their motion threshold."""
        return {k for k, lp in self._links.items() if lp.active()}

    def set_baseline(self, baselines: dict[str, float]) -> None:
        """Install per-link baselines from a calibration run."""
        for key, score in baselines.items():
            if key not in self._links:
                self._links[key] = LinkPipeline(key)
            self._links[key].set_baseline(score)

    def scores(self) -> dict[str, float]:
        return {k: lp.smoothed_score for k, lp in self._links.items()}
