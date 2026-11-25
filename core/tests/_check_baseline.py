"""Diagnostic: use the empty recording as calibration, then score all other recordings."""
from core.ingest import iter_csv
from core.pipeline import RoomPipeline
import pathlib

def build_baselines():
    files = sorted(pathlib.Path('.').glob('recordings/empty_*.csv'))
    if not files:
        raise FileNotFoundError('no empty recording found')
    room = RoomPipeline()
    for p in iter_csv(files[0]):
        room.push(p)
    return room.scores()

baselines = build_baselines()
print("Baselines from empty recording:")
for k, v in sorted(baselines.items()):
    print(f"  {k}: {v:.4f}")
print()

for label in ['empty', 'fall', 'fan', 'sitting', 'walk']:
    files = sorted(pathlib.Path('.').glob(f'recordings/{label}_*.csv'))
    if not files:
        continue

    room = RoomPipeline()
    room.set_baseline(baselines)

    active_ticks = 0
    total_ticks  = 0
    for p in iter_csv(files[0]):
        room.push(p)
        total_ticks += 1
        if room.active_links():
            active_ticks += 1

    pct = 100 * active_ticks / max(total_ticks, 1)
    print(f"{label}: {active_ticks}/{total_ticks} active ({pct:.1f}%)")
