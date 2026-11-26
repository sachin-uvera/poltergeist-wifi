"""Check the Telegram alert path with a stubbed network call (no real message is sent)."""
import importlib.util
import os
import sys
import time
import urllib.parse
from pathlib import Path

here = Path(__file__).parent
spec = importlib.util.spec_from_file_location("gg_app", here / "app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

from core.state import Event

sent = []


class FakeResp:
    status = 200
    def __enter__(self): return self
    def __exit__(self, *a): return False


def fake_urlopen(req, timeout=0):
    sent.append((req.full_url, urllib.parse.parse_qs(req.data.decode())))
    return FakeResp()


app.urllib.request.urlopen = fake_urlopen
os.environ["TELEGRAM_BOT_TOKEN"] = "TESTTOKEN"
os.environ["TELEGRAM_CHAT_ID"] = "42"

for kind in ("possible_fall", "fall", "inactive", "moving"):
    app._on_event(Event(kind=kind, state=kind, wall_ms=0, active_links=["A/CSI-B"], note=""))
time.sleep(0.5)

print("messages sent:", len(sent))
for url, body in sent:
    print(" ", url.split("/bot")[0], "| chat", body["chat_id"], "|", body["text"][0])
