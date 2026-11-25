"""Check peak simultaneous active links during bursts in each recording."""
import pathlib
from core.ingest import iter_csv
from core.pipeline import RoomPipeline

empty_files = sorted(pathlib.Path('.').glob('recordings/empty_*.csv'))
room_bl = RoomPipeline()
for p in iter_csv(empty_files[0]):
    room_bl.push(p)
baselines = room_bl.scores()

for label in ['walk', 'fall', 'fan', 'sitting']:
    files = sorted(pathlib.Path('.').glob(f'recordings/{label}_*.csv'))
    if not files:
        continue
    room = RoomPipeline()
    room.set_baseline(baselines)
    counts = []
    for packet in iter_csv(files[0]):
        room.push(packet)
        n = len(room.active_links())
        counts.append(n)
    # histogram of simultaneous active link counts
    from collections import Counter
    hist = Counter(counts)
    total = len(counts)
    print(f"{label}:")
    for k in sorted(hist):
        print(f"  {k} links active: {hist[k]} ticks ({100*hist[k]/total:.1f}%)")
    print()
