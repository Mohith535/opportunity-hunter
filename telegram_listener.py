"""
Telegram listener (Phase C — the two-way half + Application Tracker). FREE.

Run this on your laptop:   python telegram_listener.py

It long-polls Telegram for button taps from the digest and remembers what you do
with each opportunity:
  ➕ Plan      → creates a TaskFlow task (status: planned)
  ✅ Applied   → marks it applied
  ⏭ Skip      → marks it skipped (stops nagging)
  ⏰ Remind    → revisit in a few days; the listener nudges you when it's due

It also handles:
  /start   → prints your chat id
  /top     → your current top opportunities
  /report  → the weekly "Regret Report" on demand

Once a day it fires due reminders, and every Sunday it sends the weekly report.
Telegram queues taps for ~24h, so taps made while this isn't running are handled
the next time you start it. Stop with Ctrl+C.
"""

import html
import json
import time
from datetime import date

import requests

import config
import store
import taste
import tracker
from filters import policy
from models import Opportunity
from taskflow import integration
from util import log

_last_tick: date | None = None


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


def _send(chat_id, text: str, buttons: list | None = None) -> None:
    payload = dict(chat_id=chat_id, text=text, parse_mode="HTML",
                   disable_web_page_preview=True)
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    _post("sendMessage", **payload)


def _tracker_buttons(key: str, url: str = "") -> list:
    row1 = []
    if url:
        row1.append({"text": "🔗 Open", "url": url})
    row1.append({"text": "➕ Plan", "callback_data": f"plan:{key}"})
    row1.append({"text": "✍️ Draft", "callback_data": f"draft:{key}"})
    return [row1,
            [{"text": "✅ Applied", "callback_data": f"applied:{key}"},
             {"text": "⏭ Skip", "callback_data": f"skip:{key}"},
             {"text": "⏰ Remind", "callback_data": f"remind:{key}"}]]


def _handle_plan(key: str, cb: dict) -> None:
    chat_id = cb["message"]["chat"]["id"]
    it = _history_items().get(key)
    if not it:
        _answer(cb["id"], "Couldn't find that item (it may have aged out).")
        return
    if integration.is_available() and integration.already_dumped(it):
        tracker.set_status(key, "planned", item=it)
        taste.relearn()
        _answer(cb["id"], "Already in TaskFlow ✅ — no duplicate created.")
        return
    local = integration.is_available()
    ok = integration.plan(it, policy.effective_score(it))
    if not ok:
        _answer(cb["id"], "Couldn't add it right now — try again shortly.")
        return
    tracker.set_status(key, "planned", item=it)
    taste.relearn()
    if local:
        _answer(cb["id"], "Added to TaskFlow ✅")
        _send(chat_id, f"✅ Added to TaskFlow:\n<b>{html.escape(it.title)}</b>")
    else:
        _answer(cb["id"], "Queued for TaskFlow ✅")
        _send(chat_id, "✅ Queued for TaskFlow — run <code>taskflow sync pull</code> "
                       f"(or tap ↓ in the dashboard):\n<b>{html.escape(it.title)}</b>")
    if it.action_plan:
        steps = "\n".join(f"{i}. {html.escape(s)}"
                          for i, s in enumerate(it.action_plan, 1))
        _send(chat_id, f"<b>Suggested plan</b>\n{steps}")


def _handle_status(action: str, key: str, cb: dict) -> None:
    it = _history_items().get(key)
    if action == "applied":
        tracker.set_status(key, "applied", item=it)
        taste.relearn()
        _answer(cb["id"], "Marked as applied ✅ — nice one!")
    elif action == "skip":
        tracker.set_status(key, "skipped", item=it)
        taste.relearn()
        _answer(cb["id"], "Skipped — I won't nag you about this.")
    elif action == "remind":
        tracker.set_status(key, "remind", item=it)
        _answer(cb["id"], f"I'll remind you in {config.TRACKER_REMIND_DAYS} days ⏰")


def _handle_draft(key: str, cb: dict) -> None:
    chat_id = cb["message"]["chat"]["id"]
    it = _history_items().get(key)
    if not it:
        _answer(cb["id"], "Couldn't find that item.")
        return
    # Answer the callback immediately (Telegram needs it fast), then do the slow
    # LLM call and send the draft as a follow-up message.
    _answer(cb["id"], "✍️ Drafting your application — one sec…")
    import draft
    text = draft.generate_draft(it)
    if text:
        _send(chat_id, f"✍️ <b>Draft — {html.escape(it.title[:60])}</b>\n\n"
                       f"{html.escape(text)}\n\n<i>Tweak it and send. Good luck. 🚀</i>")
    else:
        _send(chat_id, "Couldn't generate a draft right now (LLM busy) — try again shortly.")


def _handle_message(msg: dict) -> None:
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    if text.startswith("/start"):
        _send(chat_id,
              "👋 <b>Opportunity Hunter</b> is connected.\n"
              f"Your chat id is <code>{chat_id}</code> — put it in .env as "
              "<code>TELEGRAM_CHAT_ID</code> to receive digests.\n"
              "Commands: /top · /report · /taste · /coach — or just ask me anything.")
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
    elif text.startswith("/report"):
        _send(chat_id, tracker.build_report(_history_items()))
    elif text.startswith("/taste"):
        _send(chat_id, taste.report_line())
    elif text.startswith("/coach"):
        import coach
        _send(chat_id, html.escape(coach.analyze(_history_items())))
    elif text.startswith("/"):
        _send(chat_id, "Try /top · /report · /taste · /coach — or just ask me a question.")
    elif text:
        # Freeform question → grounded answer over the feed.
        import ask
        ans = ask.answer(text, _history_items())
        _send(chat_id, html.escape(ans) if ans
              else "Couldn't answer that right now — try again shortly.")


def _daily_tick() -> None:
    """Once a day: fire due reminders, and on Sundays send the weekly report."""
    global _last_tick
    today = date.today()
    if _last_tick == today:
        return
    _last_tick = today
    cid = config.TELEGRAM_CHAT_ID
    if not cid:
        return

    hist = _history_items()
    for key, entry in tracker.due_reminders(today):
        it = hist.get(key)
        title = it.title if it else entry.get("title", "this opportunity")
        url = it.url if it else entry.get("url", "")
        _send(cid, f"⏰ <b>Reminder</b> — you asked to revisit:\n<b>{html.escape(title)}</b>",
              buttons=_tracker_buttons(key, url))
        tracker.clear_remind(key)

    if today.weekday() == 6:  # Sunday
        _send(cid, tracker.build_report(hist))


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
                        action, _, key = cb.get("data", "").partition(":")
                        if action == "plan":
                            _handle_plan(key, cb)
                        elif action == "draft":
                            _handle_draft(key, cb)
                        elif action in ("applied", "skip", "remind"):
                            _handle_status(action, key, cb)
                        else:
                            _answer(cb["id"])
                    elif "message" in upd:
                        _handle_message(upd["message"])
                _daily_tick()
            except requests.RequestException as e:
                log(f"[telegram-listener] poll error: {e}", level="WARN")
                time.sleep(5)
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    run()
