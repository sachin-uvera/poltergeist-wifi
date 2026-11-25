# Repo structure

```
poltergeist-wifi/
├── .kiro/
│   ├── steering/       # product.md, privacy.md, tech.md, structure.md
│   ├── specs/          # one spec per component (firmware, core, apps)
│   └── hooks/          # replay regression hook and others
│
├── firmware/
│   └── csi_node/       # production ESP32 firmware (built from spike/csi_rx)
│                       # secrets.h is gitignored; copy from secrets.h.example
│
├── core/               # shared sensing skeleton, imported by both apps
│   ├── ingest.py       # reads all 4 serial ports, tags packets with board MAC
│   ├── pipeline.py     # signal cleaning, motion score, zone logic
│   ├── state.py        # state machine: empty → present → moving → fall / inactive
│   ├── replay.py       # plays a recordings/ CSV through the same code path as live
│   └── config.toml     # all thresholds and tunable values (read by MCP server)
│
├── apps/
│   ├── grandma-ghost/  # Grandma Ghost web app
│   │                   # haunted floor plan, tombstone log, Telegram alert
│   │                   # imports only from core/
│   └── cold-room-guardian/   # Cold Room Guardian web app
│                             # room status, locking-button alarm
│                             # imports only from core/
│
├── recordings/         # labelled CSI sessions used for replay and regression tests
│                       # naming: <label>_<YYYYMMDD>.csv
│                       # labels: empty, walking, sitting, fall, fan
│
├── docs/
│   ├── KIRO_WORKPLAN.md   # step-by-step build plan
│   ├── architecture.md    # system diagram and design notes
│   └── video_script.md    # demo video script
│
├── spike/              # hardware feasibility test — kept as evidence, not production
│   ├── csi_rx/         # Arduino sketch (secrets.h gitignored)
│   └── live_plot.py    # real-time CSI graph over serial
│
├── PROGRESS.md         # running log of decisions, gotchas, and remaining work
└── README.md           # setup instructions and tools disclosure
```

## Rules for each folder

**`.kiro/`** — never add to `.gitignore`. This folder is the judges' evidence that Kiro was used throughout the build.

**`core/`** — no app-specific logic here. Both apps import from `core/`; `core/` imports from neither app.

**`apps/`** — each app folder is self-contained except for its `core/` imports. No cross-imports between `grandma-ghost` and `cold-room-guardian`.

**`firmware/`** — Arduino sketches only. The hub-side Python never lives here.

**`recordings/`** — checked into the repo. These are the regression dataset and the source material for the public replay demo. File names follow `<label>_<YYYYMMDD>.csv`. Do not store raw CSI amplitudes; store the derived values the pipeline produces.

**`spike/`** — read-only after the hardware feasibility phase. Do not refactor or import from it.
