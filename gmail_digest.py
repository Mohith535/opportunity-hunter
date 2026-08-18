"""
Inbox Scout — turn your Gmail into an opportunity + triage digest.

This is OPHunter's discovery organ pointed at your inbox: your college mail is a real source of
programs, events, and networking. It reads TODAY's messages and, for each, gives a category, an
honest 0-10 "how much should I care" rating against your actual goals, a deadline if any, and a
one-line summary — then groups them so you read the signal, not the noise.

────────────────────────────────────────────────────────────────────────────────────────────────
IMPORTANT — privacy: to summarise mail, each message's sender + subject + a short snippet is sent to
the free LLM provider (Groq/Cerebras/OpenRouter). Only a ~500-char snippet is sent, never full bodies
or attachments — but it IS third-party. Don't point this at an inbox with secrets you wouldn't paste
into an API. It never sends, deletes, or modifies anything; read-only.
────────────────────────────────────────────────────────────────────────────────────────────────

SETUP (you must do this — I cannot):
  1. Turn on 2-Step Verification for the account.
  2. Google Account → Security → App passwords → generate one (16 chars).
  3. Put it in this project's gitignored .env:
        GMAIL_USER=mk2184@srmist.edu.in
        GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx
  4. Run:  python gmail_digest.py
     (or override per run:  python gmail_digest.py --user other@gmail.com )

Note on the SRM account: it's a Google Workspace account, so SRM's admin may have DISABLED IMAP or
app passwords. If login fails with that, the app password route is blocked and you'd need the Gmail
API (OAuth) instead — tell me and I'll add that path. Personal Gmail with 2FA works with app passwords.
"""

from __future__ import annotations

import argparse
import email
import imaplib
import os
import re
import sys
from datetime import date
from email.header import decode_header

IMAP_HOST = "imap.gmail.com"
_MAX_EMAILS = 40          # cap the LLM call
_SNIPPET = 500            # chars of body sent per email (privacy + token budget)


def _decode(value: str | None) -> str:
    if not value:
        return ""
    out = []
    for text, enc in decode_header(value):
        out.append(text.decode(enc or "utf-8", errors="ignore") if isinstance(text, bytes) else text)
    return "".join(out)


def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    return re.sub(r"<[^>]+>", " ", html)


def _snippet(msg: email.message.Message) -> str:
    """A short plain-text preview, falling back to tag-stripped HTML."""
    plain = htmls = ""
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        ctype = part.get_content_type()
        if "attachment" in str(part.get("Content-Disposition", "")):
            continue
        try:
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            text = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
        except Exception:
            continue
        if ctype == "text/plain" and not plain:
            plain = text
        elif ctype == "text/html" and not htmls:
            htmls = _strip_html(text)
    return re.sub(r"\s+", " ", (plain or htmls)).strip()[:_SNIPPET]


def fetch_today(user: str, password: str, host: str = IMAP_HOST) -> list[dict]:
    """Today's inbox messages as {from, subject, snippet}. Raises on auth/connection failure."""
    box = imaplib.IMAP4_SSL(host)
    try:
        box.login(user, password)
    except imaplib.IMAP4.error as e:
        raise RuntimeError(
            f"IMAP login failed for {user}: {e}. Check the app password, and that IMAP is enabled "
            "(Gmail → Settings → Forwarding and POP/IMAP). A Workspace/college account may have IMAP "
            "or app-passwords disabled by its admin — then we need the Gmail API (OAuth) instead.") from e
    try:
        box.select("INBOX")
        _, data = box.search(None, f'(SINCE "{date.today().strftime("%d-%b-%Y")}")')
        ids = data[0].split()
        out = []
        for mid in ids[-_MAX_EMAILS:]:
            _, raw = box.fetch(mid, "(RFC822)")
            msg = email.message_from_bytes(raw[0][1])
            out.append({"from": _decode(msg.get("From")), "subject": _decode(msg.get("Subject")),
                        "snippet": _snippet(msg)})
        return out
    finally:
        try:
            box.logout()
        except Exception:
            pass


_PROMPT = """You are Mohith's personal opportunity scout, triaging his email inbox. Here is who he is
and what advances his growth:

{profile}

For EACH email below output ONE line, pipe-separated, and NOTHING else:
<n> | <CATEGORY> | <interest 0-10> | <deadline or -> | <one concise line: what it is + why it does or
does not matter for HIS growth>

CATEGORY is exactly one of:
  PROGRAM    - fellowship / internship / competition / scholarship / research that grows his career
  EVENT      - talk / workshop / hackathon / meetup — new experience or connections
  LEARNING   - a course, resource, or skill-building thing
  ADMIN      - college or personal logistics he actually has to act on
  NOISE      - promotional, newsletter, automated, or irrelevant

interest 0-10 = how much attention HE should give it FOR HIS GROWTH (10 = drop everything and act;
0 = ignore). Be honest and calibrated — most promotional/automated mail is 0-2. Never inflate.
Extract a real deadline if the text has one, else "-".

After all the lines, output one final line:
HIGHLIGHTS: <2-3 sentences: the shape of today's inbox and the single most important thing to act on>

EMAILS:
{emails}
"""

_CATS = ("PROGRAM", "EVENT", "LEARNING", "ADMIN", "NOISE")
_ICON = {"PROGRAM": "🎯", "EVENT": "🤝", "LEARNING": "📚", "ADMIN": "✅", "NOISE": "🗑️"}


def _profile_block() -> str:
    try:
        import user_profile  # noqa: PLC0415
        return user_profile.load_profile().to_prompt_block()
    except Exception:
        return ("A CSE (AI & ML) student chasing AI/ML engineering, elite internships, research, "
                "open source, and international/Google-Microsoft-level opportunities.")


def summarize(emails: list[dict]) -> tuple[list[dict], str]:
    """(scored rows, highlights). Each row: {n, category, interest, deadline, summary, email}."""
    from filters.llm_scorer import complete  # noqa: PLC0415
    listing = "\n".join(
        f"{i}. FROM: {e['from'][:70]} | SUBJECT: {e['subject'][:110]} | {e['snippet'][:400]}"
        for i, e in enumerate(emails, 1))
    out = complete(_PROMPT.format(profile=_profile_block(), emails=listing),
                   max_tokens=1600, temperature=0.2)
    rows, highlights = [], ""
    for line in (out or "").splitlines():
        if line.upper().startswith("HIGHLIGHTS:"):
            highlights = line.split(":", 1)[1].strip()
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5 or not parts[0].rstrip(".").isdigit():
            continue
        n = int(parts[0].rstrip("."))
        if not (1 <= n <= len(emails)):
            continue
        cat = next((c for c in _CATS if c in parts[1].upper()), "NOISE")
        try:
            interest = max(0, min(10, int(re.search(r"\d+", parts[2]).group())))
        except (AttributeError, ValueError):
            interest = 0
        rows.append({"n": n, "category": cat, "interest": interest, "deadline": parts[3],
                     "summary": parts[4], "email": emails[n - 1]})
    return rows, highlights


def format_digest(rows: list[dict], highlights: str, total: int) -> str:
    scanned = len(rows)
    lines = ["=" * 68, f"INBOX SCOUT — {date.today():%A, %d %B %Y}", "=" * 68,
             f"{total} emails today · {scanned} triaged", ""]
    shown = False
    for cat in ("PROGRAM", "EVENT", "LEARNING", "ADMIN"):
        group = sorted([r for r in rows if r["category"] == cat],
                       key=lambda r: -r["interest"])
        if not group:
            continue
        shown = True
        label = {"PROGRAM": "PROGRAMS FOR YOUR GROWTH", "EVENT": "EVENTS · NETWORKING · EXPERIENCE",
                 "LEARNING": "LEARNING", "ADMIN": "ADMIN — needs your action"}[cat]
        lines.append(f"{_ICON[cat]} {label}")
        for r in group:
            dl = f"  ⏰ {r['deadline']}" if r["deadline"] and r["deadline"] != "-" else ""
            lines.append(f"   [{r['interest']}/10] {r['summary']}{dl}")
            lines.append(f"          from: {r['email']['from'][:64]}")
        lines.append("")
    noise = sum(1 for r in rows if r["category"] == "NOISE")
    if noise:
        lines.append(f"🗑️  {noise} promotional/automated email(s) — skipped.\n")
    if not shown:
        lines.append("Nothing growth-relevant surfaced today. A quiet inbox is fine.\n")
    if highlights:
        lines += ["─" * 68, f"TODAY: {highlights}"]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Inbox Scout — an opportunity digest of today's Gmail.")
    ap.add_argument("--user", default=os.environ.get("GMAIL_USER", ""),
                    help="Gmail address (or set GMAIL_USER in .env)")
    ap.add_argument("--host", default=IMAP_HOST, help="IMAP host (default imap.gmail.com)")
    args = ap.parse_args()

    try:
        import config  # loads .env  # noqa: F401, PLC0415
    except Exception:
        pass
    user = args.user or os.environ.get("GMAIL_USER", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not user or not password:
        print("Missing credentials. Set these in .env (see the setup notes at the top of this file):\n"
              "   GMAIL_USER=you@example.com\n   GMAIL_APP_PASSWORD=your-16-char-app-password")
        return 1

    try:
        emails = fetch_today(user, password, args.host)
    except RuntimeError as e:
        print(f"Error: {e}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"Could not reach the mailbox: {e}")
        return 1

    if not emails:
        print(f"No emails today ({date.today():%d %b %Y}) in {user}. Nothing to summarise.")
        return 0

    rows, highlights = summarize(emails)
    if not rows:
        print("Fetched mail but the LLM digest is unavailable — set an LLM key in .env "
              "(GROQ_API_KEY / CEREBRAS_API_KEY / OPENROUTER_API_KEY).")
        return 1
    print(format_digest(rows, highlights, len(emails)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
