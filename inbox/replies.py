"""
Replies about his applications — spotted in Gmail, confirmed by him (22 Oct 2026).

The bot asks "heard back?" 7 and 14 days after he applies, but a recruiter's email can arrive on day 2
and sit unread under the job alerts. This links an email to a job he tapped ✅ Applied on, and sends him
the same three buttons the follow-up uses (🎉 Interview / ❌ Rejected) — HE confirms; an outcome is
never recorded from a guess, because a wrong "rejected" would teach OPH the wrong thing.

A match needs BOTH his application's title AND status wording, and never comes from an alert sender:
his inbox on 21 Oct held "AI/ML Engineering Intern at Daice Labs" from LinkedIn Job Alerts — a title,
not a reply.

Privacy: email text goes only to his own Telegram chat; nothing is logged but counts.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

import requests

import config
from util import log

STATE = config.DATA_DIR / "inbox_replies_asked.json"
MAX_AGE_DAYS = 60
MIN_TITLE = 12           # "Internship" alone matches every alert
_STATUS = re.compile(r"\b(application|applied|shortlist\w*|interview|assessment|next round|selected|offer|"
                     r"unfortunately|regret|not been selected|not selected|status of your|update on your|"
                     r"moving forward|other candidates|congratulations)\b", re.I)
_ALERT = re.compile(r"job ?alert|jobs-noreply|is hiring|new opportunit|recommended for you|jobs you may|"
                    r"\balert\b|newsletter|digest", re.I)
_INTERVIEW = re.compile(r"interview|next round|shortlist\w*|assessment|coding (?:test|round)|selected|"
                        r"schedule (?:a )?(?:call|chat)|congratulations|offer", re.I)
_REJECT = re.compile(r"unfortunately|regret|not (?:been )?selected|other candidates|not moving forward|"
                     r"decided to (?:move forward|proceed) with", re.I)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _role(title: str) -> str:
    """"Software Engineer Intern — Adobe" -> "software engineer intern"; the company is matched apart."""
    return _norm(re.split(r"\s+—\s+", title or "")[0])


def matches(emails: list[dict], tracker: dict, today: date | None = None) -> list[dict]:
    """[{email_id, key, title, guess, subject, sender}] — emails that look like a reply about one of his
    open applications. Pure; the tests pin it."""
    today = today or date.today()
    since = (today - timedelta(days=MAX_AGE_DAYS)).isoformat()
    apps = [(k, e) for k, e in (tracker or {}).items()
            if e.get("status") == "applied" and not e.get("outcome") and e.get("title")
            and str(e.get("applied_at") or e.get("updated_at") or "") >= since
            and len(_role(e["title"])) >= MIN_TITLE]
    out = []
    for m in emails or []:
        sender, subject = str(m.get("from") or ""), str(m.get("subject") or "")
        text = f"{subject} {m.get('summary') or ''}"
        if _ALERT.search(f"{sender} {subject}") or not _STATUS.search(text):
            continue
        body = _norm(text)
        for k, e in apps:
            if f" {_role(e['title'])} " in f" {body} ":
                guess = "rejected" if _REJECT.search(text) else "interview" if _INTERVIEW.search(text) else "reply"
                out.append({"email_id": m.get("id"), "key": k, "title": e["title"], "guess": guess,
                            "subject": subject[:120], "sender": re.sub(r"\s*<.*>", "", sender)[:60]})
                break
    return out


def message(hit: dict) -> tuple[str, list]:
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    word = {"interview": "It reads like good news", "rejected": "It reads like a no",
            "reply": "It is about your application"}[hit["guess"]]
    text = (f"📬 <b>An email about your application</b>\n{esc(hit['title'])}\n\n"
            f"From {esc(hit['sender'])}: “{esc(hit['subject'])}”\n{word} — open it in Gmail, then tell me:")
    kb = [[{"text": "🎉 Interview / next round", "callback_data": f"out:interview:{hit['key']}"},
           {"text": "❌ Rejected", "callback_data": f"out:rejected:{hit['key']}"}]]
    return text, kb


def ask(emails: list[dict]) -> int:
    """Send one message per new matching email. Returns how many were sent. Never raises."""
    from filters.outcomes import fetch_tracker  # noqa: PLC0415
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        return 0
    tracker = fetch_tracker() or {}
    try:
        asked = set(json.loads(STATE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        asked = set()
    sent = 0
    for hit in matches(emails, tracker):
        if not hit["email_id"] or hit["email_id"] in asked:
            continue
        text, kb = message(hit)
        try:
            r = requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                              json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML",
                                    "reply_markup": {"inline_keyboard": kb}}, timeout=config.REQUEST_TIMEOUT)
            if r.ok:
                asked.add(hit["email_id"])
                sent += 1
        except requests.RequestException as e:
            log(f"[replies] send failed: {type(e).__name__}", level="WARN")
    if sent:
        STATE.parent.mkdir(exist_ok=True)
        STATE.write_text(json.dumps(sorted(asked)[-500:]), encoding="utf-8")
    log(f"[replies] {sent} application repl{'y' if sent == 1 else 'ies'} spotted in Gmail")
    return sent
