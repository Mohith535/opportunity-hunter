"""
Push the rendered dashboard to your private Cloudflare Worker, so it's on your phone as an app.

Reads INBOX_WORKER_URL + INBOX_SECRET from the environment (.env). Until you've deployed the worker
(see cloudflare-inbox/README.md), this just tells you what to set — it never fails the run.
"""

from __future__ import annotations

import os


def publish(html: str) -> tuple[bool, str]:
    """(ok, message-or-private-url). Posts the dashboard HTML to the worker's /push route."""
    url = (os.environ.get("INBOX_WORKER_URL") or "").rstrip("/")
    secret = os.environ.get("INBOX_SECRET") or ""
    if not url or not secret:
        return False, ("not set up yet — deploy the worker (cloudflare-inbox/README.md), then put "
                       "INBOX_WORKER_URL + INBOX_SECRET in .env")
    try:
        import requests  # noqa: PLC0415
        r = requests.post(f"{url}/{secret}/push", data=html.encode("utf-8"),
                          headers={"content-type": "text/html"}, timeout=20)
        r.raise_for_status()
        return True, f"{url}/{secret}/"
    except Exception as e:  # noqa: BLE001
        return False, f"push failed: {str(e)[:140]}"
