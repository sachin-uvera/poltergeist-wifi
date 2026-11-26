# Poltergeist: Grandma Ghost

> Your Wi-Fi is watching over you. No cameras.

Kiroween 2026 entry, **Costume Contest**.

**Live demo, no hardware needed: https://sachin-uvera.github.io/poltergeist-wifi/**

Grandma Ghost watches over an elderly person's room using only Wi-Fi signals. Four ESP32 boards in the room corners measure how the signal between each pair changes. A person walking through or lying on the floor disturbs those signals, and the app turns that into a haunted map: a ghost appears where the person is, a tombstone log records what happened, and the family gets a Telegram message when someone falls or has not moved for too long.

No cameras and no microphones. Raw Wi-Fi data never leaves the hub; only scores and events reach the screen and Telegram.

## How it works

```
4 ESP32 boards ──UDP──▶ hub (Python) ──▶ browser UI (ghost map, scores, tombstone log)
 ping each other        clean → score →         └──▶ Telegram alert on fall / inactivity
                        zones → state machine
```

States: `empty → present → moving → possible_fall → fall`, plus `inactive_too_long`. Detection uses configurable thresholds in `core/config.toml`, not a trained model.

Every recording in `recordings/` can be replayed through the same code path as live data, so the demo works without the hardware.

## Run it

Needs [uv](https://docs.astral.sh/uv/). Replay needs no hardware:

```
uv run --with websockets --with python-dotenv --with numpy apps/grandma-ghost/app.py --replay fall
```

Then open http://localhost:8080.

With the boards on the same Wi-Fi as your laptop, add `--live` instead of `--replay fall`, then press **Exorcise the room** with the room empty to calibrate.

Hosted replay demo: the public demo at the link above is a static site in `site/`, published to GitHub Pages by `.github/workflows/pages.yml`. It has no server and needs no hardware. It plays back pre-computed files that hold only motion scores, room states, ghost positions and event text, never raw Wi-Fi data. To rebuild it after changing the pipeline (needs the local `recordings/`, which are not in the repo):

```
uv run --with numpy python apps/grandma-ghost/export_demo.py
```

Telegram alerts: copy `apps/grandma-ghost/.env.example` to `.env`, add a bot token from @BotFather, then run `apps/grandma-ghost/telegram_setup.py` to find your chat ID and send a test alert. The `.env` file is gitignored.

Tests:

```
uv run --with pytest --with numpy --with hypothesis pytest core/tests -v
```

## Repo layout

```
.kiro/             steering, specs, hooks, MCP config (how the project was built with Kiro)
core/              sensing: ingest, pipeline, state machine, replay, "spirit box" MCP server
apps/grandma-ghost the web app
firmware/csi_node  production ESP32 firmware (spec and sketch)
recordings/        labelled sessions: empty, walking, sitting, fall, ceiling fan
spike/             the hardware feasibility test, kept as evidence
docs/              work plan and notes
```

## Other possible uses (not part of this submission)

The sensing in `core/` has no app-specific code, so it could serve other places where someone must not be left alone or unnoticed. One example is a worker left inside a cold room: the same "someone is still in the room" signal, checked when the door is locked. We did not build this, and it is not in the demo.

## Tools disclosure

- The hardware feasibility test in `spike/` was written with Claude Code as a co-pilot.
- The product code (`core/`, `apps/`, `firmware/csi_node`) was built through Kiro specs, steering and hooks. The record is in `.kiro/`.
- The ghost sprites in `apps/grandma-ghost/static/` are built from an image supplied by the author, using `make_ghost_image.py`.

## Known limits

- With four boards the system cannot count people in general. It shows a second ghost only when two people disturb opposite walls.
- Where the ghost stands along a board-to-board line is a coarse guess.
- Fall detection was tuned on short recordings made in one room. It has not been tested with a real fall on a mat by an independent person.

## License

MIT. See `LICENSE`.
