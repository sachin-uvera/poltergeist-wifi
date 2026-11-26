"""
Check the alarm sound behaves under the browser rule "no sound before the user clicks".

    uv run --with playwright python apps/grandma-ghost/_sound_check.py [BASE_URL]

Runs the replay demo in Edge with autoplay blocked, and counts every tone the page starts
(by wrapping OscillatorNode.start) together with whether sound could actually play at that
moment. Two visitors:
  1. never clicks before the alarm, then presses Acknowledge  -> no siren at all, before or after
  2. presses "Enable sound" first                              -> siren on the alarm, cut on Acknowledge
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8092"

SPY = """
window.__tones = [];
const start0 = OscillatorNode.prototype.start;
OscillatorNode.prototype.start = function (when) {
  window.__tones.push({ctx: this.context.state, freq: this.frequency.value, at: performance.now()});
  return start0.apply(this, arguments);
};
"""

problems = []


def check(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        problems.append(what)


def tones(page, since=0.0):
    return page.evaluate(f"window.__tones.filter(t => t.at > {since})")


with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="msedge", headless=True,
                                 args=["--autoplay-policy=user-gesture-required"])

    # ── visitor 1: no click before the alarm ─────────────────────────────────
    print("== visitor 1: does not click before the alarm ==")
    ctx = browser.new_context(viewport={"width": 1280, "height": 760})
    ctx.add_init_script(SPY)
    page = ctx.new_page()
    page.goto(f"{BASE}/?rec=fall&speed=6")
    page.wait_for_function("document.getElementById('alert-bar').classList.contains('show')", timeout=30000)
    page.wait_for_timeout(800)
    check(len(tones(page)) == 0, f"no tone scheduled while the browser keeps the page silent ({tones(page)})")
    btn = page.evaluate("({text: document.getElementById('sound-btn').textContent, "
                        "nag: document.getElementById('sound-btn').classList.contains('nag')})")
    check("Enable sound" in btn["text"] and btn["nag"], f"sound button asks to be pressed during the alarm {btn}")
    t_click = page.evaluate("performance.now()")
    page.click("#ack-btn")
    page.wait_for_timeout(1500)
    late = [t for t in tones(page, t_click) if t["freq"] in (440, 880)]
    check(not late, f"no siren after pressing Acknowledge ({late})")
    ctx.close()

    # ── visitor 2: enables sound first ───────────────────────────────────────
    print("== visitor 2: presses Enable sound first ==")
    ctx = browser.new_context(viewport={"width": 1280, "height": 760})
    ctx.add_init_script(SPY)
    page = ctx.new_page()
    page.goto(f"{BASE}/?rec=fall&speed=6")
    page.wait_for_timeout(500)
    page.click("#sound-btn")
    page.wait_for_timeout(400)
    btn = page.evaluate("document.getElementById('sound-btn').textContent")
    check("Sound on" in btn, f"button shows sound is on ({btn!r})")
    check(any(t["freq"] == 660 and t["ctx"] == "running" for t in tones(page)), "a short confirmation tone played")
    page.wait_for_function("document.getElementById('alert-bar').classList.contains('show')", timeout=30000)
    page.wait_for_timeout(600)
    siren = [t for t in tones(page) if t["freq"] in (440, 880)]
    check(len(siren) > 0 and all(t["ctx"] == "running" for t in siren),
          f"siren plays on the alarm, with sound running ({len(siren)} tones)")
    left = page.evaluate("sirenNodes.length")
    page.click("#ack-btn")
    page.wait_for_timeout(300)
    check(left > 0 and page.evaluate("sirenNodes.length") == 0, "Acknowledge stops the siren that is playing")
    ctx.close()
    browser.close()

print("RESULT:", "all checks passed" if not problems else f"{len(problems)} problem(s)")
sys.exit(1 if problems else 0)
