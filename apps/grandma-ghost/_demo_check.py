"""
Open the hosted demo in a real browser (Edge via Playwright) as a phone and as a desktop.

    uv run --with playwright python apps/grandma-ghost/_demo_check.py [BASE_URL] [OUT_DIR]

Checks: no console errors, no sideways scrolling on a phone, the ghost appears, the log fills,
the alarm shows on a possible fall, Acknowledge clears it, and Restart replays. Saves screenshots.
Uses the installed Edge, so nothing is downloaded.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else Path.home() / "AppData/Local/Temp/gg_shots")
OUT.mkdir(parents=True, exist_ok=True)

PHONE = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2,
         "is_mobile": True, "has_touch": True,
         "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
                       "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"}
DESKTOP = {"viewport": {"width": 1280, "height": 760}}

problems: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        problems.append(what)


def state(page) -> dict:
    return page.evaluate("""() => ({
        badge: document.getElementById('status-badge').textContent,
        events: [...document.querySelectorAll('#event-list .event-item')].map(e => e.textContent),
        ghosts: [...document.querySelectorAll('.ghost.visible')].length,
        down: [...document.querySelectorAll('.ghost.down')].length,
        alertBar: document.getElementById('alert-bar').classList.contains('show'),
        alarm: document.getElementById('alarm-overlay').classList.contains('show'),
        restart: getComputedStyle(document.getElementById('restart-btn')).display,
        links: document.querySelectorAll('#wave-list .wave-row').length,
        options: [...document.querySelectorAll('#rec-select option')].map(o => o.textContent),
        overflow: document.documentElement.scrollWidth - window.innerWidth,
        toggleHidden: getComputedStyle(document.querySelector('.toggle-wrap')).display === 'none',
        exorciseHidden: getComputedStyle(document.getElementById('exorcise-btn')).display === 'none',
    })""")


with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="msedge", headless=True)
    for name, cfg in (("phone", PHONE), ("desktop", DESKTOP)):
        print(f"\n== {name} ==")
        ctx = browser.new_context(**cfg)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("requestfailed", lambda r: errors.append("request failed: " + r.url))
        # name the URL behind any 404 (the console message alone does not say which file)
        page.on("response", lambda r: errors.append(f"HTTP {r.status}: {r.url}") if r.status >= 400 else None)

        # speed=6: the fall recording is 60 s, with the person arriving at 35 s and the alert at 50 s
        page.goto(f"{BASE}/?rec=fall&speed=6", wait_until="load")
        page.wait_for_timeout(1500)
        s = state(page)
        check(len(s["options"]) >= 3, f"recording list has {len(s['options'])} entries: {s['options']}")
        check(s["toggleHidden"] and s["exorciseHidden"], "Live toggle and Exorcise button are hidden")
        check(s["links"] == 12, f"12 link rows ({s['links']})")
        page.screenshot(path=str(OUT / f"{name}_1_start.png"), full_page=True)

        page.wait_for_function("document.querySelectorAll('.ghost.visible').length > 0", timeout=15000)
        page.wait_for_timeout(1500)
        s = state(page)
        check(s["ghosts"] >= 1, "a ghost appeared when someone entered")
        check(any("Someone entered" in e for e in s["events"]), f"log has 'Someone entered': {s['events']}")
        page.screenshot(path=str(OUT / f"{name}_2_moving.png"), full_page=True)

        page.wait_for_function("document.getElementById('alert-bar').classList.contains('show')", timeout=20000)
        page.wait_for_timeout(1200)
        s = state(page)
        check(s["alarm"] and s["alertBar"], "alarm overlay and alert bar show on possible fall")
        check(s["down"] >= 1, "the ghost lies down (red) on the alarm")
        # the whole sprite must sit inside the room (it was cut off on phones before)
        box = page.evaluate("""() => {
            const room = document.getElementById('room').getBoundingClientRect();
            return [...document.querySelectorAll('.ghost.visible')].map(g => {
                const r = g.querySelector('.sprite.red').getBoundingClientRect();
                return {left: r.left - room.left, top: r.top - room.top,
                        right: room.right - r.right, bottom: room.bottom - r.bottom};
            });
        }""")
        check(all(min(b.values()) >= -1 for b in box), f"fallen ghost fully inside the room {box}")
        bar = page.evaluate("""() => {
            const b = document.getElementById('alert-bar').getBoundingClientRect();
            const h = document.querySelector('header').getBoundingClientRect();
            return {barBottom: b.bottom, headerTop: h.top, headerBottom: h.bottom};
        }""")
        if name == "phone":
            check(bar["barBottom"] <= bar["headerTop"] + 1 or bar["headerTop"] >= bar["barBottom"] - 1,
                  f"alert bar does not cover the title on a phone {bar}")
        check("POSSIBLE FALL" in s["badge"], f"badge says possible fall: {s['badge']!r}")
        check(s["restart"] != "none", "Restart replay button is offered")
        page.screenshot(path=str(OUT / f"{name}_3_alarm.png"), full_page=True)

        page.click("#ack-btn")
        page.wait_for_timeout(600)
        s = state(page)
        check(not s["alertBar"] and not s["alarm"], "Acknowledge clears the alert bar and the overlay")
        check(s["ghosts"] == 0, "Acknowledge clears the ghost")
        check(any("acknowledged" in e.lower() for e in s["events"]), "log records the acknowledgement")
        page.screenshot(path=str(OUT / f"{name}_4_acknowledged.png"), full_page=True)

        # pick another recording and play it through the dropdown + button
        page.select_option("#rec-select", index=1)
        page.click("#replay-btn")
        page.wait_for_timeout(2500)
        s = state(page)
        check(s["badge"].startswith("replay"), f"another recording plays from the dropdown: {s['badge']!r}")
        check(s["events"] == [] or not any("acknowledged" in e.lower() for e in s["events"]),
              "log was cleared for the new recording")

        if name == "phone":
            check(s["overflow"] <= 0, f"no sideways scrolling on a phone (overflow {s['overflow']} px)")
        check(not errors, f"no console or network errors {sorted(set(errors))}")
        ctx.close()
    browser.close()

print("\nscreenshots in", OUT)
print("RESULT:", "all checks passed" if not problems else f"{len(problems)} problem(s): {problems}")
sys.exit(1 if problems else 0)
