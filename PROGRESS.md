# Poltergeist: progress log

> Your Wi-Fi is watching over you. No cameras.

Kiroween 2026 entry, category **Skeleton Crew**: one Wi-Fi sensing skeleton powering two apps, **Grandma Ghost** (elder fall and inactivity alerts) and **Cold Room Guardian** (a worker left inside a cold room).

**Submission deadline:** Dec 4, 2026, 2:00 PM PT (Dec 5, 3:30 AM IST). Last updated Nov 20, 2026.

---

## Done

### Setup
- [x] Joined the hackathon on Devpost and requested Kiro credits
- [x] Checked Kiro in India: supported; Claude Sonnet 5.5 has no regional limit
- [x] Created this public repo with an MIT license (the rules require public and open source; no specific license required)
- [x] Created the folder skeleton (see [Repo layout](#repo-layout))

### Hardware feasibility (go/no-go): passed Nov 20, two days early
Two classic **ESP32-D0WD-V3 DevKit** boards (CH9102 USB chip), both checked with `esptool`.

| | Board A | Board B |
|---|---|---|
| Wi-Fi | 2.4 GHz, ch 6, −55 dBm | 2.4 GHz, ch 6, −57 dBm |
| CSI rate | 100 packets/s | 100 packets/s |
| CSI size | 128 values (64 subcarriers, LLTF) | same |
| Motion score, still | ~0.03 | ~0.03–0.05 |
| Motion score, walking between board and router | ~0.145 (≈5×) | ~0.35 (≈8–10×) |

Conclusion: a person walking through the link is clearly visible in the Wi-Fi signal. Each crossing shows up as a separate peak.

### Decisions so far
| Decision | Why |
|---|---|
| **Router mode**: each board pings the home router ~100×/s, and each reply carries CSI | No extra transmitter board needed. Two boards give two links, so two zones. |
| **Arduino core 3.3.11** instead of ESP-IDF | Already installed. CSI is compiled in (`CONFIG_ESP_WIFI_CSI_ENABLED=y`). Saves a 2 GB install. |
| **Own firmware** instead of esp-csi or ESPectre code | Original work for the rules, and no licence entanglement if this becomes a product |
| **No LEDs or buzzer in v1** | Minimal MVP. The alert is Telegram plus an on-screen alarm. LEDs only if time is left. |
| **Replay mode is mandatory** | Judges don't have our boards. The hosted app replays recorded sessions. |

### Gotchas we hit, so nobody hits them again
- **Board looks dead or stuck in download mode:** open the serial port with **DTR and RTS released** (`dtr=False`, `rts=False`). Asserting them holds these boards in reset ("waiting for download").
- **Board can't join Wi-Fi:** SSIDs are **case-sensitive**, and the ESP32 only sees **2.4 GHz** networks.
- **COM port number changes** depending on which USB socket is used. Identify boards by MAC address.

---

## Remaining

### Build: done in Kiro, so `.kiro/` is the evidence
- [ ] Steering files: product, privacy (no raw CSI leaves the hub, consent first), tech conventions
- [ ] Spec: `firmware/csi_node`, the production firmware built from the spike
- [ ] Spec: `core` signal pipeline (cleanup, motion score, 2-zone logic)
- [ ] Spec: state machine (empty, present, moving, possible fall, fall, inactive too long)
- [ ] Spec: Grandma Ghost app (haunted floor plan, tombstone event log, Telegram alert)
- [ ] Spec: Cold Room Guardian app (still-inside alarm, room-empty status)
- [ ] Hook: replay `recordings/` as regression tests on every change
- [ ] MCP server "spirit box": streams live CSI stats to the Kiro agent so it can tune thresholds (signature demo moment)
- [ ] Property-based tests on the signal math (no NaN; score rises with injected disturbance)
- [ ] Use at least one Kiro power and one custom agent (both are listed in the write-up topics)
- [ ] "Exorcise the room" calibration (60 s empty-room baseline)
- [ ] Record labelled sessions: empty, walking, sitting, fall, ceiling fan
- [ ] Replay mode, hosted publicly, and kept up until Jan 29, 2027 (end of judging)

### Submission
- [ ] Demo video: under 3 minutes, public on YouTube, no copyrighted music or third-party trademarks, shows the real hardware working
- [ ] Kiro write-up covering IDE/CLI/Web/Crew, custom agents, hooks, specs, steering, MCP, PBT, powers
- [ ] Text description: problem, audience, features (in English)
- [ ] README with setup instructions and a disclosure of pre-existing code and tools
- [ ] Blog post (dev.to or Hashnode) that mentions the **Kiroween 2026 hackathon**
- [ ] Social post that **starts with** `#KiroweenHackathon26`, about my favourite thing in Kiro (written by me, not AI)
- [ ] Best Startup Project: Uvera website live, LinkedIn up to date, founder confirmation on the form
- [ ] Devpost draft filled in early, **submitted by the evening of Dec 4 IST**

### Key dates
| Date | Milestone |
|---|---|
| ~~Nov 22~~ | ~~Hardware go/no-go~~ ✅ passed Nov 20 |
| Nov 28 | Decide: keep Skeleton Crew (2 apps) or fall back to Costume Contest (1 app) |
| Dec 1, 12:00 PM PT | Last day to request Kiro credits |
| Dec 2–3 | Record the video, write the submission |
| Dec 4 (evening IST) | Submit |

---

## Repo layout
```
.kiro/            steering, specs, hooks (Kiro's evidence; never gitignore it)
core/             shared sensing skeleton (ingest, pipeline, state machine, replay)
firmware/csi_node production ESP32 firmware
apps/grandma-ghost
apps/cold-room-guardian
recordings/       labelled CSI sessions for replay and regression tests
docs/             Kiro write-up, architecture, video script
spike/            hardware feasibility test (throwaway, kept as evidence)
```

## Run the spike
Needs the Arduino IDE (ESP32 core 3.3.x) and [uv](https://docs.astral.sh/uv/).
1. Copy `spike/csi_rx/secrets.h.example` to `secrets.h` and fill in a **2.4 GHz** SSID and password.
2. Flash `spike/csi_rx` to an ESP32 (board: *ESP32 Dev Module*).
3. Live graph: `uv run --with pyserial --with matplotlib --with numpy spike/live_plot.py COM4`
4. Walk between the board and the router: the line jumps.

## Tools disclosure
The `spike/` feasibility test was written with Claude Code as a co-pilot. Product code is built through Kiro specs, steering and hooks, recorded in `.kiro/`.
