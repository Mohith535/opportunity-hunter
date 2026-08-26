"""
    python -m inbox                 # today's inbox → summary + a mobile web page
    python -m inbox --days 3        # look back 3 days
    python -m inbox --unread        # only unread
    python -m inbox --out mail.html # choose where the page is written

Reads your Gmail, hides the junk, and writes two things: data/inbox_summary.json (the data) and an
HTML page you open on your phone. Both stay on your machine.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .render import render_html
from .scan import scan

_BASE = Path(__file__).resolve().parent.parent


def main() -> int:
    # Windows consoles default to cp1252 and crash on the odd unicode char in an email. Force UTF-8.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Inbox Assistant — a clean summary of what matters in Gmail.")
    ap.add_argument("--days", type=int, default=1, help="look back this many days (default 1 = today)")
    ap.add_argument("--unread", action="store_true", help="only unread mail")
    ap.add_argument("--credentials", default="credentials.json", help="OAuth client JSON")
    ap.add_argument("--out", default=str(_BASE / "inbox_dashboard.html"),
                    help="where to write the mobile web page")
    ap.add_argument("--phone", action="store_true",
                    help="send the summary to your private Telegram (safest way to see it on your phone)")
    ap.add_argument("--publish", action="store_true",
                    help="push the web page to your private Cloudflare URL (installable as a phone app)")
    ap.add_argument("--taskflow", action="store_true",
                    help="turn important deadlines/actions into TaskFlow tasks (tagged #mail)")
    ap.add_argument("--calendar", action="store_true",
                    help="add deadline reminders to your Google Calendar (needs a one-time permission)")
    ap.add_argument("--watch", type=int, default=0, metavar="MIN",
                    help="keep refreshing every MIN minutes (Ctrl+C to stop) — page stays current")
    ap.add_argument("--headless", action="store_true",
                    help="never open a browser for sign-in (for a scheduled auto-refresh); if the login "
                         "has expired, exit cleanly instead of hanging")
    args = ap.parse_args()

    try:
        import config  # loads .env  # noqa: F401
    except Exception:
        pass

    # --watch keeps the page current on its own: re-run every N minutes until Ctrl+C. This is the honest
    # "it updates" answer — the page is a snapshot, so something has to regenerate it.
    if args.watch and args.watch > 0:
        import time
        print(f"⏳ Auto-refresh every {args.watch} min — your phone page stays current. Ctrl+C to stop.")
        while True:
            try:
                _run_once(args)
            except KeyboardInterrupt:
                print("\n👋 Stopped watching.")
                return 0
            except Exception as e:  # noqa: BLE001
                print(f"(this refresh failed, will try again: {e})")
            try:
                time.sleep(args.watch * 60)
            except KeyboardInterrupt:
                print("\n👋 Stopped watching.")
                return 0
    return _run_once(args)


def _run_once(args) -> int:
    # When adding to Calendar, ask for the Calendar permission in the SAME Gmail login — otherwise the
    # Gmail read creates a Gmail-only token first and the calendar step is left without permission.
    scan_scopes = None
    if args.calendar:
        scan_scopes = ["https://www.googleapis.com/auth/gmail.readonly",
                       "https://www.googleapis.com/auth/calendar"]
    try:
        summary = scan(args.days, args.unread, args.credentials, scopes=scan_scopes,
                       allow_consent=not args.headless)
    except RuntimeError as e:
        print(f"Error: {e}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"Could not read the mailbox: {e}")
        return 1

    # Bring in today's TaskFlow tasks (due today + overdue) — READ-ONLY; the phone dashboard is the
    # thing that actually comes to you, so the tasks ride along with the inbox. Silent if TaskFlow
    # isn't present.
    try:
        from .taskflow_read import read_day_tasks
        summary["day"] = read_day_tasks()
    except Exception:  # noqa: BLE001
        summary["day"] = {"available": False}

    # Save the data + the page (both local, gitignored — personal).
    (_BASE / "data").mkdir(exist_ok=True)
    (_BASE / "data" / "inbox_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    out = Path(args.out)
    dashboard = render_html(summary)
    out.write_text(dashboard, encoding="utf-8")

    # Terminal preview.
    shown, hidden = summary["shown"], summary["hidden"]
    print("=" * 60)
    print(f"INBOX ASSISTANT — {summary['window']}")
    print("=" * 60)
    print(f"{len(shown)} shown · {sum(hidden.values())} codes/security hidden "
          f"({', '.join(f'{v} {k}' for k, v in hidden.items()) or 'none'})\n")
    for it in shown:
        dl = f"  ⏰ {it['deadline']}" if it.get("deadline") else ""
        print(f"  [{it['importance']}/10] {it['category']:11} {it['summary'][:74]}{dl}")
    print(f"\n📱 Open on your phone → {out}")
    print("   (Deadlines have a one-tap 'Add to Calendar' button inside.)")

    # ── deliveries (opt-in) ──
    if args.publish:
        from .publish import publish
        ok, msg = publish(dashboard)
        print("🌐 Private page: " + (f"live → {msg}  (open on your phone → Add to Home Screen)" if ok
                                     else msg))
    if args.phone:
        from .notify import to_telegram
        ok = to_telegram(summary)
        print("📨 Telegram: " + ("sent to your private chat ✓" if ok
                                  else "not configured (set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID in .env)"))
    if args.taskflow:
        from .tasks import to_taskflow
        r = to_taskflow(summary)
        if not r["planned"]:
            print("✅ TaskFlow: nothing important enough to turn into a task today.")
        elif r["available"]:
            print(f"✅ TaskFlow: created {r['created']} task(s) (tagged #mail).")
        else:
            print(f"✅ TaskFlow: would create {len(r['planned'])} task(s), but the `taskflow` command "
                  "isn't on PATH here. Install your TaskFlow CLI "
                  "(pip install git+https://github.com/Mohith535/TaskFlow.git) or run this where it works.")
    if args.calendar:
        from .gcal import to_calendar
        r = to_calendar(summary, args.credentials)
        if r.get("error"):
            print(f"📅 Calendar: {r['error']}")
        else:
            extra = f" ({r['skipped']} already on your calendar)" if r.get("skipped") else ""
            print(f"📅 Calendar: added {r['created']} reminder(s){extra}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
