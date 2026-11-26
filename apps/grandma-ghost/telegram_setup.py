"""
apps/grandma-ghost/telegram_setup.py – check the Telegram bot and find the chat ID.

    uv run --with python-dotenv --with numpy --with websockets apps/grandma-ghost/telegram_setup.py
    uv run --with python-dotenv --with numpy --with websockets apps/grandma-ghost/telegram_setup.py --send

Reads TELEGRAM_BOT_TOKEN (and TELEGRAM_CHAT_ID if set) from apps/grandma-ghost/.env.
Never prints the token.

1. Checks the token with Telegram (getMe) and shows the bot's name.
2. Lists the chats that have messaged the bot, with their chat IDs (getUpdates).
   Send the bot any message first, or it has no chats to list.
3. With --send: sends a test alert through the hub's own send code, so a success
   here means real alerts will arrive too.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
ENV = HERE / ".env"


def api(token: str, method: str) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read())
        except Exception:
            return {"ok": False, "description": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "description": f"{type(exc).__name__} (no internet?)"}


def main() -> int:
    if not ENV.exists():
        print(f"No {ENV.name} found. Copy .env.example to .env in {HERE} and fill in the token.")
        return 1
    from dotenv import load_dotenv
    load_dotenv(ENV)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or "your-" in token:
        print("TELEGRAM_BOT_TOKEN is not set in .env. Get one from @BotFather (/newbot).")
        return 1

    me = api(token, "getMe")
    if not me.get("ok"):
        print("Token rejected by Telegram:", me.get("description"))
        print("Copy the whole token from @BotFather, with no quotes or spaces.")
        return 1
    bot = me["result"]
    print(f"Token OK: bot @{bot.get('username')} ({bot.get('first_name')})")

    updates = api(token, "getUpdates")
    chats: dict[str, str] = {}
    for u in updates.get("result", []):
        msg = u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}
        chat = msg.get("chat") or {}
        if "id" in chat:
            name = chat.get("title") or " ".join(
                x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("username", "")
            chats[str(chat["id"])] = f"{name} ({chat.get('type')})"
    if chats:
        print("Chats that have messaged the bot:")
        for cid, name in chats.items():
            mark = "  <- TELEGRAM_CHAT_ID" if cid == chat_id else ""
            print(f"  {cid:>16}  {name}{mark}")
    else:
        print(f"No chats yet. Open Telegram, find @{bot.get('username')}, press Start or send it "
              "any message, then run this again.")

    if not chat_id or "your-" in chat_id:
        print("TELEGRAM_CHAT_ID is not set in .env. Put one of the IDs above there.")
        return 1 if "--send" in sys.argv else 0

    if "--send" in sys.argv:
        # Use the hub's real sender so this tests exactly what alerts will use
        spec = importlib.util.spec_from_file_location("gg_app", HERE / "app.py")
        app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(app)
        from datetime import datetime
        ok = app._send_telegram(f"Poltergeist: test alert, {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("Test message sent. Check Telegram." if ok else "Test message failed (see the warning above).")
        return 0 if ok else 1

    print("Setup looks complete. Run again with --send to send a test alert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
