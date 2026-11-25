# Product: Poltergeist

Poltergeist is a Wi-Fi CSI sensing system that detects human presence, movement, and falls — no cameras, no microphones.

## Tagline
> Your Wi-Fi is watching over you. No cameras.

## Two apps, one sensing skeleton

The same core signal pipeline powers both apps.

| App | Purpose | Audience |
|---|---|---|
| **Grandma Ghost** | Detects falls and prolonged inactivity in an elder's room | Family caregivers |
| **Cold Room Guardian** | Detects a worker left inside a cold room when it is locked | Workplace safety |

**Build order:** Grandma Ghost first. Cold Room Guardian gets a thin version at the end (step 10 of the work plan). Skeleton Crew category requires both app folders.

## v1 scope (what is in and what is out)

**In:**
- Fall detection and inactivity alert (Grandma Ghost)
- Still-inside alarm triggered by a "locking" button (Cold Room Guardian)
- On-screen alarm and Telegram notification
- Replay mode: recorded sessions can be played back through the same code path as live data (mandatory — judges do not have the hardware)
- MCP "spirit box" server for live stats and threshold tuning from Kiro chat

**Out (v1):**
- LEDs or buzzer on the boards
- Trained ML model (detection uses configurable thresholds)
- Multiple buildings or remote locations

## Replay mode is mandatory
Every release must work in replay mode. The hosted public demo runs in replay mode only, with no hardware, and must stay up until Jan 29, 2027.
