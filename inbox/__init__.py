"""
Inbox Assistant — a plain, honest summary of what actually matters in your Gmail.

Separate from Opportunity Hunter on purpose: OPHunter hunts the world for opportunities; the Inbox
Assistant takes care of your OWN mail. It hides the junk you never need to see (one-time codes,
security/verify alerts, promotions, social noise) and shows only what matters — real replies,
deadlines, opportunities, personal mail — with a tap-to-add calendar link on anything with a due date.

Privacy: the junk is filtered out with simple LOCAL rules BEFORE anything reaches the summariser, so
one-time codes and security alerts never leave your machine. Only the handful of genuinely important
emails get a short summary written for them.

It reuses only the Gmail-reading plumbing from `gmail_digest` (how to read the inbox) — the product
logic here is entirely its own.
"""

from .scan import scan, is_junk
from .render import render_html, gcal_link
from .notify import to_telegram
from .tasks import to_taskflow
from .gcal import to_calendar

__all__ = ["scan", "is_junk", "render_html", "gcal_link",
           "to_telegram", "to_taskflow", "to_calendar"]
