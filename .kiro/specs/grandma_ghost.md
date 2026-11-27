# Spec: Grandma Ghost app

The web app on top of `core/`: a haunted map of an elderly person's room, built only from Wi-Fi signals, with an on-screen alarm and a Telegram alert when someone falls or has not moved for too long.

> **How this spec was written.** The app was built step by step from prompts in Kiro chat (Nov 26–27). This file was written afterwards, on Nov 27, to record the requirements as built and the checks behind them. Each acceptance criterion says whether it was verified, and how.

---

## Users and the job

| Who | Needs |
|---|---|
| Family caregiver | To know quickly, on their phone, when the person falls or stays still too long. No cameras in the room. |
| The person being watched | Privacy: no camera, no microphone, no raw signal data leaving the house. They have agreed to be monitored (see `privacy.md`). |
| A judge or visitor | To see the whole thing work in a browser, with no hardware, at a public URL. |

---

## Architecture

```
4 ESP32 boards ──UDP 5005──▶ hub: apps/grandma-ghost/app.py (one Python process, run with uv)
                              core/ pipeline → state machine → ghost positions → events
                              │
                              ├──HTTP 8080──▶ browser: static/index.html (plain HTML + JS)
                              ├──WebSocket 8765──▶ same page, about 1 update per second
                              └──HTTPS──▶ Telegram Bot API (fall, inactivity)

Hosted demo: export_demo.py → site/ (static files) → GitHub Pages
             demo/demo-player.js stands in for the hub in the browser
```

The app imports only from `core/` (no copy of the signal logic). The hosted demo and the hub share `position.py` and `tombstones.py`, so the ghost moves and the log reads the same in both.

---

## Requirements

### R1 Haunted floor plan
- A dark room with the four boards at the corners: A top-left, B top-right, D bottom-left, C bottom-right. The layout is defined twice and the two must match: `BOARDS` in `position.py` (hub) and `BOARD_XY` in `index.html` (page).
- The six board-to-board lines are drawn dotted. A line lights up while its link is active.
- Empty room: no ghost, the text "the room is empty…".
- Someone present: a ghost fades in and glides (about 1 s) to its new position. The sprite is a particle ghost built from source artwork by `make_ghost_image.py`.
- The ghost stands **on the most disturbed line**, between the two boards. Along the line it starts at the middle and leans up to a quarter of the way (`MAX_LEAN = 0.25`) toward the end whose other links are also disturbed.
- It stays on its current line unless another is clearly stronger (`switch_ratio = 1.3`), and moves are smoothed (`alpha = 0.4`), so it does not jump between two similar lines.
- The whole sprite stays inside the room on any screen size.
- Possible fall or fall: the ghost lies down and turns red, with a red glow.

### R2 Two people
- With 4 boards the system cannot count people in general: one person can disturb up to three lines. The one clear pattern is **two busy lines that share no board and do not cross**, which in this layout means opposite walls (A–B with C–D, or A–D with B–C). That shows a second ghost.
- The second line must be at least half as busy as the strongest (`SECOND_RATIO = 0.5`) and at least `SECOND_MIN = 0.08` above its baseline. The pattern must hold for `PERSIST_TICKS = 3` updates before a second ghost appears or leaves.
- At most two ghosts. A fall alarm marks every ghost, because the state machine judges the room as a whole.

### R3 Live motion scores
- One row per link (12 rows for 4 boards): the smoothed motion score as a bar and a number, updated about once a second. Active links are highlighted.

### R4 Tombstone event log
- One entry per state change, newest at the top, for example "💀 Fall detected near B/CSI-D, 14:02" or "🕯 Inactivity alert, 14:45". Wording comes from `tombstones.py`.
- Kept to the last 100 entries. Cleared when a new replay or live session starts.

### R5 Calibration: "Exorcise the room"
- A button starts a 60 s empty-room baseline (`baseline_secs` in `core/config.toml`) with a full-screen candle countdown.
- It records from the live feed and installs the result as per-link baselines in the running pipeline. After it, a link counts as active when its score passes its own baseline plus `motion_threshold`.
- Live mode only; in replay the button explains it needs live mode. The baseline is kept in memory only and is lost when the hub restarts.

### R6 Alarm on screen, with sound
- On `possible_fall` or `fall`: the screen flashes red, the badge reads "POSSIBLE FALL" or "FALL", and an alert bar appears with **Acknowledge** (and **Restart replay** in replay mode).
- Sound is a two-tone siren made with the Web Audio API, no audio files.
- Browsers keep a page silent until the first click. So: an **Enable sound** button in the header turns sound on (it plays a short tone and shows "Sound on"); the siren is only scheduled while sound can play right away, never queued; the button flashes while an alarm shows with sound still off; Acknowledge or the alarm ending stops a siren that is playing.
- Acknowledge resets the state machine to `empty` and clears the ghost; monitoring carries on. It is accepted after `possible_fall`, `fall` and `inactive_too_long`, and refused otherwise.

### R7 Telegram alert
- On `fall` and on inactivity (`inactive_too_long`): one message to the family chat, "Poltergeist: Fall detected, 2026-11-26 21:11:38" or "Poltergeist: Inactivity alert, …". Not on `possible_fall`, so a pause mid-walk does not message the family.
- Bot token and chat id in `apps/grandma-ghost/.env`, which is gitignored; `.env.example` is committed. `.env` fills in any setting that is missing or empty in the environment.
- Sending runs in its own thread and never raises: no internet, a rejected message or missing settings are logged, and the hub carries on. A rejection logs Telegram's own reason (for example "chat not found"); the token is never logged.
- `telegram_setup.py` checks the token, lists the chats that have messaged the bot with their ids, and with `--send` sends a test alert through the hub's own sender.

### R8 Live and replay
- **Live:** listen on UDP 5005 for the boards' lines (`CSI-<tx>,…`, `# board X …`, `# heartbeat …`); identify each board by its announcement and IP, never by COM port.
- **Replay:** play a recording from `recordings/` at real speed through the same pipeline, state machine and tracker as live data, with pauses longer than 2 s shortened to 2 s. Replay uses the empty recording as its baseline.
- A Live/Replay toggle and a recording dropdown. Only one pipeline runs at a time; starting one stops the other.

### R9 Hosted replay demo
- `export_demo.py` runs each recording through the real pipeline and writes `site/data/<label>.json`: one entry per second (motion score per link, active links, room state, ghost positions) plus the events. It refuses to write any key outside an allow-list.
- `demo/demo-player.js` replays those files through the page's own message handler and answers the page's calls (replay, acknowledge, stop) in the browser. It skips the empty lead-in; `?rec=<label>` and `?speed=<n>` are supported.
- The page works on a phone (one column, no sideways scrolling) and from a sub-path. Live toggle and Exorcise are hidden in the demo.
- Published by `.github/workflows/pages.yml` to https://sachin-uvera.github.io/poltergeist-wifi/. Recordings: fall, sitting, fan, empty. Walk is left out until re-recorded (its long standing pauses read as possible falls).

### R10 Privacy and security
- Raw CSI never leaves the hub. Only scores, states, active links, ghost positions and event text reach the browser and the public site. Telegram gets event text only.
- The hub binds to `127.0.0.1` by default (`--host 0.0.0.0` to share on the LAN). It serves only the page and two named images; any other path is 404, so no file outside `static/` can be read.
- Replay accepts only names of files inside `recordings/`.

---

## Interfaces

**Run:** `uv run --with websockets --with python-dotenv --with numpy apps/grandma-ghost/app.py [--live | --replay <label>] [--port 8080] [--ws-port 8765] [--udp-port 5005] [--host 127.0.0.1]`

**HTTP:**

| Method | Path | Does |
|---|---|---|
| GET | `/` | the page |
| GET | `/ghost.png`, `/ghost-red.png` | the sprites |
| GET | `/api/state` | current snapshot (mode, room state, scores, ghosts, events, calibration) |
| GET | `/api/recordings` | recordings available for replay |
| POST | `/api/live` | start live mode |
| POST | `/api/replay` | `{"recording": "<label or filename>"}` start a replay |
| POST | `/api/stop` | stop live or replay |
| POST | `/api/calibrate` | start "Exorcise the room" (live mode only) |
| POST | `/api/acknowledge` | clear an alert |

**WebSocket messages (hub → page):** `init` (full snapshot on connect), `tick` (scores, active links, room state, ghosts; about 1 per second), `event` (one tombstone), `mode`, `calibrating` (seconds left), `calibrated`.

---

## Acceptance criteria

| # | Criterion | Status | How it was checked |
|---|---|---|---|
| 1 | Replaying `fall` shows the ghost, fills the log, flashes red and offers Acknowledge | ✅ | `_demo_check.py` in Edge, phone and desktop, local and on the live URL |
| 2 | A confirmed fall sends the Telegram message | ✅ | `_fall_e2e.py`: synthetic fall streamed into a test hub; possible fall at +15 s, fall at +30 s, Telegram answered HTTP 200 and the message arrived |
| 3 | Only fall and inactivity send Telegram; failures never stop the hub | ✅ | `_telegram_check.py` with the network stubbed |
| 4 | Acknowledge clears the alert and ghost; refused when nothing is active | ✅ | `_ack_check.py` and `_demo_check.py` |
| 5 | No siren before the first click, and none after Acknowledge | ✅ | `_sound_check.py`, Edge with autoplay blocked |
| 6 | One ghost per person on one wall; two on opposite walls; none of the five single-person recordings ever shows two | ✅ | `_two_check.py` (synthetic cases and all recordings) and `_two_live_check.py` (through the live hub) |
| 7 | Live mode receives all four boards | ✅ | `_hub_links.py`: all 12 links updating about once a second |
| 8 | No raw CSI reaches the browser or the public site | ✅ | `_ws_check.py` on the WebSocket; the exporter's allow-list; scan of the published files |
| 9 | Hosted demo works on a phone and stays up until Jan 29, 2027 | ✅ / ⏳ | Phone emulation in Edge; not yet opened on a real phone. Uptime depends on the repo staying public with Pages on |
| 10 | The ghost follows a real person walking across the room | ⏳ | Not verified; the position along a line is a coarse guess |
| 11 | A real fall on the mat triggers fall and Telegram | ⏳ | Not yet tried with a real person |
| 12 | The inactivity alert end to end | ⏳ | Same send code as the fall alert, but the 20 min (or 30 s demo) path has not been run end to end |

## Known limits
- With 4 boards: no general people counting, and the position along a line is a guess.
- The fall rule (burst on 2 or more links, 10 s still, 15 s more) cannot tell a fall from standing very still after moving. The walk recording shows this.
- Calibration is lost when the hub restarts.
