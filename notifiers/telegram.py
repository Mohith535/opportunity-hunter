"""
Telegram notifier (Phase C — two-way, FREE).

Sends the digest to a Telegram chat with inline buttons. Unlike ntfy (one-way),
Telegram lets you tap a button and have the agent ACT on it — the tap is handled
by telegram_listener.py (which runs locally, because TaskFlow is local-only).

Free forever: no account cost, no card. Setup:
  1. Open @BotFather in Telegram -> /newbot -> get the bot token.
  2. Message your new bot once (say "hi") so it can message you back.
  3. Put TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID in .env (the listener prints your
     chat id on first run, or visit /getUpdates).

Best-effort: any failure is logged, never raised — the run never breaks.
"""

import json

import requests

import config
from util import log


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"


def is_configured() -> bool:
    return config.telegram_configured()


def send_telegram(text: str, buttons: list | None = None,
                  parse_mode: str = "HTML") -> bool:
    """Send a message to the configured chat.

    text:    message body (HTML by default — escape <,>,& in dynamic parts).
    buttons: inline keyboard as a list of rows; each row a list of button dicts,
             e.g. [[{"text": "Open", "url": "..."},
                    {"text": "Plan", "callback_data": "plan:abc123"}]].
    Returns True on success, False on any failure (logged, never raised).
    """
    if not is_configured():
        return False
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    try:
        resp = requests.post(_api("sendMessage"), json=payload,
                             timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        log(f"[telegram] send failed: {e}", level="WARN")
        return False


if __name__ == "__main__":
    ok = send_telegram(
        "🎯 <b>Opportunity Hunter</b> — Telegram works! 🚀\n"
        "Tap a button below to test two-way control.",
        buttons=[[
            {"text": "🔗 Open repo", "url": "https://github.com/Mohith535/opportunity-hunter"},
            {"text": "✅ Test callback", "callback_data": "plan:test12345678"},
        ]],
    )
    print("sent:", ok, "| configured:", is_configured())
