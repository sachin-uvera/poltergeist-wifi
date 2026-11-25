# Privacy

## Core principle
Raw CSI data never leaves the hub. Only derived events and motion scores are transmitted to the UI, stored in logs, or sent via Telegram.

## Data boundaries

| Data | Stays on hub | Sent outside |
|---|---|---|
| Raw CSI amplitudes | ✅ yes | ❌ never |
| Motion score per link | ✅ yes | UI and MCP only (local) |
| State (empty / present / moving / fall) | ✅ yes | UI, Telegram alert, MCP |
| Event log (tombstones) | ✅ yes | UI display only |
| Telegram messages | — | Event description only (e.g. "Fall detected near bed, 14:02"). No raw data. |

## Consent comes first
The system only runs when the monitored person has agreed. Consent must be obtained before the first session starts. This requirement applies to both apps.

## No surveillance hardware
No cameras. No microphones. The only sensor is the Wi-Fi CSI data from ESP32 boards and the home router — signals that exist in the environment regardless.

## Credentials and secrets
- Wi-Fi credentials stay in a gitignored `secrets.h` on the firmware side.
- The Telegram bot token stays in a gitignored `.env` on the hub side.
- Neither is ever committed to the repository.

## Recordings
Labelled session recordings in `recordings/` contain derived CSI values from a controlled test environment (the developer's own space). They are used for regression testing and the public replay demo. No personal data is included.
