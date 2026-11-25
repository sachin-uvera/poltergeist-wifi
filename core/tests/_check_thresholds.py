"""Try different fall_still_secs values to find one that separates walk pauses from real falls."""
import tomllib, pathlib
from core.ingest import iter_csv
from core.pipeline import RoomPipeline
from core.state import StateMachine

empty_files = sorted(pathlib.Path('.').glob('recordings/empty_*.csv'))
room_bl = RoomPipeline()
for p in iter_csv(empty_files[0]):
    room_bl.push(p)
baselines = room_bl.scores()

for still_secs in [3.0, 5.0, 7.0, 8.0, 10.0]:
    for label in ['walk', 'fall', 'fan']:
        files = sorted(pathlib.Path('.').glob(f'recordings/{label}_*.csv'))
        if not files:
            continue
        room = RoomPipeline()
        room.set_baseline(baselines)
        sm = StateMachine()
        # Patch threshold at runtime
        sm._cfg = dict(sm._cfg)
        sm._cfg['fall_still_secs'] = still_secs

        events = []
        sm.on_event(events.append)
        for packet in iter_csv(files[0]):
            room.push(packet)
            sm.push(packet.wall_ms, room.active_links())

        kinds = {e.kind for e in events}
        flags = []
        if 'fall' in kinds or 'possible_fall' in kinds:
            flags.append('FALL/PF')
        print(f"still={still_secs}s  {label:8s}: {', '.join(flags) or 'clean'}")
    print()
