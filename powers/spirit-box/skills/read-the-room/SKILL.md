---
name: read-the-room
description: Explain in plain language what the Poltergeist hub sees right now - room state, which board-to-board links are disturbed, where the ghost is, and recent events - using the spirit-box get_live_stats tool.
---

# Read the room

Use this when the user asks what is happening in the room, whether the boards are working, where someone is, or why an alert fired.

## Step 1: Get the live view

Call `get_live_stats` (spirit-box MCP server). Check the `source` field first:
- `hub (live)`: the boards are streaming and this is the real room now.
- `hub (replay)` or `hub (idle)`: the hub is running but not watching the room. Say so and suggest switching the app to Live.
- `last replay() ...`: no hub is running. Say the numbers are from a recording, not the room, and that the hub starts with `uv run --with websockets --with python-dotenv --with numpy apps/grandma-ghost/app.py --live`.

## Step 2: Explain it

The boards stand in the room corners: A top-left, B top-right, D bottom-left, C bottom-right. A link key such as `B/CSI-D` is the line between boards B and D (B heard D). So:

| Line | Where it runs |
|---|---|
| A–B | top wall |
| D–C | bottom wall |
| A–D | left wall |
| B–C | right wall |
| A–C, B–D | the two diagonals, through the middle |

Report:
1. The room state (`empty`, `present`, `moving`, `possible_fall`, `fall`, `inactive_too_long`).
2. Which lines are active, described as walls or diagonals. If none are active but the state is `present`, someone is in the room keeping still.
3. The ghost position (`x`, `y` from 0 to 1, x to the right and y down) in words, for example "near the right wall, halfway down". Two ghosts means two people on opposite sides.
4. Whether the room is calibrated. If not, suggest "Exorcise the room" in the app, with the room empty for 60 s.
5. The recent events, newest first.

## Step 3: Spot problems

- There should be 12 links for 4 boards. A board whose links are missing from `scores`, or whose scores stay exactly the same across two calls a few seconds apart, is probably off or off Wi-Fi.
- An alert with no active lines just before it usually means stillness after movement; see the `tune-thresholds` skill if it is a false alarm.

Never ask for or print raw CSI values. Only scores, states, positions and events leave the hub.
