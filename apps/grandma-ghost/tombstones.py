"""
apps/grandma-ghost/tombstones.py – how a state-machine event reads in the event log.

Shared by the hub (live and replay) and by export_demo.py, so the hosted demo shows
exactly the same wording as the real app.
"""
from __future__ import annotations

LABELS: dict[str, tuple[str, str]] = {
    "fall":          ("\U0001F480", "Fall detected"),            # skull
    "possible_fall": ("\u26A0\uFE0F", "Possible fall"),          # warning sign
    "inactive":      ("\U0001F56F", "Inactivity alert"),         # candle
    "present":       ("\U0001F464", "Someone entered"),          # silhouette
    "empty":         ("\U0001F3DA", "Room empty"),               # derelict house
    "moving":        ("\U0001F6B6", "Movement detected"),        # walking
    "reset":         ("\u2705", "Alert acknowledged"),           # check mark
}


def describe(event) -> dict:
    """Return {"icon", "label", "text", "kind", "note"} for a core.state.Event.

    `text` has no time in it. The caller adds ", HH:MM" (the hub uses the clock at the
    moment of the event; the hosted demo uses the visitor's clock).
    """
    icon, label = LABELS.get(event.kind, ("\U0001F47B", event.kind.replace("_", " ").title()))
    text = f"{icon} {label}"
    if event.active_links:
        text += f" near {', '.join(event.active_links)}"
    return {"icon": icon, "label": label, "text": text, "kind": event.kind, "note": event.note}
