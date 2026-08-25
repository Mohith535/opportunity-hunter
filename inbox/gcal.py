"""
Automatically add deadline reminders to your Google Calendar.

This needs ONE extra permission you haven't given yet — the right to add calendar events (you only
granted "read email" so far). Until you enable it, the tap-to-add calendar links in the summary work
perfectly. To turn on automatic adding:

  1. Google Cloud Console → your OPHunter project → Google Auth Platform → Data Access → add the scope
        https://www.googleapis.com/auth/calendar.events
     and Save.
  2. Delete the file  token.json  in this folder (this forces a fresh "Allow" that now includes
     Calendar).
  3. Run:  python -m inbox --calendar   → the browser asks permission for Calendar too → allow it.

After that, deadlines get added to your calendar automatically. This module never deletes or changes
existing events; it only adds new all-day reminders, and never fails the whole run.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

# Full calendar scope (not just events) so OPH can operate every calendar function. Standalone Google
# "Reminders" were retired in 2023 (folded into Tasks), so the modern "reminder" is an EVENT with
# notifications — which we attach below.
_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly",
           "https://www.googleapis.com/auth/calendar"]
_SETUP = ("Calendar needs one more permission. Add the scope "
          "https://www.googleapis.com/auth/calendar in Google Cloud Console (Google Auth Platform → "
          "Data Access), delete token.json, then run `python -m inbox --calendar` and allow Calendar. "
          "(Your tap-to-add links keep working meanwhile.)")


def _already_there(svc, title: str, d: str) -> bool:
    """True if an all-day event with this exact title already exists on day `d` (YYYY-MM-DD).

    Checks the REAL calendar rather than a local log, so re-runs never duplicate — and the events you
    added on earlier runs are recognised too. On any lookup error it returns False (safer to risk a
    rare duplicate than to skip a genuinely-new reminder)."""
    try:
        day = datetime.strptime(d, "%Y-%m-%d").date()
        res = svc.events().list(
            calendarId="primary",
            timeMin=(day - timedelta(days=1)).isoformat() + "T00:00:00Z",
            timeMax=(day + timedelta(days=2)).isoformat() + "T00:00:00Z",
            singleEvents=True, maxResults=100).execute()
        return any((e.get("summary") or "") == title and (e.get("start") or {}).get("date") == d
                   for e in res.get("items", []))
    except Exception:
        return False


def to_calendar(summary: dict, credentials: str = "credentials.json",
                token: str = "token.json") -> dict:
    """Add an all-day reminder for each deadline item. Returns {created, error}. Never raises."""
    items = [it for it in summary.get("shown", []) if it.get("deadline")]
    if not items:
        return {"created": 0, "error": ""}
    try:
        from google.auth.transport.requests import Request  # noqa: PLC0415
        from google.oauth2.credentials import Credentials  # noqa: PLC0415
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: PLC0415
        from googleapiclient.discovery import build  # noqa: PLC0415
    except ImportError:
        return {"created": 0, "error": "Google libraries not installed (see the plan)."}

    creds = None
    if Path(token).exists():
        try:
            creds = Credentials.from_authorized_user_file(token, _SCOPES)
        except Exception:
            creds = None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds:
            # Only start a browser flow on a genuinely fresh token — never surprise the user.
            if not Path(token).exists() and Path(credentials).exists():
                try:
                    creds = InstalledAppFlow.from_client_secrets_file(
                        credentials, _SCOPES).run_local_server(port=0)
                    Path(token).write_text(creds.to_json(), encoding="utf-8")
                except Exception as e:
                    return {"created": 0, "error": f"Consent failed: {e}. {_SETUP}"}
            else:
                return {"created": 0, "error": _SETUP}

    try:
        svc = build("calendar", "v3", credentials=creds)
        created, skipped = 0, 0
        for it in items:
            d = it["deadline"]
            title = f"⏰ {it['subject'][:80]}"
            if _already_there(svc, title, d):   # check the REAL calendar → never duplicate
                skipped += 1
                continue
            end = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            svc.events().insert(calendarId="primary", body={
                "summary": title,
                "description": (it["summary"][:300] + "\n\n(added by your Inbox Assistant)"),
                "start": {"date": d}, "end": {"date": end},
                # The actual "reminder": notifications a day before (popup on phone + email).
                "reminders": {"useDefault": False, "overrides": [
                    {"method": "popup", "minutes": 1440},
                    {"method": "email", "minutes": 1440}]},
            }).execute()
            created += 1
        return {"created": created, "skipped": skipped, "error": ""}
    except Exception as e:
        msg = str(e)
        if "insufficient" in msg.lower() or "scope" in msg.lower() or "403" in msg:
            return {"created": 0, "error": _SETUP}
        return {"created": 0, "error": f"Calendar write failed: {msg[:120]}"}
