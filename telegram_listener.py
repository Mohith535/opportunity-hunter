"""
Telegram listener (Phase C — the two-way half). FREE.

Run this on your laptop:   python telegram_listener.py

It long-polls Telegram for button taps from the digest. When you tap
"✅ Plan in TaskFlow" on an opportunity, it finds that item (by dedup key, from
data/history.json) and creates the TaskFlow task — locally, where TaskFlow lives.

Telegram queues taps for ~24h, so taps made while this isn't running are handled
the next time you start it. Also supports:
  /start  → prints your chat id (put it in .env as TELEGRAM_CHAT_ID)
  /top    → your current top opportunities

Stop with Ctrl+C.
"""

import html
import time
from datetime import date

import requests

import config
import store
from filters import policy
from models import Opportunity
from taskflow import integration
from util import log


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"


def _history_items() -> dict:
    """Every opportunity ever logged, keyed by dedup_key (latest wins)."""
    data = store._load(config.HISTORY_FILE)
    out: dict = {}
    for run in data.get("runs", []):
        for d in run.get("items", []):
            it = Opportunity(
                title=d.get("title", ""), url=d.get("url", ""),
                source=d.get("source", ""), description=d.get("description", ""),
                tags=d.get("tags", []), native_id=d.get("native_id"),
            )
            it.score = d.get("score", 0)
            it.ai_score = d.get("ai_score", -1)
            it.ai_summary = d.get("ai_summary", "")
            it.action_plan = d.get("action_plan", [])
            dl = d.get("deadline")
            if dl:
                try:
                    it.deadline = date.fromisoformat(dl)
                except ValueError:
                    pass
            out[it.dedup_key()] = it
    return out


def _post(method: str, **payload) -> None:
    try:
        requests.post(_api(method), json=payload, timeout=config.REQUEST_TIMEOUT)
    except requests.RequestException as e:
        log(f"[telegram-listener] {method} failed: {e}", level="WARN")


def _answer(cb_id: str, text: str = "") -> None:
    _post("answerCallbackQuery", callback_query_id=cb_id, text=text)


def _send(chat_id, text: str) -> None:
    _post("sendMessage", chat_id=chat_id, text=text,
          parse_mode="HTML", disable_web_page_preview=True)


def _handle_plan(key: str, cb: dict) -> None:
    chat_id = cb["message"]["chat"]["id"]
    it = _history_items().get(key)
    if not it:
        _answer(cb["id"], "Couldn't find that item (it may have aged out).")
        return
    if not integration.is_available():
        _answer(cb["id"], "TaskFlow isn't available on this machine.")
        return
    ok = integration.dump(it, policy.effective_score(it))
    _answer(cb["id"], "Added to TaskFlow ✅" if ok else "Dump failed — check logs")
    if ok:
        _send(chat_id, f"✅ Added to TaskFlow:\n<b>{html.escape(it.title)}</b>")
        if it.action_plan:
            steps = "\n".join(f"{i}. {html.escape(s)}"
                              for i, s in enumerate(it.action_plan, 1))
            _send(chat_id, f"<b>Suggested plan</b>\n{steps}")


def _handle_message(msg: dict) -> None:
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    if text.startswith("/start"):
        _send(chat_id,
              "👋 <b>Opportunity Hunter</b> is connected.\n"
              f"Your chat id is <code>{chat_id}</code> — put it in .env as "
              "<code>TELEGRAM_CHAT_ID</code> to receive digests.\n"
              "Send /top to see your top opportunities.")
        print(f"[chat id] {chat_id}")
    elif text.startswith("/top"):
        items = sorted(_history_items().values(),
                       key=policy.effective_score, reverse=True)[:5]
        if not items:
            _send(chat_id, "No opportunities logged yet — run the hunt first.")
            return
        lines = [f"{policy.effective_score(i)}/10 — <b>{html.escape(i.title[:60])}</b>"
                 for i in items]
        _send(chat_id, "<b>Top opportunities</b>\n" + "\n".join(lines))


def run() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN not set. Create a bot via @BotFather, add it to .env.")
        return
    print("Telegram listener running — tap buttons in your digest. Ctrl+C to stop.")
    offset = None
    try:
        while True:
            try:
                resp = requests.get(_api("getUpdates"),
                                    params={"timeout": 30, "offset": offset},
                                    timeout=40)
                resp.raise_for_status()
                for upd in resp.json().get("result", []):
                    offset = upd["update_id"] + 1
                    if "callback_query" in upd:
                        cb = upd["callback_query"]
                        data = cb.get("data", "")
                        if data.startswith("plan:"):
                            _handle_plan(data[5:], cb)
                        else:
                            _answer(cb["id"])
                    elif "message" in upd:
                        _handle_message(upd["message"])
            except requests.RequestException as e:
                log(f"[telegram-listener] poll error: {e}", level="WARN")
                time.sleep(5)
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    run()
