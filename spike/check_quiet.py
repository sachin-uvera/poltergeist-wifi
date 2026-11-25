"""Check longest quiet spell per recording label."""
import csv, glob, numpy as np
from collections import defaultdict

def amplitudes(vals):
    v = np.array(vals, dtype=np.float32)
    return np.hypot(v[0::2], v[1::2])

def motion_score(frames):
    if len(frames) < 2:
        return 0.0
    a = np.stack(frames).astype(np.float32)
    a = a / (a.mean(axis=1, keepdims=True) + 1e-6)
    s = float(a.std(axis=0).mean())
    return s if np.isfinite(s) else 0.0

WINDOW = 50
THRESHOLD = 0.17

for label in ['walk', 'fall']:
    files = glob.glob(f'recordings/{label}_*.csv')
    if not files:
        print(f'{label}: no file')
        continue
    windows = defaultdict(list)
    smoothed = defaultdict(float)
    history = []
    with open(files[0], newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            line = row['raw_line'].strip()
            if not line.startswith('CSI-'):
                continue
            parts = line.split(',', 4)
            if len(parts) != 5:
                continue
            key = f"{row['board']}/CSI-{parts[0][4:]}"
            try:
                amps = amplitudes(list(map(int, parts[4].split())))
                windows[key].append(amps)
                if len(windows[key]) >= WINDOW:
                    raw = motion_score(list(windows[key])[-WINDOW:])
                    smoothed[key] = 0.3 * raw + 0.7 * smoothed[key]
            except Exception:
                pass
            n = sum(1 for k in smoothed if smoothed[k] > THRESHOLD)
            history.append((int(row['wall_time_ms']), n))

    max_q = 0
    qs = None
    for ms, n in history:
        if n == 0:
            if qs is None:
                qs = ms
            if ms - qs > max_q:
                max_q = ms - qs
        else:
            qs = None
    print(f'{label}: longest quiet = {max_q / 1000:.1f}s')
