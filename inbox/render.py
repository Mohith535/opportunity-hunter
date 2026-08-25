"""
Turn the scan into things you can use: a tap-to-add calendar link, and a clean mobile web page.

The calendar link is the zero-setup path from the plan — it opens Google Calendar with the event
pre-filled; you tap save. No extra permission needed. The page is a single self-contained HTML file
(all data embedded) you open on your phone; it never calls out anywhere except the calendar links you
choose to tap.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from datetime import datetime, timedelta

_CAT = {
    "REPLY": ("💬", "Reply"), "DEADLINE": ("⏰", "Deadline"), "OPPORTUNITY": ("🎯", "Opportunity"),
    "PERSONAL": ("👤", "Personal"), "ACTION": ("✅", "To do"), "INFO": ("ℹ️", "Info"),
}


def gcal_link(title: str, deadline: str) -> str:
    """A Google Calendar 'add event' URL for an all-day event on `deadline` (YYYY-MM-DD). '' if bad."""
    try:
        d = datetime.strptime(deadline, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return ""
    q = urllib.parse.urlencode({
        "action": "TEMPLATE", "text": title[:120],
        "dates": f"{d:%Y%m%d}/{d + timedelta(days=1):%Y%m%d}",
        "details": "Reminder added from your Inbox Assistant."})
    return "https://calendar.google.com/calendar/render?" + q


def _sender_name(s: str) -> str:
    s = (s or "").strip()
    m = re.match(r'\s*"?([^"<]+?)"?\s*<', s)
    if m:
        return m.group(1).strip()[:40]
    if "@" in s and " " not in s:
        return s.split("@")[0][:40]
    return (s or "Unknown")[:40]


def _e(s) -> str:
    return html.escape(str(s or ""))


def render_html(summary: dict) -> str:
    shown = summary.get("shown", [])
    hidden = summary.get("hidden", {})
    hidden_total = sum(hidden.values())
    built = datetime.now().strftime("%A, %d %B %Y · %I:%M %p")

    cards = []
    for it in shown:
        emoji, label = _CAT.get(it["category"], ("✉️", it["category"].title()))
        imp = it["importance"]
        dl = it.get("deadline") or ""
        actions = []
        gid = it.get("id") or ""
        if gid:  # jump straight to the real email in Gmail
            actions.append(
                '<a class="btn open" target="_blank" rel="noopener" '
                f'href="https://mail.google.com/mail/u/0/#all/{_e(gid)}">✉️ Open email</a>')
        if dl:
            cal = gcal_link(it["subject"], dl)
            if cal:
                actions.append('<a class="btn cal" target="_blank" rel="noopener" '
                               f'href="{_e(cal)}">＋ Calendar</a>')
            actions.append(f'<span class="due">⏰ {_e(dl)}</span>')
        actions_html = f'<div class="actions">{"".join(actions)}</div>' if actions else ""
        cards.append(f"""
        <article class="card imp{min(imp,10)//4}">
          <div class="row1">
            <span class="chip">{emoji} {_e(label)}</span>
            <span class="imp" title="importance">{imp}/10</span>
          </div>
          <div class="who">{_e(_sender_name(it["from"]))}</div>
          <div class="subj">{_e(it["subject"][:120])}</div>
          <div class="sum">{_e(it["summary"])}</div>
          {actions_html}
        </article>""")

    if not shown:
        cards.append('<p class="empty">Nothing important right now. A quiet inbox is a good inbox. 🌿</p>')

    hidden_line = ""
    if hidden_total:
        bits = " · ".join(f"{v} {_e(k)}" for k, v in hidden.items())
        hidden_line = f'<div class="hidden">🗂️ Hid {hidden_total} junk email(s): {bits}</div>'

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>My Inbox — {_e(summary.get('window','today'))}</title>
<style>
  :root{{--bg:#F6F7F5;--surface:#fff;--ink:#1b211d;--soft:#586159;--line:#e6e8e3;
    --accent:#2E7D5B;--accent-soft:#e7f0ea;--gold:#a8791b;--gold-soft:#f5ecd6;
    --hi:#c6532b;--sh:0 1px 2px rgba(20,30,22,.05),0 6px 18px rgba(20,30,22,.05)}}
  @media(prefers-color-scheme:dark){{:root{{--bg:#12160f;--surface:#1a1f18;--ink:#eceee7;
    --soft:#a0a89c;--line:#2a2f26;--accent:#69c295;--accent-soft:#1f2b22;--gold:#e7b65c;
    --gold-soft:#2a2416;--hi:#e8875f;--sh:0 1px 2px rgba(0,0,0,.3),0 8px 22px rgba(0,0,0,.35)}}}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,ui-sans-serif,sans-serif;
    font-size:16px;line-height:1.5;-webkit-font-smoothing:antialiased}}
  .wrap{{max-width:640px;margin:0 auto;padding:22px 16px 60px}}
  header h1{{font-size:1.5rem;margin:0 0 2px;letter-spacing:-.01em}}
  .built{{color:var(--soft);font-size:.85rem;margin-bottom:12px}}
  .counts{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px}}
  .pill{{background:var(--accent-soft);color:var(--accent);font-weight:700;font-size:.82rem;
    padding:5px 11px;border-radius:999px}}
  .hidden{{color:var(--soft);font-size:.85rem;margin:6px 0 18px}}
  .card{{background:var(--surface);border:1px solid var(--line);border-radius:16px;
    padding:14px 15px;margin-bottom:11px;box-shadow:var(--sh);border-left:4px solid var(--line)}}
  .card.imp2{{border-left-color:var(--accent)}} .card.imp3{{border-left-color:var(--hi)}}
  .row1{{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:6px}}
  .chip{{font-size:.76rem;font-weight:700;background:var(--accent-soft);color:var(--accent);
    padding:3px 9px;border-radius:999px}}
  .imp{{font-size:.78rem;font-weight:800;color:var(--soft);font-variant-numeric:tabular-nums}}
  .who{{font-weight:800;font-size:.98rem}}
  .subj{{color:var(--soft);font-size:.86rem;margin:1px 0 6px}}
  .sum{{font-size:.95rem}}
  .actions{{margin-top:11px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
  .btn{{text-decoration:none;font-weight:800;padding:6px 12px;border-radius:999px;font-size:.82rem;
    -webkit-tap-highlight-color:transparent}}
  .btn:active{{transform:scale(.97)}}
  .btn.open{{background:var(--accent-soft);color:var(--accent)}}
  .btn.cal{{background:var(--gold-soft);color:var(--gold)}}
  .due{{font-size:.82rem;font-weight:800;color:var(--gold)}}
  .empty{{color:var(--soft);text-align:center;padding:40px 0}}
  footer{{margin-top:26px;color:var(--soft);font-size:.8rem;text-align:center}}
</style></head><body>
<div class="wrap">
  <header>
    <h1>Your inbox, sorted</h1>
    <div class="built">{_e(summary.get('window','today')).capitalize()} · built {_e(built)}</div>
    <div class="counts">
      <span class="pill">{len(shown)} worth your time</span>
      <span class="pill">{hidden_total} junk hidden</span>
    </div>
    {hidden_line}
  </header>
  {''.join(cards)}
  <footer>Only reads your mail · junk (codes, security, promos) filtered out before summarising ·
  nothing sent, deleted, or changed. 🌱</footer>
</div>
</body></html>"""
