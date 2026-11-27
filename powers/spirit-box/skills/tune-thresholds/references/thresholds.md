# Poltergeist detection thresholds

All live in `core/config.toml`. Only the `[zones]` and `[state]` keys can be changed through `set_thresholds`; `[pipeline]` keys are refused.

## [zones]

| Key | Default | Meaning |
|---|---|---|
| `motion_threshold` | 0.17 | A link counts as active when its smoothed motion score is above its empty-room baseline plus this value. Higher means less sensitive. |

Motion scores measured from the Nov 25 recordings, with no baseline applied (the reason 0.17 was chosen):

| Recording | 95th percentile | Highest |
|---|---|---|
| empty | 0.094 | 0.162 |
| sitting | 0.096 | 0.114 |
| fan | 0.119 | 0.155 |
| fall | 0.158 | 0.257 |
| walk | 0.170 | 0.323 |

0.17 sits above everything the empty room, sitting and the fan produced, and below the walk and fall peaks. With the empty-room baseline subtracted (which `replay` and the calibrated hub both do) there is more room on both sides.

## [state]

| Key | Default | Meaning |
|---|---|---|
| `fall_burst_secs` | 0.5 | Shortest burst of motion that can start a fall. |
| `fall_links_min` | 2 | Links that must be active together during the burst. Whole number. |
| `fall_still_secs` | 10.0 | Stillness after the burst before `possible_fall`. |
| `fall_confirm_secs` | 15.0 | More stillness before `possible_fall` becomes `fall`. A Telegram message is sent at `fall`. |
| `empty_secs` | 60.0 | All links quiet this long means the room is empty. |
| `inactive_secs` | 1200 | Present but not moving this long gives an inactivity alert (Telegram). |
| `inactive_secs_demo` | 30 | Same, in demo mode. |

## Known limits

- The fall rule cannot tell a fall from standing very still after moving. The walk recording has pauses of up to 23 s and is reported as a known issue; do not tune for it.
- The recordings were made in one room on one day. A change that passes them is a good sign, not proof.
- Raising `fall_still_secs` or `fall_confirm_secs` delays the alert to the family by the same amount.
