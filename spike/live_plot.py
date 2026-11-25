"""Live motion score per link, from one or more CSI boards (router mode or board-to-board csi_mesh).

Usage:  uv run --with pyserial --with matplotlib --with numpy spike/live_plot.py COM4 [COM5 ...]
        ... spike/live_plot.py udp        (csi_udp boards over Wi-Fi, UDP port 5005)
Pass:   a link's line jumps when you walk through it, and settles when you stop.
"""
import socket
import sys
import threading
from collections import deque

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation

try:
    import serial
except ImportError:
    serial = None  # only needed for COM port mode

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


FRAMES = {}
# Board IPs seen at boot (csi_udp). '# board X' / '# heartbeat board=X' lines update this live.
NAMES = {"192.168.29.87": "A", "192.168.29.37": "B", "192.168.29.137": "C", "192.168.29.249": "D"}


def handle(src, line, series, rates):
    """One line per link: router mode lines are 'CSI', board-to-board lines are 'CSI-<tx>'."""
    line = line.strip()
    if line.startswith("#"):
        print(f"{src}: {line}")
        if line.startswith("# board "):
            NAMES[src] = line.split()[2]
        elif line.startswith("# heartbeat board="):
            NAMES[src] = line.split()[2][6:]
        return
    parts = line.split(",", 4)
    if len(parts) != 5 or not parts[0].startswith("CSI"):
        return
    rx = NAMES.get(src, src)
    key = f"{parts[0][4:]}->{rx}" if parts[0] != "CSI" else src
    try:
        a = amplitudes(parts[4].split())
    except ValueError:
        return
    f = FRAMES.setdefault(key, deque(maxlen=WINDOW))
    f.append(a)
    rates[key] = rates.get(key, 0) + 1
    if len(f) == WINDOW and len({x.shape for x in f}) == 1:
        series.setdefault(key, deque(maxlen=HISTORY)).append(motion_score(f))


def reader(port, series, rates):
    if serial is None:
        sys.exit("pyserial is required for COM port mode: uv run --with pyserial ...")
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = port, 921600, 1
    s.dtr = s.rts = False  # released; asserting them holds these boards in reset/download mode
    s.open()
    with s:
        while True:
            handle(port, s.readline().decode(errors="ignore"), series, rates)


def udp_reader(series, rates, port=5005):
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    u.bind(("0.0.0.0", port))
    while True:
        data, (ip, _) = u.recvfrom(65535)
        for line in data.decode(errors="ignore").splitlines():
            handle(ip, line, series, rates)


def main(ports):
    series, rates = {}, {}
    for p in ports:
        if p == "udp":
            threading.Thread(target=udp_reader, args=(series, rates), daemon=True).start()
        else:
            threading.Thread(target=reader, args=(p, series, rates), daemon=True).start()

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.set_xlabel("packets")
    ax.set_ylabel("motion score")
    lines, last = {}, {}

    def update(_):
        top = 0.05
        for k in sorted(series):
            if k not in lines:
                lines[k] = ax.plot([], [], label=k)[0]
                ax.legend(loc="upper left", ncol=3, fontsize=8)
            y = list(series[k])
            lines[k].set_data(range(len(y)), y)
            top = max(top, max(y, default=0) * 1.2)
        ax.set_xlim(0, HISTORY)
        ax.set_ylim(0, top)
        hz = {k: rates[k] - last.get(k, 0) for k in sorted(rates)}
        last.update(rates)
        ax.set_title("pkt/s  " + "  ".join(f"{k}:{h}" for k, h in hz.items()), fontsize=8)
        return list(lines.values())

    _anim = FuncAnimation(fig, update, interval=1000, cache_frame_data=False)
    plt.show()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
