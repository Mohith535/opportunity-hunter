"""
Phone notifications via ntfy.sh (CLAUDE.md §8.2).

Free, no account. User subscribes to the topic in the ntfy app. Best-effort:
if ntfy.sh is down or rate-limited, we log and move on — never crash the run.

Setup for the user:
  1. Install the ntfy app (Android/iOS)
  2. Subscribe to your NTFY_TOPIC (set in .env / config.py)
  3. Done.
"""

import requests

import config
from util import log


def _ascii_header(text: str) -> str:
    """HTTP headers are latin-1; ntfy mishandles non-ASCII titles. Emojis go in
    the body/Tags instead, so strip the Title header to ASCII."""
    return text.encode("ascii", "ignore").decode("ascii").strip() or "Opportunity Hunter"


def send_phone(title: str, message: str, priority: str = "default", tags: str = "rocket") -> bool:
    """Send a push to the ntfy topic.

    priority: urgent | high | default | low | min
    Returns True on success, False on any failure (logged, never raised).
    """
    if not config.PHONE_NOTIFICATIONS:
        return False
    try:
        resp = requests.post(
            config.NTFY_URL,
            data=message.encode("utf-8"),
            headers={
                "Title": _ascii_header(title),
                "Priority": priority,
                "Tags": tags,
            },
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        log(f"[ntfy] phone notification failed: {e}", level="WARN")
        return False


if __name__ == "__main__":
    ok = send_phone(
        "🎯 Opportunity Hunter — Test",
        "If you can read this on your phone, ntfy works! 🚀",
        priority="high",
    )
    print("sent:", ok, "| topic:", config.NTFY_TOPIC)
