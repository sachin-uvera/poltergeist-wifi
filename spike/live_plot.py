"""Go/no-go viewer: live motion score from one or more CSI boards.

Usage:  uv run --with pyserial --with matplotlib --with numpy spike/live_plot.py COM4 [COM5]
Pass:   the line jumps when you walk between a board and the router, and settles when you stop.
"""
import sys
import threading
from collections import deque

import matplotlib.pyplot as plt
import numpy as np
import serial
from matplotlib.animation import FuncAnimation

WINDOW = 50      # packets (~0.5 s at 100 Hz) for the motion score
HISTORY = 1500   # points shown (~15 s)


def amplitudes(values):
    """Interleaved [imag, real, ...] -> per-subcarrier amplitude."""
    v = np.asarray(values, dtype=np.float32)
    return np.hypot(v[0::2], v[1::2])


def motion_score(frames):
    """Mean over subcarriers of the std over time. Empty room ~ low, movement ~ high."""
    a = np.stack(frames)
    a = a / (a.mean(axis=1, keepdims=True) + 1e-6)  # cancel overall gain swings
    return float(a.std(axis=0).mean())


def reader(port, scores, rates):
    frames = deque(maxlen=WINDOW)
    count = 0
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = port, 921600, 1
    s.dtr = s.rts = False  # released; asserting them holds these boards in reset/download mode
    s.open()
    with s:
        while True:
            line = s.readline().decode(errors="ignore").strip()
            if line.startswith("#"):
                print(f"{port}: {line}")
                continue
            parts = line.split(",", 4)
            if len(parts) != 5 or parts[0] != "CSI":
                continue
            try:
                frames.append(amplitudes(parts[4].split()))
            except ValueError:
                continue
            count += 1
            rates[port] = count
            if len(frames) == WINDOW and len({f.shape for f in frames}) == 1:
                scores.append(motion_score(frames))


def main(ports):
    series = {p: deque(maxlen=HISTORY) for p in ports}
    rates = {p: 0 for p in ports}
    for p in ports:
        threading.Thread(target=reader, args=(p, series[p], rates), daemon=True).start()

    fig, ax = plt.subplots(figsize=(10, 4))
    lines = {p: ax.plot([], [], label=p)[0] for p in ports}
    ax.set_title("Poltergeist go/no-go: walk between a board and the router")
    ax.set_xlabel("packets")
    ax.set_ylabel("motion score")
    ax.legend(loc="upper left")
    last = dict(rates)

    def update(_):
        top = 0.05
        for p, ln in lines.items():
            y = list(series[p])
            ln.set_data(range(len(y)), y)
            top = max(top, max(y, default=0) * 1.2)
        ax.set_xlim(0, HISTORY)
        ax.set_ylim(0, top)
        hz = {p: rates[p] - last[p] for p in ports}
        last.update(rates)
        ax.set_title("Poltergeist go/no-go   " + "   ".join(f"{p}: {h} pkt/s" for p, h in hz.items()))
        return list(lines.values())

    _anim = FuncAnimation(fig, update, interval=1000, cache_frame_data=False)
    plt.show()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
