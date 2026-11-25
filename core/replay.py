"""
core/replay.py – play a recordings CSV through the same pipeline as live data.

Spec: .kiro/specs/core_pipeline.md § replay.py

Usage (from the repo root):
    uv run python -c "
    from core.replay import replay
    from core.pipeline import RoomPipeline
    room = RoomPipeline()
    replay('recordings/walk_20261125_064620.csv', room.push)
    "
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from core.ingest import Packet, iter_csv

# Maximum sleep between packets in realtime mode.
# Prevents stalling on long pauses in the recording (e.g. between sessions).
_MAX_GAP_S = 2.0


def replay(
    path: str | Path,
    callback: Callable[[Packet], object],
    *,
    realtime: bool = True,
) -> int:
    """Replay a recordings CSV, calling callback(packet) for each valid packet.

    Parameters
    ----------
    path:     Path to a recordings/*.csv file.
    callback: Called with each Packet in order.  Return value is ignored.
    realtime: If True, sleep between packets to match original wall_ms timing (1× speed).
              If False, deliver all packets as fast as possible (for tests).

    Returns
    -------
    Number of packets delivered.
    """
    packets_delivered = 0
    prev_wall_ms: int | None = None
    prev_deliver_time: float | None = None

    for packet in iter_csv(path):
        if realtime and prev_wall_ms is not None and packet.wall_ms > 0:
            gap_s = (packet.wall_ms - prev_wall_ms) / 1000.0
            gap_s = min(gap_s, _MAX_GAP_S)   # never stall on long pauses
            if gap_s > 0:
                elapsed = time.monotonic() - prev_deliver_time  # type: ignore[operator]
                sleep_s = gap_s - elapsed
                if sleep_s > 0:
                    time.sleep(sleep_s)

        callback(packet)
        packets_delivered += 1
        prev_wall_ms      = packet.wall_ms
        prev_deliver_time = time.monotonic()

    return packets_delivered
