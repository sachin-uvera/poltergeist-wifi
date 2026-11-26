# Kiro work plan

The order to build Poltergeist in the Kiro IDE once the hackathon credits arrive. Work top to bottom. Each step says what to create in Kiro, a prompt to start it, and how to tell it's done.

**Focus:** Grandma Ghost only. Step 10 (Cold Room Guardian) was dropped on Nov 26: we enter Costume Contest with one app.

**Rule for every step:** build it *through* Kiro (steering, specs, hooks, MCP) and commit `.kiro/` with the code. That folder is the judges' evidence that Kiro was used.

---

## Where we start (Nov 23)

| | Status |
|---|---|
| Hardware | 4 classic ESP32 boards, all running `spike/csi_rx` and streaming CSI at 100 packets/s |
| Repo | Folder skeleton, spike firmware, `spike/live_plot.py` |
| `.kiro/` | Empty (`steering/`, `specs/`, `hooks/` contain only `.gitkeep`) |

| Board | USB chip | MAC | Flash with |
|---|---|---|---|
| A | CH9102 | `20:9b:a9:60:e1:6c` | Arduino IDE Upload button |
| B | CH9102 | `8c:94:df:61:43:b8` | Arduino IDE Upload button |
| C | CP210x | `8c:94:df:90:59:dc` | Piece-by-piece method in the [appendix](#appendix-flashing-boards-c-and-d) |
| D | CP210x | `00:70:07:a3:db:18` | Piece-by-piece method in the [appendix](#appendix-flashing-boards-c-and-d) |

## Target setup

All 4 boards go in one Grandma Ghost room. Each board pings the router, so each board is one "link" across the room.

```
        ┌───────────────────────────────┐
        │ [A]                       [B] │       4 boards × 100 CSI packets/s
        │        bed        chair       │                 │ USB serial
        │   · · · grandma's path · · ·  │                 ▼
        │ [C]                       [D] │      hub (Python, laptop)
        └───────────────┬───────────────┘   clean → score → zone → state
                 router "SamSon" (ch 6)                   │
                                          ┌───────────────┼────────────────┐
                                          ▼               ▼                ▼
                                   web UI (live)   Telegram alert   "spirit box" MCP
                                   + replay mode   to family        for the Kiro agent
```

---

## Step-by-step

### 1. Steering (first hour)
Create in `.kiro/steering/`:

| File | What it says |
|---|---|
| `product.md` | Poltergeist in one line, the two apps, Grandma Ghost first, v1 is minimal (no LEDs or buzzer), and replay mode is mandatory |
| `privacy.md` | Raw CSI never leaves the hub. Only events and scores reach the UI and Telegram. Consent comes first: the system only runs when the person has agreed. No cameras, no microphones. |
| `tech.md` | Firmware is Arduino core 3.3.11 built with arduino-cli. The hub is Python run with `uv`. Serial ports open with DTR=RTS=False. Boards are identified by MAC, never by COM port. Detection uses thresholds, not a trained model. |
| `structure.md` | The repo layout from `PROGRESS.md` and what goes in each folder |

> Prompt: *"Read PROGRESS.md and docs/KIRO_WORKPLAN.md. Create steering files product.md, privacy.md, tech.md and structure.md in .kiro/steering as described in step 1 of the plan."*

**Done when:** the four files exist and Kiro picks them up in a new chat.

### 2. Spec: `firmware/csi_node`
The production firmware, built from the spike.
- Print a header line with the board MAC on boot, so the hub can tell the boards apart.
- Keep a fixed line format: `CSI,<ms>,<rssi>,<len>,<values…>`.
- Reconnect to Wi-Fi automatically, and print a heartbeat line when idle.
- Wi-Fi details stay in a gitignored `secrets.h`.

> Prompt: *"Create a spec for firmware/csi_node based on spike/csi_rx/csi_rx.ino. Requirements: MAC header on boot, stable CSI line format, Wi-Fi auto-reconnect, heartbeat, secrets in secrets.h."*

**Done when:** flashed to all 4 boards, and each one appears in the hub under its own MAC.

### 3. Spec: `core` ingest and recorder
- Read all 4 serial ports at the same time and tag each packet with the board MAC.
- Record sessions to `recordings/<label>_<date>.csv`.
- Replay a recording at real speed through the same code path as live data.

**Then record** the labelled sessions: empty room (60 s), walking, sitting still, a fall onto the mat (several times, always from the same spot), and the ceiling fan running. These recordings drive every later step.

**Done when:** a recorded session replays through the same pipeline and gives the same output as when it was live.

### 4. Spec: `core` signal pipeline
- Clean up the signal: amplitudes, outlier clipping, smoothing.
- Compute a motion score per link (the spike's metric is the starting point).
- **"Exorcise the room" calibration:** record a 60 s empty-room baseline for each link.
- Zones: work out which links are disturbed. With 4 links this gives the room's quadrants.
- **Property-based tests (Kiro PBT):** the filters never output NaN, and the motion score rises as more disturbance is injected.

**Done when:** the property-based tests pass, and the recordings show a clear difference between empty, still and walking.

### 5. Spec: `core` state machine
States: `empty → present → moving → possible_fall → fall`, plus `inactive_too_long`.
- **Fall rule:** a sharp burst on several links, then stillness for N seconds, so it becomes `possible_fall`. If there's still no movement after M more seconds, it becomes `fall`.
- **Inactivity rule:** present, but no movement for 20 minutes. Make the time configurable, so the demo can use a short value.
- Every threshold lives in one config file, so the MCP server (step 7) can change it.

**Done when:** each fall recording triggers `fall`, and the walk and fan recordings never do.

### 6. Hook: replay regression
A Kiro hook that runs on every saved change to `core/`. It replays every file in `recordings/` and fails if a known fall is missed or a false alarm appears.

**Done when:** changing a threshold to something bad makes the hook go red.

### 7. MCP server: "spirit box" (the signature demo moment)
Tools the Kiro agent can call:
- `get_live_stats`: motion score per link, the current state and zone.
- `list_recordings` / `replay(recording)`: run a recording and return the events it produced.
- `get_thresholds` / `set_thresholds`: read and change the detection config.

**Demo:** in Kiro chat, ask "the fan is causing false alarms, fix it". The agent replays the fan recording, raises a threshold, and confirms the falls are still caught. **Film this.**

**Done when:** Kiro chat can read live stats and change a threshold through MCP.

### 8. Spec: Grandma Ghost app (`apps/grandma-ghost`)
- **Haunted floor plan:** a ghost glows in the active zone.
- **Live waveform panel:** one line per link.
- **Tombstone event log:** "Fell near bed, 14:02".
- **Calibration screen:** "Exorcise the room", with a spooky 60 s countdown.
- **On-screen alarm** with sound when a fall is detected.
- **Telegram alert** to a family member on a fall or inactivity. The bot token goes in a gitignored `.env`.
- **Live/Replay toggle:** live reads the boards, replay plays `recordings/`.

**Done when:** a real fall on the mat produces the ghost animation, a tombstone, the on-screen alarm and a Telegram message, in that order.

### 9. Hosting the replay demo
- Deploy the app in replay mode only, with no hardware needed and no raw CSI exposed: only the derived scores ship.
- It must stay up until **Jan 29, 2027**. Pick a free or cheap host that doesn't go to sleep.

**Done when:** the public URL works in a private browser window on a phone.

### 10. Dropped: Cold Room Guardian
Decided Nov 26: the entry is Costume Contest with one app. Cold Room Guardian appears in the README as another possible use of the same sensing, and nowhere else. It is not built and not in the demo. Use the time for spooky polish, hosting and the write-up.

### 11. Agent and power (write-up items)
- Use at least one **Kiro power** and one **custom agent**. For example, a "ghost hunter" agent that runs the replay suite and summarises any regressions.
- Use the Kiro CLI at least once, such as running the replay suite from a terminal, so the write-up can mention it.

### 12. Submission
- **Demo video, under 3 minutes:** a ghost follows you with no camera, you fall, the phone buzzes, then the spirit-box MCP tuning moment.
- **Kiro write-up:** steering, specs, hooks, MCP, PBT, powers, agents, and the IDE and CLI.
- **README:** setup instructions, plus the tools disclosure: the spike was written with Claude Code, and the product code was built through Kiro.
- **Blog post** that mentions the Kiroween 2026 hackathon, and a **social post** that starts with `#KiroweenHackathon26`, written by you.
- **Startup prize:** check the Uvera site and your LinkedIn.

---

## Schedule

| Date | Steps |
|---|---|
| Credits day (≈ Nov 24) | 1 steering, 2 firmware |
| Nov 25 | 3 ingest, then record the sessions |
| Nov 26 | 4 pipeline and PBT |
| Nov 27 | 5 state machine, 6 hook |
| Nov 28 | 7 spirit-box MCP |
| Nov 29–30 | 8 Grandma Ghost UI and Telegram |
| Dec 1 | 9 hosting, spooky polish. **Kiro credit request deadline is 12:00 PM PT.** |
| Dec 2–3 | 11 agent and power, 12 video and write-up |
| **Dec 4 (evening IST)** | **Submit.** The hard deadline is Dec 4, 2:00 PM PT (Dec 5, 3:30 AM IST). |

**If behind schedule, cut in this order:** the custom agent, the waveform panel, the calibration screen animation. **Never cut:** replay mode, the fall alert, or the MCP moment.

## Open decisions (settle in the step's spec)
- **4 boards on USB serial** need 4 USB ports or a powered hub. If ports run short, switch the firmware to send UDP to the hub over Wi-Fi (step 2).
- **UI stack:** plain HTML/JS served by the Python hub is the least work. Choose in step 8.
- **Host for replay mode** (step 9).

---

## Appendix: flashing boards C and D
The Arduino IDE Upload button fails on C and D. Esptool's helper program won't run on these boards, and the connection drops during long writes. This method works (tested Nov 22):

1. Compile to files:
   `arduino-cli compile --fqbn esp32:esp32:esp32 --output-dir build <sketch folder>`
2. Split the app into 64 KB pieces:
   `split -b 65536 -d -a 2 build/<sketch>.ino.bin part_`
3. **Hold BOOT the whole time** and tap EN once. Then flash each piece in its own run, retrying on failure:
   `uvx --from esptool esptool --port COMx --no-stub write-flash <offset> <file>`

| File | Offset |
|---|---|
| `<sketch>.ino.bootloader.bin` | `0x1000` |
| `<sketch>.ino.partitions.bin` | `0x8000` |
| `boot_app0.bin` (from `Arduino15/packages/esp32/hardware/esp32/3.3.11/tools/partitions/`) | `0xe000` |
| `part_00`, `part_01`, … | `0x10000`, `0x20000`, … (add `0x10000` per piece) |

It takes about 3 minutes per board. Good first task for Kiro in step 2: turn this into a script.
