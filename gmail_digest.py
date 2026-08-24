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

DEFAULT AUTH = OAuth (Gmail API, READ-ONLY) — no 2-Step Verification, no password shared. Chosen
because enabling 2SV would force phone OTP on your normal lab logins (phones aren't allowed in the
lab). OAuth authorises ONCE in a browser (no phone if 2SV is off) and caches a token locally.

SETUP (you must do this in Google Cloud Console — I cannot):
  1. console.cloud.google.com → create a project (e.g. "OPHunter").
  2. APIs & Services → Library → enable "Gmail API".
  3. APIs & Services → OAuth consent screen → External → app name + your email →
     add your SRM email as a Test user → keep publishing status "Testing".
  4. Credentials → Create credentials → OAuth client ID → "Desktop app" → download the JSON →
     save it as  credentials.json  in this project folder.
  5. Run:  python gmail_digest.py
     A browser opens → sign in (no phone if 2SV is off) → "Advanced → Go to OPHunter (unsafe)" past
     the unverified-app warning → grant READ-ONLY Gmail. Token cached in token.json (gitignored).
  Needs:  pip install google-auth-oauthlib google-api-python-client google-auth-httplib2

TWO honest caveats (verified, not guessed):
  • FREE/personal OAuth stays in "Testing" mode, so the refresh token EXPIRES EVERY 7 DAYS — re-run
    step 5's browser click about weekly (still no phone). Permanent tokens need Google's paid
    verification for the restricted Gmail scope — not worth it for personal use.
  • SRM is Google Workspace FOR EDUCATION; its admin can BLOCK third-party apps from Gmail. If you see
    "Access blocked: … your admin", OAuth is walled off (same as IMAP) — no free workaround short of
    SRM IT or using personal Gmail.

Alternative (ONLY if you already have 2-Step Verification): run with  --imap  and set GMAIL_USER +
GMAIL_APP_PASSWORD in .env.
"""

from __future__ import annotations

import argparse
import email
import hashlib
import imaplib
import json
import os
import re
import sys
from datetime import date, timedelta
from email.header import decode_header
from pathlib import Path

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


def fetch_today(user: str, password: str, host: str = IMAP_HOST,
                days: int = 1, unread: bool = False) -> list[dict]:
    """Inbox messages as {from, subject, snippet}. `days` = look-back window (1 = today).
    Raises on auth/connection failure. (IMAP path — Gmail search operators aren't available here.)"""
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
        since = (date.today() - timedelta(days=max(0, days - 1))).strftime("%d-%b-%Y")
        criteria = f'SINCE "{since}"' + (" UNSEEN" if unread else "")
        _, data = box.search(None, f"({criteria})")
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


# ─── OAuth / Gmail API path (default — no 2-Step Verification needed) ────────────
_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def build_gmail_query(days: int = 1, unread: bool = False, raw: str = "") -> str:
    """A Gmail search query from the scan flags. `raw` overrides everything (full Gmail operators)."""
    if raw:
        return raw
    base = f"after:{date.today():%Y/%m/%d}" if days <= 1 else f"newer_than:{days}d"
    return f"{base} is:unread" if unread else base


def fetch_today_oauth(credentials_path: str = "credentials.json",
                      token_path: str = "token.json", query: str = "") -> list[dict]:
    """Today's inbox via the Gmail API over OAuth (read-only). No app password, no 2SV.

    First run opens a browser for one-time consent; the token is cached in token_path. Kept in
    'Testing' publishing status the refresh token expires ~weekly, so you re-consent with a browser
    click (no phone). Uses the Gmail-provided ~200-char snippet only — never decodes full bodies.
    """
    try:
        from google.auth.transport.requests import Request  # noqa: PLC0415
        from google.oauth2.credentials import Credentials  # noqa: PLC0415
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: PLC0415
        from googleapiclient.discovery import build  # noqa: PLC0415
    except ImportError as e:
        raise RuntimeError(
            "Gmail API libraries aren't installed. Run:\n"
            "   pip install google-auth-oauthlib google-api-python-client google-auth-httplib2") from e

    from pathlib import Path as _P  # noqa: PLC0415
    creds = None
    if _P(token_path).exists():
        creds = Credentials.from_authorized_user_file(token_path, _SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds:
            if not _P(credentials_path).exists():
                raise RuntimeError(
                    f"No '{credentials_path}' found. Create a Google Cloud OAuth 'Desktop app' client "
                    "and download it here as credentials.json (see the setup notes at the top).")
            creds = InstalledAppFlow.from_client_secrets_file(
                credentials_path, _SCOPES).run_local_server(port=0)
        _P(token_path).write_text(creds.to_json(), encoding="utf-8")

    service = build("gmail", "v1", credentials=creds)
    listing = service.users().messages().list(
        userId="me", q=query or f"after:{date.today():%Y/%m/%d}",
        maxResults=_MAX_EMAILS).execute()
    out = []
    for ref in listing.get("messages", []):
        msg = service.users().messages().get(
            userId="me", id=ref["id"], format="metadata",
            metadataHeaders=["From", "Subject"]).execute()
        headers = {h["name"].lower(): h["value"]
                   for h in msg.get("payload", {}).get("headers", [])}
        out.append({"from": headers.get("from", ""), "subject": headers.get("subject", ""),
                    "snippet": (msg.get("snippet", "") or "")[:_SNIPPET]})
    return out


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
    # gpt-oss-120b is a reasoning model — it spends tokens "thinking" before the visible answer, so a
    # tight ceiling truncates the per-email lines (1600 handled only ~8 of 38 emails). Headroom for the
    # 40-email cap. It only generates what it needs, so this costs nothing extra on small inboxes.
    out = complete(_PROMPT.format(profile=_profile_block(), emails=listing),
                   max_tokens=5000, temperature=0.2)
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


def format_digest(rows: list[dict], highlights: str, total: int, window: str = "today") -> str:
    scanned = len(rows)
    lines = ["=" * 68, f"INBOX SCOUT — {date.today():%A, %d %B %Y}", "=" * 68,
             f"{total} emails ({window}) · {scanned} triaged", ""]
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


# ─── Inbox → Feed: make growth-worthy emails first-class OPHunter opportunities ──
_FEED_PATH = Path(__file__).resolve().parent / "data" / "inbox_items.json"
_URL_RE = re.compile(r"https?://[^\s)>\]]+")


def to_feed_items(rows: list[dict], min_interest: int = 4) -> list[dict]:
    """Growth-worthy inbox opportunities (PROGRAM/EVENT ≥ min_interest) in OPHunter feed schema —
    so `python -m resume.fit` ranks them next to the scraped opportunities."""
    out = []
    for r in rows:
        if r["category"] not in ("PROGRAM", "EVENT") or r["interest"] < min_interest:
            continue
        e = r["email"]
        link = _URL_RE.search(e.get("snippet", "") or "")
        out.append({
            "key": hashlib.md5(f"{e['from']}|{e['subject']}".encode()).hexdigest()[:12],
            "title": (e.get("subject") or "(no subject)")[:140],
            "url": link.group(0) if link else "",
            "source": "inbox",
            "deadline": r["deadline"] if r["deadline"] and r["deadline"] != "-" else "",
            "tags": [r["category"].lower(), "inbox"],
            "ai_score": r["interest"],
            "ai_summary": r["summary"],
            "description": e.get("snippet", ""),
            "from": e.get("from", ""),
        })
    return out


def save_feed_items(items: list[dict], path: Path = _FEED_PATH) -> tuple[int, int]:
    """Merge into data/inbox_items.json, deduped by key (so re-runs don't duplicate). (added, total)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict] = {}
    try:
        for it in json.loads(path.read_text(encoding="utf-8")).get("items", []):
            existing[it.get("key")] = it
    except Exception:
        pass
    today, added = date.today().isoformat(), 0
    for it in items:
        if it["key"] in existing:  # refresh the live fields in case it was re-triaged
            existing[it["key"]].update({k: it[k] for k in ("ai_score", "ai_summary", "deadline")})
        else:
            it["first_seen"] = today
            existing[it["key"]] = it
            added += 1
    path.write_text(json.dumps({"updated_at": today, "items": list(existing.values())},
                               indent=2, ensure_ascii=False), encoding="utf-8")
    return added, len(existing)


def main() -> int:
    ap = argparse.ArgumentParser(description="Inbox Scout — an opportunity digest of today's Gmail.")
    ap.add_argument("--imap", action="store_true",
                    help="use IMAP + app password instead of OAuth (needs 2-Step Verification)")
    ap.add_argument("--credentials", default="credentials.json",
                    help="OAuth client JSON from Google Cloud (OAuth mode, default)")
    ap.add_argument("--user", default=os.environ.get("GMAIL_USER", ""),
                    help="Gmail address (IMAP mode only)")
    ap.add_argument("--host", default=IMAP_HOST, help="IMAP host (IMAP mode only)")
    ap.add_argument("--days", type=int, default=1,
                    help="look back this many days (default 1 = today). Use if you run it irregularly "
                         "so opportunities from in-between days aren't missed.")
    ap.add_argument("--unread", action="store_true", help="scan only UNREAD mail (cuts through a busy inbox)")
    ap.add_argument("--query", default="",
                    help="raw Gmail search query, full control (OAuth only), e.g. "
                         "\"is:unread -category:promotions newer_than:3d\" — overrides --days/--unread")
    ap.add_argument("--no-feed", action="store_true",
                    help="just print the digest; don't save opportunities to data/inbox_items.json")
    args = ap.parse_args()

    # A human-readable label for what we scanned (shown in the digest header).
    if args.query:
        window = "custom query"
    else:
        window = "today" if args.days <= 1 else f"last {args.days} days"
        if args.unread:
            window += " · unread only"

    try:
        import config  # loads .env  # noqa: F401, PLC0415
    except Exception:
        pass

    try:
        if args.imap:
            if args.query:
                print("Note: --query uses Gmail search syntax and is OAuth-only; ignoring it for IMAP "
                      "(--days and --unread still apply).")
            user = args.user or os.environ.get("GMAIL_USER", "")
            password = os.environ.get("GMAIL_APP_PASSWORD", "")
            if not user or not password:
                print("IMAP mode needs credentials in .env:\n"
                      "   GMAIL_USER=you@example.com\n   GMAIL_APP_PASSWORD=your-16-char-app-password")
                return 1
            emails = fetch_today(user, password, args.host, days=args.days, unread=args.unread)
        else:
            emails = fetch_today_oauth(
                args.credentials, query=build_gmail_query(args.days, args.unread, args.query))
    except RuntimeError as e:
        print(f"Error: {e}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"Could not reach the mailbox: {e}\n"
              "(If this says the app is blocked by your admin, SRM's Workspace has disabled "
              "third-party Gmail access — see the caveats at the top of this file.)")
        return 1

    if not emails:
        print(f"No emails matched ({window}). Nothing to summarise.")
        return 0

    rows, highlights = summarize(emails)
    if not rows:
        print("Fetched mail but the LLM digest is unavailable — set an LLM key in .env "
              "(GROQ_API_KEY / CEREBRAS_API_KEY / OPENROUTER_API_KEY).")
        return 1
    print(format_digest(rows, highlights, len(emails), window))

    if not args.no_feed:
        added, total = save_feed_items(to_feed_items(rows))
        if total:
            print(f"\n📥 {added} new opportunit(y/ies) saved to data/inbox_items.json "
                  f"({total} tracked). Rank them with your scraped feed:  python -m resume.fit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
