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
    ap = argparse.ArgumentParser(description="Inbox Assistant — a clean summary of what matters in Gmail.")
    ap.add_argument("--days", type=int, default=1, help="look back this many days (default 1 = today)")
    ap.add_argument("--unread", action="store_true", help="only unread mail")
    ap.add_argument("--credentials", default="credentials.json", help="OAuth client JSON")
    ap.add_argument("--out", default=str(_BASE / "inbox_dashboard.html"),
                    help="where to write the mobile web page")
    args = ap.parse_args()

    try:
        import config  # loads .env  # noqa: F401
    except Exception:
        pass

    try:
        summary = scan(args.days, args.unread, args.credentials)
    except RuntimeError as e:
        print(f"Error: {e}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"Could not read the mailbox: {e}")
        return 1

    # Save the data + the page (both local, gitignored — personal).
    (_BASE / "data").mkdir(exist_ok=True)
    (_BASE / "data" / "inbox_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    out = Path(args.out)
    out.write_text(render_html(summary), encoding="utf-8")

    # Terminal preview.
    shown, hidden = summary["shown"], summary["hidden"]
    print("=" * 60)
    print(f"INBOX ASSISTANT — {summary['window']}")
    print("=" * 60)
    print(f"{len(shown)} worth your time · {sum(hidden.values())} junk hidden "
          f"({', '.join(f'{v} {k}' for k, v in hidden.items()) or 'none'})\n")
    for it in shown:
        dl = f"  ⏰ {it['deadline']}" if it.get("deadline") else ""
        print(f"  [{it['importance']}/10] {it['category']:11} {it['summary'][:74]}{dl}")
    print(f"\n📱 Open on your phone → {out}")
    print("   (Deadlines have a one-tap 'Add to Calendar' button inside.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
