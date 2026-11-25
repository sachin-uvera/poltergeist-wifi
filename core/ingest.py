"""
core/ingest.py – parse CSI packets from recordings CSVs or live serial lines.

Spec: .kiro/specs/core_pipeline.md § ingest.py
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np


@dataclass
class Packet:
    wall_ms:  int         # milliseconds since epoch (laptop clock)
    board_ms: int         # millis() on the board
    board:    str         # board letter: "A", "B", "C", or "D"
    rssi:     int         # dBm
    link:     str         # "CSI" (router mode) or "CSI-B" / "CSI-A" … (mesh)
    values:   np.ndarray  # int8, length 128 (LLTF: 64 subcarriers × imag+real)


def parse_line(board: str, raw_line: str) -> Packet | None:
    """Parse one raw CSI line; return None for comments, heartbeats, or bad data.

    raw_line is the value from the CSV `raw_line` column — it may carry CSV-style
    outer double-quotes added by the recorder.  Strip them before parsing.
    """
    line = raw_line.strip()

    # Strip CSV outer quotes (the recorder wraps lines that contain commas)
    if line.startswith('"') and line.endswith('"'):
        line = line[1:-1].replace('""', '"')

    # Ignore comment and heartbeat lines
    if line.startswith("#") or line.startswith("HB,") or line.startswith("MAC,"):
        return None

    # Must start with CSI (router-mode "CSI" or mesh "CSI-B" etc.)
    parts = line.split(",", 4)
    if len(parts) != 5 or not parts[0].startswith("CSI"):
        return None

    link_field, board_ms_str, rssi_str, _len_str, values_str = parts

    try:
        board_ms = int(board_ms_str)
        rssi     = int(rssi_str)
        values   = np.fromstring(values_str, dtype=np.int8, sep=" ")
    except (ValueError, OverflowError):
        return None

    if values.size == 0 or values.size % 2 != 0:
        return None

    return Packet(
        wall_ms  = 0,          # filled in by iter_csv from the wall_time_ms column
        board_ms = board_ms,
        board    = board,
        rssi     = rssi,
        link     = link_field,
        values   = values,
    )


def iter_csv(path: str | Path) -> Iterator[Packet]:
    """Yield Packet objects from a recordings CSV, skipping bad rows silently."""
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            packet = parse_line(row["board"], row["raw_line"])
            if packet is None:
                continue
            try:
                packet.wall_ms = int(row["wall_time_ms"])
            except (KeyError, ValueError):
                pass
            yield packet
