"""Find the longest quiet gap in fall vs walk recordings (after baseline)."""
import pathlib
from core.ingest import iter_csv
from core.pipeline import RoomPipeline

empty_files = sorted(pathlib.Path('.').glob('recordings/empty_*.csv'))
room_bl = RoomPipeline()
for p in iter_csv(empty_files[0]):
    room_bl.push(p)
baselines = room_bl.scores()

for label in ['walk', 'fall']:
    files = sorted(pathlib.Path('.').glob(f'recordings/{label}_*.csv'))
    if not files:
        continue
    room = RoomPipeline()
    room.set_baseline(baselines)

    packets = list(iter_csv(files[0]))
    quiet_start = None
    quiet_gaps = []
    for packet in packets:
        room.push(packet)
        n = len(room.active_links())
        if n == 0:
            if quiet_start is None:
                quiet_start = packet.wall_ms
        else:
            if quiet_start is not None:
                quiet_gaps.append(packet.wall_ms - quiet_start)
                quiet_start = None

    quiet_gaps.sort(reverse=True)
    print(f"{label}: top 5 quiet gaps (ms): {quiet_gaps[:5]}")
    print(f"  = {[round(g/1000,1) for g in quiet_gaps[:5]]} seconds")
    print()
