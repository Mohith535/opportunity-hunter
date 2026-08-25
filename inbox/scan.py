"""
The engine: read the inbox, drop the junk locally, summarise only what matters.

Flow, in order (each step cheap before the expensive one):
  1. Read today's mail (reuses gmail_digest's OAuth reader).
  2. HIDE the junk with local rules — Gmail's own promotions/social buckets, plus one-time-code and
     security/verify subjects. This happens BEFORE the summariser, so codes never leave the machine.
  3. Summarise the rest with the free LLM: a category, an importance 0-10, a deadline if any, and one
     plain line. Anything the model itself calls NOISE is folded into the hidden count.
"""

from __future__ import annotations

import re

from filters.llm_scorer import complete
from gmail_digest import build_gmail_query, fetch_today_oauth

# Gmail's own buckets we hide by default — this is where OTP/promo/social noise lives.
_HIDE_LABELS = {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL"}

# Subjects/senders that are one-time codes, sign-in/security, verification — never useful to read.
_JUNK_RE = re.compile(
    r"(one[- ]?time|verification code|verify your|confirm your (e?mail|account)|"
    r"security (alert|code|notification)|new sign[- ]?in|sign[- ]?in attempt|new device|"
    r"unusual (sign|activity|login)|password (reset|change)|reset your password|2[- ]?step|"
    r"\botp\b|your (otp|code|verification)|\bauthenticat|did you just (sign|try))",
    re.I)

_CATEGORIES = ("REPLY", "DEADLINE", "OPPORTUNITY", "PERSONAL", "ACTION", "INFO", "NOISE")

_PROMPT = """You are triaging the IMPORTANT part of Mohith's email inbox — the obvious junk (one-time
codes, security alerts, promotions) has ALREADY been removed. For EACH email below output ONE line,
pipe-separated, and NOTHING else:

<n> | <CATEGORY> | <importance 0-10> | <deadline as YYYY-MM-DD or -> | <one short plain line: what it is + what it needs from him>

CATEGORY is exactly one of:
  REPLY       - a real reply/response from a person or company
  DEADLINE    - something due by a specific date (application, submission, payment, form)
  OPPORTUNITY - a job / internship / hackathon / scholarship / program
  PERSONAL    - from a real person, personal or one-to-one
  ACTION      - he has to do something (confirm, upload, respond, decide)
  INFO        - worth knowing, but no action needed
  NOISE       - actually not important after all (newsletter, automated, irrelevant)

importance 0-10 = how much it matters to HIM (10 = handle today; 0 = ignore). Be honest and calibrated.
deadline: only a REAL date found in the email, formatted YYYY-MM-DD, else "-". Assume the year is the
current or next one so the date is in the future.

EMAILS:
{emails}
"""


def is_junk(email: dict) -> tuple[bool, str]:
    """(hide?, reason). Local rules only — no network, no LLM. Reason is a short bucket name."""
    if set(email.get("labels") or []) & _HIDE_LABELS:
        return True, "promotions & social"
    if _JUNK_RE.search(f"{email.get('subject', '')} {email.get('from', '')}"):
        return True, "codes & security"
    return False, ""


def _parse(out: str, n: int) -> dict[int, dict]:
    rows: dict[int, dict] = {}
    for line in (out or "").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5 or not parts[0].rstrip(".").isdigit():
            continue
        idx = int(parts[0].rstrip("."))
        if not (1 <= idx <= n):
            continue
        cat = next((c for c in _CATEGORIES if c in parts[1].upper()), "INFO")
        try:
            imp = max(0, min(10, int(re.search(r"\d+", parts[2]).group())))
        except (AttributeError, ValueError):
            imp = 3
        deadline = parts[3] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[3]) else ""
        rows[idx] = {"category": cat, "importance": imp, "deadline": deadline, "summary": parts[4]}
    return rows


def scan(days: int = 1, unread: bool = False, credentials: str = "credentials.json") -> dict:
    """Read the inbox and return {shown, hidden, total, window}. `shown` is the important mail, sorted
    most-important first; `hidden` is a {reason: count} tally of what was filtered out."""
    emails = fetch_today_oauth(credentials, query=build_gmail_query(days, unread))
    window = "today" if days <= 1 else f"last {days} days"
    if unread:
        window += " · unread"

    keep, hidden = [], {}
    for e in emails:
        junk, why = is_junk(e)
        if junk:
            hidden[why] = hidden.get(why, 0) + 1
        else:
            keep.append(e)

    shown = []
    if keep:
        listing = "\n".join(
            f"{i}. FROM: {e['from'][:70]} | SUBJECT: {e['subject'][:110]} | {e['snippet'][:300]}"
            for i, e in enumerate(keep, 1))
        parsed = _parse(complete(_PROMPT.format(emails=listing), max_tokens=4000, temperature=0.2),
                        len(keep))
        for i, e in enumerate(keep, 1):
            p = parsed.get(i, {"category": "INFO", "importance": 3, "deadline": "",
                               "summary": e["subject"][:90]})
            if p["category"] == "NOISE":
                hidden["low value"] = hidden.get("low value", 0) + 1
                continue
            shown.append({"from": e["from"], "subject": e["subject"], **p})
        shown.sort(key=lambda x: -x["importance"])

    return {"shown": shown, "hidden": hidden, "total": len(emails), "window": window}
