"""Diagnose walk recording: find what triggers possible_fall."""
from core.ingest import iter_csv
from core.pipeline import RoomPipeline
from core.state import StateMachine, Event
import pathlib

empty_files = sorted(pathlib.Path('.').glob('recordings/empty_*.csv'))
room_bl = RoomPipeline()
for p in iter_csv(empty_files[0]):
    room_bl.push(p)
baselines = room_bl.scores()

walk_files = sorted(pathlib.Path('.').glob('recordings/walk_*.csv'))
room = RoomPipeline()
room.set_baseline(baselines)
sm = StateMachine()
events = []
sm.on_event(events.append)

for packet in iter_csv(walk_files[0]):
    room.push(packet)
    sm.push(packet.wall_ms, room.active_links())

for e in events:
    print(f"{e.kind:20s} state={e.state:20s} note={e.note!r}")
