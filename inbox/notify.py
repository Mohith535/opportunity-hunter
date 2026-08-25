"""
Send the inbox summary to your private Telegram.

This is the safest free way to get PERSONAL email onto your phone: a private direct message only you
can see — no public web link that could leak your inbox. It reuses the Telegram sender the project
already has. Deadlines come through as tap-to-add calendar buttons.
"""

from __future__ import annotations

import html as _html

from notifiers.telegram import is_configured, send_telegram
from .render import _sender_name, gcal_link

_EMOJI = {"REPLY": "💬", "DEADLINE": "⏰", "OPPORTUNITY": "🎯",
          "PERSONAL": "👤", "ACTION": "✅", "INFO": "ℹ️"}


def to_telegram(summary: dict) -> bool:
    """Push the summary to the configured Telegram chat. False if Telegram isn't set up or the send
    fails (never raises). Calendar buttons appear for anything with a deadline."""
    if not is_configured():
        return False
    shown = summary.get("shown", [])
    hidden_total = sum(summary.get("hidden", {}).values())

    lines = [f"<b>📬 Your inbox — {_html.escape(summary.get('window', 'today'))}</b>",
             f"<i>{len(shown)} worth your time · {hidden_total} junk hidden</i>", ""]
    buttons: list = []
    for it in shown[:12]:
        emoji = _EMOJI.get(it["category"], "✉️")
        who = _html.escape(_sender_name(it["from"]))
        summ = _html.escape(it["summary"][:130])
        block = f"{emoji} <b>[{it['importance']}/10]</b> {who}\n   {summ}"
        if it.get("deadline"):
            block += f"\n   ⏰ <b>{_html.escape(it['deadline'])}</b>"
            link = gcal_link(it["subject"], it["deadline"])
            if link:
                buttons.append([{"text": f"＋ Calendar · {it['subject'][:26]}", "url": link}])
        lines.append(block)
    if not shown:
        lines.append("Nothing important right now — a quiet inbox. 🌿")

    return send_telegram("\n".join(lines)[:3900], buttons=buttons or None)
