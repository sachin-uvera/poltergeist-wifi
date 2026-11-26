# Product: Poltergeist

Poltergeist is a Wi-Fi CSI sensing system that detects human presence, movement, and falls — no cameras, no microphones.

## Tagline
> Your Wi-Fi is watching over you. No cameras.

## One app on a reusable sensing skeleton

| App | Purpose | Audience |
|---|---|---|
| **Grandma Ghost** | Detects falls and prolonged inactivity in an elder's room | Family caregivers |

Grandma Ghost is the only app in the submission. The entry is for the **Costume Contest** category (one app with a haunting UI), not Skeleton Crew.

`core/` has no app-specific logic, so the same sensing could serve other uses, such as a worker left inside a cold room. The README mentions that as a possible other use only. It is not built, not in the demo, and has no app folder. Do not add a second app.

## v1 scope (what is in and what is out)

**In:**
- Fall detection and inactivity alert (Grandma Ghost)
- On-screen alarm and Telegram notification
- Replay mode: recorded sessions can be played back through the same code path as live data (mandatory — judges do not have the hardware)
- MCP "spirit box" server for live stats and threshold tuning from Kiro chat

**Out (v1):**
- LEDs or buzzer on the boards
- Trained ML model (detection uses configurable thresholds)
- Multiple buildings or remote locations
- A second app (Cold Room Guardian was dropped on Nov 26)

## Replay mode is mandatory
Every release must work in replay mode. The hosted public demo runs in replay mode only, with no hardware, and must stay up until Jan 29, 2027.
