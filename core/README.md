# core: the sensing skeleton
Shared by both apps: serial ingest from ESP32 nodes, signal cleanup, per-link motion score, zone logic, state machine (empty / present / moving / possible fall / fall / inactive), event bus, replay of recorded sessions. Built from Kiro specs in `.kiro/specs/`.
