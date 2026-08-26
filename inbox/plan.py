"""
Step 3 of My Day: the one line at the very top — "what to do first today."

This is the AI-plans-my-day voice, but grounded: the model only ever sees the REAL items already in
the plan (overdue tasks, today's items, this week's deadlines), so it can point but not invent. It's
self-contained — Nova can later read this same plan, but the line stands on its own without Nova.

Resilience matters more than cleverness here: the free LLM chain is flaky (rate limits, dead credits).
So a deterministic fallback always names the single most urgent real item; if the model answers well we
use its line, otherwise the fallback shows. The feature never blanks.
"""

from __future__ import annotations

import datetime

from filters.llm_scorer import complete


def _parse_dl(s):
    try:
        return datetime.datetime.strptime(str(s), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _late(days: int) -> str:
    return "1 day overdue" if days == 1 else f"{days} days overdue"


def _mail_deadlines(emails, today):
    """(due_today, due_soon) email-deadline rows within the next 7 days, carrying importance so the
    fallback can tell a real deadline from a skippable webinar that merely happens to be 'today'."""
    dt, soon = [], []
    for e in emails or []:
        d = _parse_dl(e.get("deadline"))
        if d and today <= d <= today + datetime.timedelta(days=7):
            row = {"title": (e.get("subject") or "").strip(), "date": d,
                   "importance": int(e.get("importance", 0) or 0)}
            (dt if d == today else soon).append(row)
    soon.sort(key=lambda x: x["date"])
    return dt, soon


def _fallback(day: dict, mail_today, mail_soon, today) -> str:
    """A real, deterministic 'first thing' — always works, no network. Order: a genuinely important
    thing due today (irreversible) → the most-urgent overdue task → a low-value thing due today (worth
    a mention) → soonest upcoming → nothing pressing. Importance beats a mere 'due today' timestamp, so
    10 overdue Critical tasks outrank a skippable 8pm webinar."""
    overdue = day.get("overdue", [])
    due = day.get("due_today", [])                       # TaskFlow tasks due today
    imp_today = [m for m in mail_today if m["importance"] >= 4]
    if due:
        return f"First: {due[0]['title'][:70]} — due today."
    if imp_today:
        return f"First: {imp_today[0]['title'][:70]} — due today."
    if overdue:
        t = overdue[0]
        return f"Start with “{t['title'][:60]}” — {_late(t['days_over'])}, your most urgent."
    if mail_today:
        return f"Due today: {mail_today[0]['title'][:70]}."
    if mail_soon:
        m = mail_soon[0]
        n = (m["date"] - today).days
        return f"Nothing due today. Next up: {m['title'][:60]} in {n} day{'s' if n != 1 else ''}."
    return "Nothing urgent today — clear runway. Pick one item off your list and finish it. 🌿"


_PROMPT = """You are Mohith's day-planner. From his real tasks and email deadlines below, write ONE
short line (max 30 words) telling him the single most important thing to do FIRST today, and briefly
why. Name the actual item. Be direct and encouraging. Output ONLY that one line — no preamble, no list.

OVERDUE TASKS (most urgent first):
{overdue}

DUE TODAY:
{due_today}

UPCOMING DEADLINES (next 7 days):
{soon}
"""


def _fmt(rows, kind) -> str:
    if not rows:
        return "  (none)"
    out = []
    for r in rows[:8]:
        if kind == "overdue":
            out.append(f"  - {r['title'][:70]} ({_late(r['days_over'])})")
        elif kind == "task_today":
            out.append(f"  - {r['title'][:70]}")
        else:  # mail with a date
            out.append(f"  - {r['title'][:70]} (due {r['date'].isoformat()})")
    return "\n".join(out)


def first_thing(day: dict | None, emails: list | None, today: datetime.date | None = None) -> str:
    """The 'do this first' line for the top of the day plan. LLM when it answers well, deterministic
    fallback otherwise. Returns '' only when there is genuinely nothing to plan."""
    today = today or datetime.date.today()
    day = day or {}
    mail_today, mail_soon = _mail_deadlines(emails, today)

    has_anything = (day.get("overdue") or day.get("due_today") or day.get("upcoming")
                    or mail_today or mail_soon)
    if not has_anything:
        return ""  # nothing dated to plan — the section stays quiet, no wasted LLM call

    fb = _fallback(day, mail_today, mail_soon, today)

    # Build the grounded context: today's tasks + email-deadlines-today combined.
    due_rows = [{"title": t["title"]} for t in day.get("due_today", [])] + \
               [{"title": m["title"]} for m in mail_today]
    soon_rows = mail_soon + [{"title": t["title"], "date": _parse_dl(t.get("date"))}
                             for t in day.get("upcoming", []) if _parse_dl(t.get("date"))]
    soon_rows = [r for r in soon_rows if r.get("date")]
    soon_rows.sort(key=lambda x: x["date"])

    prompt = _PROMPT.format(
        overdue=_fmt(day.get("overdue", []), "overdue"),
        due_today=_fmt(due_rows, "task_today"),
        soon=_fmt(soon_rows, "mail"))
    try:
        out = complete(prompt, max_tokens=200, temperature=0.4)
    except Exception:  # noqa: BLE001
        out = ""
    line = (out or "").strip().splitlines()[0].strip() if out else ""
    line = line.lstrip("-•*").strip().strip('"').strip()
    # Trust the model only if it looks like a single tidy line; otherwise the deterministic fallback.
    if line and 8 <= len(line) <= 200:
        return line
    return fb
