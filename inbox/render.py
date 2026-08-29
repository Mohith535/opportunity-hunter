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


def _priority_class(p: str) -> str:
    """Red stripe for the do-it-now tier, gold for the strategic/long-game tier."""
    return "crit" if str(p or "").strip().lower() in ("critical", "urgent", "high", "important") \
        else "strat"


_IMPORTANT = 4  # importance 0-10: at/above this an email is a "worth your time" card; below → collapsed


def _late_label(days: int) -> str:
    return "1 day late" if days == 1 else f"{days} days late"


def _soon_label(days: int) -> str:
    return "tomorrow" if days == 1 else f"in {days} days"


def _parse_dl(s: str):
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _plan_row(title: str, stripe: str, when_html: str, badge_html: str = "", href: str = "") -> str:
    """One line in the day plan. Task or email, same shape. `title` links to Gmail when href is given."""
    title = title[:140]
    t = (f'<a class="t" target="_blank" rel="noopener" href="{_e(href)}">{_e(title)}</a>'
         if href else f'<div class="t">{_e(title)}</div>')
    return f"""
      <div class="task {stripe}"><div class="tbody">{t}
        <div class="meta">{when_html}{badge_html}</div></div></div>"""


def _mail_link(gid: str) -> str:
    return f"https://mail.google.com/mail/u/0/#all/{gid}" if gid else ""


def _email_card(it: dict) -> str:
    """A full 'worth your time' email card: category, importance, sender, one-line summary, actions."""
    emoji, label = _CAT.get(it["category"], ("✉️", it["category"].title()))
    imp = it["importance"]
    dl = it.get("deadline") or ""
    actions = []
    href = _mail_link(it.get("id") or "")
    if href:  # jump straight to the real email in Gmail
        actions.append('<a class="btn open" target="_blank" rel="noopener" '
                       f'href="{_e(href)}">✉️ Open email</a>')
    if dl:
        cal = gcal_link(it["subject"], dl)
        if cal:
            actions.append('<a class="btn cal" target="_blank" rel="noopener" '
                           f'href="{_e(cal)}">＋ Calendar</a>')
        actions.append(f'<span class="due">⏰ {_e(dl)}</span>')
    actions_html = f'<div class="actions">{"".join(actions)}</div>' if actions else ""
    return f"""
        <article class="card imp{min(imp, 10) // 4}">
          <div class="row1">
            <span class="chip">{emoji} {_e(label)}</span>
            <span class="imp" title="importance">{imp}/10</span>
          </div>
          <div class="who">{_e(_sender_name(it["from"]))}</div>
          <div class="subj">{_e(it["subject"][:120])}</div>
          <div class="sum">{_e(it["summary"])}</div>
          {actions_html}
        </article>"""


def _render_day(day: dict | None, emails: list | None, today, lead: str = "",
                opps: list | None = None) -> str:
    """The 'Today' plan: your TaskFlow tasks, your email deadlines, and OPHunter's closing
    opportunities woven into ONE agenda — Overdue → Today → Coming up → Opportunities closing, led by a
    'do this first' line. Read-only. '' when there's nothing to show."""
    day = day or {}
    emails = emails or []
    opps = opps or []
    overdue = day.get("overdue", [])
    due_tasks = day.get("due_today", [])
    up_tasks = day.get("upcoming", [])
    backlog = day.get("backlog_count", 0)

    # Email deadlines within the next week, split into today vs later.
    mail_today, mail_soon = [], []
    for e in emails:
        d = _parse_dl(e.get("deadline") or "")
        if not d or d < today or (d - today).days > 7:
            continue
        row = {"title": e.get("subject", ""), "date": d, "href": _mail_link(e.get("id") or "")}
        (mail_today if d == today else mail_soon).append(row)

    act_now = len(overdue) + len(due_tasks) + len(mail_today)
    has_soon = bool(up_tasks or mail_soon or opps)
    if act_now == 0 and not has_soon and backlog == 0:
        return ""  # nothing dated and nothing on the list — stay quiet

    blocks = []

    # ── Overdue (tasks) ──
    shown_over = overdue[:12]
    if shown_over:
        rows = [_plan_row(t["title"], _priority_class(t["priority"]),
                          f'<span class="late">{_e(_late_label(t["days_over"]))}</span>',
                          f'<span class="ptag">{_e(t["priority"])}</span>' if t.get("priority") else "")
                for t in shown_over]
        blocks.append(f'<div class="tier-lbl over">Overdue</div>{"".join(rows)}')

    # ── Today (tasks + email deadlines dated today) ──
    today_rows = []
    for t in due_tasks:
        today_rows.append(_plan_row(
            t["title"], _priority_class(t["priority"]), '<span class="today-tag">due today</span>',
            f'<span class="ptag">{_e(t["priority"])}</span>' if t.get("priority") else ""))
    for m in mail_today:
        today_rows.append(_plan_row(m["title"], "mail", '<span class="today-tag">due today</span>',
                                    '<span class="src">✉ mail</span>', m["href"]))
    if today_rows:
        blocks.append(f'<div class="tier-lbl today">Today</div>{"".join(today_rows)}')

    # ── Coming up (next 7 days: email deadlines + upcoming tasks, soonest first) ──
    soon = [(m["date"], "mail", m) for m in mail_soon]
    for t in up_tasks:
        d = _parse_dl(t["date"])
        if d:
            soon.append((d, "task", t))
    soon.sort(key=lambda x: x[0])
    if soon:
        rows = []
        for d, kind, obj in soon:
            when = f'<span class="soon">{_e(_soon_label((d - today).days))}</span>'
            if kind == "mail":
                rows.append(_plan_row(obj["title"], "mail", when,
                                      '<span class="src">✉ mail</span>', obj["href"]))
            else:
                rows.append(_plan_row(
                    obj["title"], _priority_class(obj["priority"]), when,
                    f'<span class="ptag">{_e(obj["priority"])}</span>' if obj.get("priority") else ""))
        blocks.append(f'<div class="tier-lbl">Coming up</div>{"".join(rows)}')

    # ── Opportunities closing (OPHunter's radar: ranked opportunities with a deadline soon) ──
    if opps:
        opps = sorted(opps, key=lambda o: str(o.get("date") or "9999"))
        rows = []
        for o in opps[:8]:
            d = _parse_dl(o.get("date"))
            when = (f'<span class="soon">{_e(_soon_label((d - today).days))}</span>'
                    if d else "")
            rows.append(_plan_row(o.get("title", ""), "opp", when,
                                  '<span class="src opp">🎯 opportunity</span>', o.get("url", "")))
        blocks.append(f'<div class="tier-lbl opp">Opportunities closing</div>{"".join(rows)}')

    extra = []
    if len(overdue) > len(shown_over):
        extra.append(f"+{len(overdue) - len(shown_over)} more overdue")
    if backlog:
        extra.append(f"{backlog} on your list")
    note = f'<div class="day-note">{_e(" · ".join(extra))}</div>' if extra else ""
    if act_now == 0 and not blocks:
        blocks = ['<div class="day-note calm">Nothing due today. 🌿</div>']

    pill = f"{act_now} to handle" if act_now else ("planned" if has_soon else "all clear")
    lead_html = f'<div class="lead">▶ {_e(lead)}</div>' if lead else ""
    return f"""
    <section class="day">
      <div class="day-head"><h2>Today</h2><span class="pill">{_e(pill)}</span></div>
      {lead_html}
      {''.join(blocks)}
      {note}
    </section>"""


def render_html(summary: dict) -> str:
    shown = summary.get("shown", [])
    hidden = summary.get("hidden", {})
    hidden_total = sum(hidden.values())
    built = datetime.now().strftime("%A, %d %B %Y · %I:%M %p")

    today = datetime.now().date()
    important = [it for it in shown if it.get("importance", 0) >= _IMPORTANT]
    other = [it for it in shown if it.get("importance", 0) < _IMPORTANT]

    cards = [_email_card(it) for it in important]
    if not important:
        msg = ("Nothing urgent right now — a quiet inbox is a good inbox. 🌿" if other
               else "Nothing important right now. A quiet inbox is a good inbox. 🌿")
        cards.append(f'<p class="empty">{msg}</p>')

    # Everything else: lower-priority mail (promos, newsletters, FYIs) — visible, just tucked away so
    # it never buries the signal. The user asked to see every email except OTP/security.
    more_html = ""
    if other:
        rows = []
        for it in other:
            href = _mail_link(it.get("id") or "")
            who = _e(_sender_name(it["from"]))
            subj = _e(it["subject"][:110])
            inner = f'<span class="mwho">{who}</span> — {subj}'
            rows.append(f'<a class="mrow" target="_blank" rel="noopener" href="{_e(href)}">{inner}</a>'
                        if href else f'<div class="mrow">{inner}</div>')
        more_html = (f'<details class="more"><summary>Everything else ({len(other)})</summary>'
                     f'{"".join(rows)}</details>')

    hidden_line = ""
    if hidden_total:
        bits = " · ".join(f"{v} {_e(k)}" for k, v in hidden.items())
        hidden_line = f'<div class="hidden">🔒 Hid {hidden_total} code/security email(s): {bits}</div>'

    day_html = _render_day(summary.get("day"), shown, today, summary.get("lead", ""),
                           summary.get("opps"))
    inbox_head = '<h2 class="sec">Inbox</h2>' if day_html else ""
    other_pill = f'<span class="pill soft">{len(other)} more</span>' if other else ""

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
  .pill.soft{{background:var(--line);color:var(--soft)}}
  .hidden{{color:var(--soft);font-size:.85rem;margin:6px 0 18px}}
  .sec{{font-size:.78rem;font-weight:800;text-transform:uppercase;letter-spacing:.06em;
    color:var(--soft);margin:22px 2px 10px}}
  .day{{margin:14px 0 8px}}
  .day-head{{display:flex;align-items:center;gap:9px;margin:2px 2px 11px}}
  .day-head h2{{font-size:1.08rem;margin:0;letter-spacing:-.01em}}
  .lead{{background:var(--accent-soft);color:var(--accent);font-weight:800;font-size:1rem;
    line-height:1.4;padding:13px 15px;border-radius:14px;margin:0 0 14px;letter-spacing:-.005em}}
  .task{{display:flex;background:var(--surface);border:1px solid var(--line);
    border-left:4px solid var(--line);border-radius:14px;padding:11px 13px;margin-bottom:8px;
    box-shadow:var(--sh)}}
  .task.crit{{border-left-color:var(--hi)}} .task.strat{{border-left-color:var(--gold)}}
  .task.mail{{border-left-color:var(--accent)}} .task.opp{{border-left-color:var(--gold)}}
  .task .t{{font-weight:700;font-size:.95rem;line-height:1.34;color:var(--ink);
    text-decoration:none;display:block}}
  a.t:active{{opacity:.7}}
  .meta{{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin-top:5px}}
  .late{{color:var(--hi);font-weight:800;font-size:.76rem;font-variant-numeric:tabular-nums}}
  .today-tag{{color:var(--gold);font-weight:800;font-size:.76rem}}
  .soon{{color:var(--accent);font-weight:800;font-size:.76rem}}
  .src{{color:var(--soft);font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em}}
  .src.opp{{color:var(--gold)}}
  .ptag{{color:var(--soft);font-size:.7rem;font-weight:700;text-transform:uppercase;
    letter-spacing:.04em}}
  .tier-lbl{{font-size:.72rem;font-weight:800;text-transform:uppercase;letter-spacing:.05em;
    color:var(--soft);margin:12px 2px 7px}}
  .tier-lbl.over{{color:var(--hi)}} .tier-lbl.today{{color:var(--gold)}}
  .tier-lbl.opp{{color:var(--gold)}}
  .day-note{{color:var(--soft);font-size:.85rem;margin:8px 2px 0}}
  .day-note.calm{{margin:2px 2px 8px}}
  .more{{margin:2px 0 4px;border:1px solid var(--line);border-radius:14px;background:var(--surface);
    box-shadow:var(--sh);overflow:hidden}}
  .more>summary{{cursor:pointer;padding:12px 15px;font-weight:800;font-size:.9rem;color:var(--soft);
    list-style:none;-webkit-tap-highlight-color:transparent}}
  .more>summary::-webkit-details-marker{{display:none}}
  .more>summary::after{{content:"▾";float:right;color:var(--soft)}}
  .more[open]>summary::after{{content:"▴"}}
  .mrow{{display:block;padding:10px 15px;border-top:1px solid var(--line);font-size:.9rem;
    color:var(--ink);text-decoration:none}}
  .mrow:active{{background:var(--accent-soft)}}
  .mwho{{font-weight:700}}
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
    <h1>Your day, sorted</h1>
    <div class="built">{_e(summary.get('window','today')).capitalize()} · built {_e(built)}</div>
    <div class="counts">
      <span class="pill">{len(important)} worth your time</span>
      {other_pill}
      <span class="pill soft">{hidden_total} codes hidden</span>
    </div>
    {hidden_line}
  </header>
  {day_html}
  {inbox_head}
  {''.join(cards)}
  {more_html}
  <footer>Reads your mail and your TaskFlow list · only one-time codes & security mail are hidden ·
  nothing sent, deleted, completed, or changed. 🌱</footer>
</div>
</body></html>"""
