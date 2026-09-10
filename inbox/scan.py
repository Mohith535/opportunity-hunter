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

# Subjects/senders that are one-time codes, sign-in/security, verification — never useful to read.
_JUNK_RE = re.compile(
    r"(one[- ]?time|verification code|verify your|confirm your (e?mail|account)|"
    r"security (alert|code|notification)|new sign[- ]?in|sign[- ]?in attempt|new device|"
    r"unusual (sign|activity|login)|password (reset|change)|reset your password|2[- ]?step|"
    r"\botp\b|your (otp|code|verification)|\bauthenticat|did you just (sign|try))",
    re.I)

_CATEGORIES = ("REPLY", "DEADLINE", "OPPORTUNITY", "PERSONAL", "ACTION", "INFO", "NOISE")

# ─── deterministic safety net ────────────────────────────────────────────────────────────────────
# The model is not allowed to be the only thing standing between Mohith and a real paid offer. These
# rules run on EVERY email regardless of what the LLM said (or failed to say) and raise a FLOOR on
# importance, so money, work offers and human replies can never be buried in "Low priority".
_MONEY_RE = re.compile('(?:[\\u20b9$\\u20ac\\u00a3]\\s?\\d[\\d,]*|\\b\\d[\\d,]*\\s?(?:k|lakh|lpa|usd|eur|inr)\\b|\\b(?:usd|eur|inr|rs)\\.?\\s?\\d[\\d,]*)', re.I)
_WORK_RE = re.compile(
    '\\b(offer|hiring|freelance|contract(?:or)?|paid (?:work|gig|project|role)|collaborat\\w*|commission|would like to (?:hire|pay|work)|budget|compensation|stipend|proposal|work with (?:you|us)|shortlisted|selected for)\\b', re.I)
# Marketing that merely *looks* like an offer. If this fires we do NOT raise the floor.
_PROMO_RE = re.compile(
    '(\\d+\\s?%\\s?off|\\bdiscount|\\bsale\\b|\\bsubscribe|\\bcoupon|limited[- ]time|save big|upgrade (?:now|today)|unsubscribe|newsletter|\\bwebinar\\b|\\bcourse\\b|\\bplan\\b[^.]{0,20}\\b(?:year|month)ly?)', re.I)
_NOREPLY_RE = re.compile('no[-_.]?reply|donotreply|notifications?@|mailer|bounce', re.I)


def high_signal(subject: str, sender: str, snippet: str = "") -> tuple[int, str]:
    """(importance_floor, reason) — 0 when nothing fires.

    Deliberately biased toward SHOWING: a missed paid offer costs far more than one extra email on
    screen. Marketing that merely uses offer-words is excluded so this stays trustworthy."""
    text = f"{subject} {sender} {snippet}"
    if _PROMO_RE.search(text):
        return 0, ""
    money = bool(_MONEY_RE.search(text))
    work = bool(_WORK_RE.search(text))
    if money and work:
        return 8, "a real amount of money plus work terms"
    if money:
        return 6, "a concrete amount of money"
    if work:
        return 5, "work/offer wording"
    if re.match(r"\s*re\s*:", subject or "", re.I) and not _NOREPLY_RE.search(sender or ""):
        return 6, "a reply from a real person"
    return 0, ""



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
    """(hide?, reason). Local rules only — no network, no LLM. Reason is a short bucket name.

    We hide ONLY one-time codes / security / verification mail — the stuff that's genuinely never worth
    reading and that must never leave the machine. Everything else (promotions, social, newsletters)
    stays visible; the summariser just sorts it low so it lands in 'Everything else' instead of on top.
    """
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


def _triage(keep: list, chunk: int = 12) -> dict[int, dict]:
    """LLM-triage every kept email, in small batches. One giant prompt (a big inbox has 30-40 mails
    once promos are no longer pre-hidden) overflows the provider's request size — Groq returns 413 and
    the whole digest silently falls back to defaults. Batching keeps each call small and reliable.
    Returns {global 1-based index: {category, importance, deadline, summary}}."""
    result: dict[int, dict] = {}
    for start in range(0, len(keep), chunk):
        batch = keep[start:start + chunk]
        listing = "\n".join(
            f"{i}. FROM: {e['from'][:70]} | SUBJECT: {e['subject'][:110]} | {e['snippet'][:250]}"
            for i, e in enumerate(batch, 1))
        out = complete(_PROMPT.format(emails=listing), max_tokens=3500, temperature=0.2)
        for local_i, row in _parse(out, len(batch)).items():
            result[start + local_i] = row
    return result


def scan(days: int = 1, unread: bool = False, credentials: str = "credentials.json",
         scopes: list | None = None, allow_consent: bool = True) -> dict:
    """Read the inbox and return {shown, hidden, total, window}. `shown` is EVERY email except hidden
    OTP/security, each triaged and sorted most-important first (the caller/render tiers them into
    'worth your time' vs 'everything else'); `hidden` is a {reason: count} tally of what was filtered.

    `scopes` lets a caller ask for extra permission in the SAME login (e.g. Calendar), so we don't end
    up with a Gmail-only token that later blocks calendar writes. `allow_consent=False` makes a headless
    auto-refresh fail fast instead of blocking on a browser sign-in."""
    emails = fetch_today_oauth(credentials, query=build_gmail_query(days, unread), scopes=scopes,
                               allow_consent=allow_consent)
    window = "last 24 hours" if days <= 1 else f"last {days} days"
    if unread:
        window += " · unread"

    keep, hidden = [], {}
    for e in emails:
        junk, why = is_junk(e)
        if junk:
            hidden[why] = hidden.get(why, 0) + 1
        else:
            keep.append(e)

    shown, untriaged, seen_keys = [], 0, set()
    if keep:
        parsed = _triage(keep)
        for i, e in enumerate(keep, 1):
            # Same blast twice? Keep one, so a duplicate can never crowd out something real.
            key = ((e.get("from") or "").strip().lower(), (e.get("subject") or "").strip().lower())
            if key in seen_keys:
                hidden["duplicates"] = hidden.get("duplicates", 0) + 1
                continue
            seen_keys.add(key)

            p = parsed.get(i)
            triaged = p is not None
            if not triaged:
                untriaged += 1
                # FAIL VISIBLE, NOT INVISIBLE. The old default (3/10 INFO) silently buried every
                # email whenever the LLM chain was down — that is how a real paid offer got missed.
                # An unranked email now sits ABOVE the fold and is flagged as unranked.
                p = {"category": "INFO", "importance": 5, "deadline": "",
                     "summary": (e.get("subject") or "")[:90]}
            if p["category"] == "NOISE":
                p["importance"] = min(p["importance"], 2)

            floor, why = high_signal(e.get("subject", ""), e.get("from", ""), e.get("snippet", ""))
            signal = ""
            if floor > p["importance"]:
                p = {**p, "importance": floor}
                signal = why
            shown.append({"from": e["from"], "subject": e["subject"], "id": e.get("id", ""),
                          "triaged": triaged, "signal": signal, **p})
        shown.sort(key=lambda x: -x["importance"])

    return {"shown": shown, "hidden": hidden, "total": len(emails), "window": window,
            "untriaged": untriaged}
