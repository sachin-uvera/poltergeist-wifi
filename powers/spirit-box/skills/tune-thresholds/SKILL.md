---
name: tune-thresholds
description: Safely change a Poltergeist detection threshold to fix false alarms or missed falls. Replays the labelled recordings before and after each change, changes one value at a time, and puts the old value back if a fall would be missed.
---

# Tune a detection threshold

Use this when the user says the fall detector is too sensitive, raises false alarms (for example from a ceiling fan), misses a fall, or asks to change a threshold.

The tools come from the `spirit-box` MCP server defined in the project's `.kiro/settings/mcp.json`: `get_thresholds`, `set_thresholds`, `replay`, `list_recordings`, `get_live_stats`. If they are not available, stop and tell the user to open the Poltergeist workspace and reconnect the spirit-box server in the MCP panel.

Background on every threshold, with the values measured from the recordings: `references/thresholds.md`.

## Step 1: Measure before changing anything

1. Call `get_thresholds` and note every value.
2. Call `replay` for each of: `fall`, `fan`, `sitting`, `empty`. Note the events each produced (`event_summary`) and its `final_state`.
3. Judge each against what must happen:

| Recording | Must produce |
|---|---|
| fall | `possible_fall` or `fall` |
| fan, sitting, empty | no `possible_fall` and no `fall` |
| walk | known issue: its long standing pauses read as `possible_fall`. Report it, never tune for it |

4. If everything already meets this, **tell the user nothing needs changing and stop.** Do not change a threshold to fix a problem the recordings do not show. Suggest a new recording of the situation instead (`spike/udp_recv.py <label> 60`).

## Step 2: Pick one value

Choose the single key most likely to fix the problem, using `references/thresholds.md`:

- False alarm from steady motion (fan, someone sitting): raise `motion_threshold` a little (0.01 at a time).
- False alarm that looks like a fall: raise `fall_still_secs` or `fall_links_min`.
- Missed fall: lower `motion_threshold` a little, or lower `fall_still_secs`.

Never change more than one key per round.

## Step 3: Change it and check

1. Call `set_thresholds` with that one key. It edits `core/config.toml` in place and tells the running hub to reload (`running_hub` in the reply says whether it did).
2. Replay `fall`, `fan`, `sitting` and `empty` again.
3. **If `fall` no longer produces `possible_fall` or `fall`, put the old value back at once** with `set_thresholds`, and say the change would have missed a fall.
4. Otherwise compare with step 1 and decide whether the problem is fixed. If not, you may try one more small change. Stop after three rounds and report.

## Step 4: Report

Keep it short:
- a table of recording, before, after, pass/fail
- the key, its old value and its new value
- whether the running hub reloaded

Tell the user the change is in `core/config.toml` and not committed. Committing is their decision. Never print raw CSI values; only scores, states and events.
