"""
Render the scan as the "Attention OS" command-center dashboard (the design tested and approved as an
artifact), driven by REAL data.

The whole front-end (layout, CSS, views, Focus mode, filter pills, command palette, keyboard) is the
approved artifact. Here we only inject the real items and wire the actions honestly:
  - TaskFlow task rows: ✓ done / ⏰ snooze POST to the worker's /action route (applied through
    TaskFlow's own CLI on the next sync) — the same bridge as before.
  - Email rows: Open (Gmail) and Add-to-Calendar are real; "done"/"later" only clear the item from
    YOUR view (localStorage), because Gmail access is read-only and we never fake an action we cannot
    truthfully take.
  - Opportunity rows: Open the link.

Public API kept stable: render_html(summary), gcal_link(title, deadline), _sender_name(s).
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
from datetime import datetime, timedelta

_EMAIL_KIND = {"ACTION": "action", "REPLY": "action", "DEADLINE": "deadline",
               "OPPORTUNITY": "opportunity", "PERSONAL": "personal", "INFO": "info"}


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


def _mail_link(gid: str) -> str:
    return f"https://mail.google.com/mail/u/0/#all/{gid}" if gid else ""


def _parse_dl(s):
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _short_date(iso: str) -> str:
    d = _parse_dl(iso)
    return f"{d:%b} {d.day}" if d else ""


def _effort(kind: str, imp: int) -> str:
    if kind in ("opportunity", "deadline"):
        return "medium"
    return "deep" if imp >= 8 else "quick"


_IMPORTANT = 4


# ── build the real items in the shape the front-end expects ──────────────────
def _task_item(uid, t, today, overdue):
    pr = (t.get("priority") or "").strip()
    days = t.get("days_over", 0)
    due = (("1 day overdue" if days == 1 else f"{days} days overdue") if overdue else "due today")
    why = []
    if pr:
        why.append(f"You marked this {pr} yourself")
    why.append(f"{days} days overdue in TaskFlow" if overdue and days else "Due today in TaskFlow")
    imp = 9 if pr.lower() in ("critical", "urgent", "high") else 6
    return {"id": uid, "kind": "action", "title": (t.get("title") or "")[:140],
            "sender": "TaskFlow task", "source": "task", "imp": imp, "effort": "quick",
            "due": due, "why": why, "tid": t.get("id"), "href": "", "cal": ""}


def _upcoming_task_item(uid, t, today):
    d = _parse_dl(t.get("date"))
    days = (d - today).days if d else None
    due = ("tomorrow" if days == 1 else f"in {days} days") if days else "upcoming"
    pr = (t.get("priority") or "").strip()
    return {"id": uid, "kind": "deadline", "title": (t.get("title") or "")[:140],
            "sender": "TaskFlow task", "source": "task", "imp": 6, "effort": "medium",
            "due": due, "why": [f"You marked this {pr}" if pr else "On your TaskFlow list",
                                f"Due {t.get('date')}" if t.get("date") else ""],
            "tid": t.get("id"), "href": "", "cal": ""}


def _email_item(uid, e, today):
    cat = e.get("category", "INFO")
    kind = _EMAIL_KIND.get(cat, "info")
    imp = int(e.get("importance", 0) or 0)
    dl = e.get("deadline") or ""
    href = _mail_link(e.get("id") or "")
    cal = gcal_link(e.get("subject", ""), dl) if dl else ""
    due = ""
    d = _parse_dl(dl)
    if d:
        days = (d - today).days
        due = "due today" if days == 0 else (f"in {days} days" if days > 0 else f"{-days} days ago")
    lab = {"action": "Needs a response", "deadline": "Has a deadline", "opportunity": "An opportunity",
           "personal": "From a person", "info": "Low priority"}[kind]
    why = [f"{lab} · {imp}/10 to you"]
    if dl:
        why.append(f"Deadline {dl}")
    why.append(f"From {_sender_name(e.get('from', ''))}")
    return {"id": uid, "kind": kind, "title": (e.get("subject") or "")[:140],
            "sender": _sender_name(e.get("from", "")), "source": "mail", "imp": imp,
            "effort": _effort(kind, imp), "due": due, "why": why[:3],
            "tid": "", "href": href, "cal": cal}


def _opp_item(uid, o, today):
    d = _parse_dl(o.get("date"))
    days = (d - today).days if d else None
    due = ("tomorrow" if days == 1 else f"in {days} days") if days else "closing soon"
    sc = int(o.get("score", 0) or 0)
    return {"id": uid, "kind": "opportunity", "title": (o.get("title") or "")[:140],
            "source": "opp", "sender": (o.get("source") or "opportunity"), "imp": min(sc, 10),
            "effort": "medium", "due": due, "hunter": sc,
            "why": [f"Ranked {sc}/10 by Opportunity Hunter", f"Closing {due}"],
            "tid": "", "href": o.get("url", ""), "cal": ""}


def _build_data(summary: dict) -> dict:
    today = datetime.now().date()
    shown = summary.get("shown", [])
    day = summary.get("day") or {}
    opps = summary.get("opps") or []
    hidden_total = sum((summary.get("hidden") or {}).values())

    important = [e for e in shown if int(e.get("importance", 0) or 0) >= _IMPORTANT]
    other = [e for e in shown if int(e.get("importance", 0) or 0) < _IMPORTANT]

    items, uid = [], 0
    for t in day.get("overdue", []):
        uid += 1
        items.append(_task_item(uid, t, today, True))
    for t in day.get("due_today", []):
        uid += 1
        items.append(_task_item(uid, t, today, False))
    for e in important:
        uid += 1
        items.append(_email_item(uid, e, today))
    for o in opps:
        uid += 1
        items.append(_opp_item(uid, o, today))
    for t in day.get("upcoming", []):
        uid += 1
        items.append(_upcoming_task_item(uid, t, today))
    for e in other:
        uid += 1
        items.append(_email_item(uid, e, today))

    # right-rail "Today" glance: overdue + due-today, real
    today_ev = []
    for t in day.get("overdue", [])[:3]:
        d = t.get("days_over", 0)
        today_ev.append({"t": f"{d}d late", "lab": (t.get("title") or "")[:40]})
    for t in day.get("due_today", [])[:2]:
        today_ev.append({"t": "today", "lab": (t.get("title") or "")[:40]})

    # "Deadlines ahead": opportunities + upcoming tasks + email deadlines, soonest first
    up = []
    for o in opps:
        if o.get("date"):
            up.append({"date": o["date"], "lab": (o.get("title") or "")[:32], "d": _short_date(o["date"])})
    for t in day.get("upcoming", []):
        if t.get("date"):
            up.append({"date": t["date"], "lab": (t.get("title") or "")[:32], "d": _short_date(t["date"])})
    for e in shown:
        d = _parse_dl(e.get("deadline"))
        if d and d >= today:
            up.append({"date": e["deadline"], "lab": (e.get("subject") or "")[:32],
                       "d": _short_date(e["deadline"])})
    up = sorted({x["lab"]: x for x in up}.values(), key=lambda x: x["date"])[:5]

    return {"items": items, "today": today_ev, "upcoming": up, "hiddenJunk": hidden_total,
            "worthTime": len(important), "inboxTotal": len(shown)}


# ── the approved artifact front-end: CSS, body, JS (verbatim design; real actions) ──
_CSS = """
  :root{
    --bg:#0F120D; --panel:#161A12; --panel-2:#1B2016; --raise:#20261A;
    --ink:#ECEFE6; --ink-2:#B8C0AE; --soft:#8A9382; --faint:#5E6656;
    --line:#262C1D; --line-2:#323A28;
    --accent:#63C594; --accent-dim:#1E2C22; --accent-ink:#0F120D;
    --crit:#EF7350; --crit-dim:#2C1D17;
    --amber:#E3A83C; --amber-dim:#2A2213;
    --blue:#6FA8DE; --blue-dim:#182430;
    --done:#5E8B6C;
    --sans:"Hanken Grotesk",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
    --mono:"IBM Plex Mono",ui-monospace,"SFMono-Regular",Menlo,monospace;
    --sh:0 1px 2px rgba(0,0,0,.4),0 10px 30px rgba(0,0,0,.35);
    --r:14px;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
    font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased;
    background-image:radial-gradient(1200px 600px at 80% -10%, #161B12 0%, transparent 60%);
    background-attachment:fixed}
  h1,h2,h3{margin:0;font-weight:700;letter-spacing:-.01em}
  button{font-family:inherit;cursor:pointer}
  .mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
  ::selection{background:var(--accent-dim);color:var(--accent)}
  :focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:8px}
  .topbar{position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:14px;
    padding:12px 20px;background:rgba(15,18,13,.82);backdrop-filter:blur(12px);
    border-bottom:1px solid var(--line)}
  .brand{display:flex;align-items:center;gap:9px;font-weight:800;letter-spacing:-.02em}
  .brand .dot{width:9px;height:9px;border-radius:50%;background:var(--accent);box-shadow:0 0 10px var(--accent)}
  .brand small{font-family:var(--mono);font-size:.66rem;color:var(--soft);font-weight:500;
    letter-spacing:.14em;text-transform:uppercase}
  .tabs{display:flex;gap:2px;margin-left:8px}
  .tab{background:transparent;border:0;color:var(--soft);font-weight:600;font-size:.9rem;
    padding:6px 12px;border-radius:9px}
  .tab:hover{color:var(--ink-2);background:var(--panel)}
  .tab[aria-current="true"]{color:var(--ink);background:var(--panel-2)}
  .topbar .spacer{flex:1}
  .date{font-family:var(--mono);font-size:.78rem;color:var(--soft)}
  .cmd{display:flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--line-2);
    color:var(--soft);border-radius:10px;padding:7px 11px;font-size:.82rem}
  .cmd kbd{font-family:var(--mono);font-size:.7rem;background:var(--raise);border:1px solid var(--line-2);
    border-radius:5px;padding:1px 5px;color:var(--ink-2)}
  .grid{display:grid;grid-template-columns:248px minmax(0,1fr) 328px;gap:26px;
    max-width:1760px;margin:0 auto;padding:30px clamp(20px,3.2vw,52px)}
  .rail,.context{display:flex;flex-direction:column;gap:14px}
  .navcard{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:8px;box-shadow:var(--sh)}
  .navitem{display:flex;align-items:center;gap:11px;width:100%;background:transparent;border:0;
    color:var(--ink-2);font-weight:600;font-size:.92rem;padding:9px 11px;border-radius:10px;text-align:left}
  .navitem:hover{background:var(--panel-2);color:var(--ink)}
  .navitem[aria-current="true"]{background:var(--accent-dim);color:var(--accent)}
  .navitem .ico{width:16px;height:16px;flex:0 0 16px;opacity:.85}
  .navitem .n{margin-left:auto;font-family:var(--mono);font-size:.76rem;color:var(--soft)}
  .navitem[aria-current="true"] .n{color:var(--accent)}
  .railhead{font-family:var(--mono);font-size:.66rem;letter-spacing:.14em;text-transform:uppercase;
    color:var(--faint);padding:4px 12px;margin-top:4px}
  .radar{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:15px 16px;box-shadow:var(--sh)}
  .radar h3{font-family:var(--mono);font-size:.68rem;letter-spacing:.13em;text-transform:uppercase;
    color:var(--soft);font-weight:600;margin-bottom:12px}
  .rrow{margin:10px 0}
  .rrow .rt{display:flex;justify-content:space-between;font-size:.8rem;color:var(--ink-2);margin-bottom:5px}
  .rrow .rt b{font-family:var(--mono);color:var(--ink)}
  .bar{height:6px;border-radius:99px;background:var(--raise);overflow:hidden}
  .bar i{display:block;height:100%;border-radius:99px}
  .center{display:flex;flex-direction:column;gap:22px;min-width:0}
  .brief{background:linear-gradient(160deg,var(--panel-2),var(--panel));border:1px solid var(--line-2);
    border-radius:18px;padding:20px 22px;box-shadow:var(--sh)}
  .brief .hi{font-size:1.6rem;font-weight:800;letter-spacing:-.02em}
  .brief .status{color:var(--ink-2);margin-top:3px;font-size:.95rem}
  .brief .status b{color:var(--ink);font-weight:700}
  .first{display:flex;align-items:flex-start;gap:12px;margin-top:16px;padding:13px 14px;
    background:var(--accent-dim);border:1px solid #244A38;border-radius:12px}
  .first .lbl{font-family:var(--mono);font-size:.62rem;letter-spacing:.14em;text-transform:uppercase;
    color:var(--accent);font-weight:600}
  .first .txt{font-weight:700;color:var(--ink);margin-top:3px;line-height:1.35}
  .first .go{margin-left:auto;flex:0 0 auto;align-self:center;background:var(--accent);color:var(--accent-ink);
    border:0;font-weight:700;font-size:.82rem;padding:9px 14px;border-radius:10px;white-space:nowrap}
  .first .go:hover{filter:brightness(1.08)}
  .briefline{display:flex;gap:16px;flex-wrap:wrap;margin-top:15px;padding-top:14px;border-top:1px solid var(--line)}
  .briefline .b{display:flex;flex-direction:column;gap:1px}
  .briefline .b .k{font-family:var(--mono);font-size:1.15rem;font-weight:600;color:var(--ink)}
  .briefline .b .v{font-size:.74rem;color:var(--soft)}
  .group{margin-top:10px}
  .grouphead{display:flex;align-items:center;gap:10px;padding:0 4px 11px;cursor:pointer;user-select:none}
  .grouphead .g-ico{width:8px;height:8px;border-radius:50%;flex:0 0 8px}
  .grouphead h2{font-size:.82rem;font-family:var(--mono);letter-spacing:.1em;text-transform:uppercase;
    color:var(--ink-2);font-weight:600}
  .grouphead .cnt{font-family:var(--mono);font-size:.8rem;color:var(--soft)}
  .grouphead .chev{margin-left:auto;color:var(--faint);font-size:.8rem;transition:transform .18s ease}
  .group.collapsed .chev{transform:rotate(-90deg)}
  .group.collapsed .items{display:none}
  .items{display:flex;flex-direction:column;gap:8px}
  .pills{display:flex;gap:7px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
  .pill{background:var(--panel);border:1px solid var(--line-2);color:var(--ink-2);font-weight:600;
    font-size:.82rem;padding:6px 12px;border-radius:99px;display:inline-flex;gap:6px;align-items:center;transition:all .13s}
  .pill b{font-family:var(--mono);color:var(--soft);font-weight:600}
  .pill:hover{border-color:var(--soft);color:var(--ink)}
  .pill.on{background:var(--accent-dim);border-color:#2c5540;color:var(--accent)}
  .pill.on b{color:var(--accent)}
  .clearlow{background:transparent;border:1px solid var(--line-2);color:var(--soft);font-weight:600;
    font-size:.78rem;padding:6px 11px;border-radius:99px;margin-left:auto}
  .clearlow:hover{color:var(--ink);border-color:var(--soft)}
  .ring{flex:0 0 auto;text-align:center;line-height:1}
  .item{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:12px 14px;
    display:flex;gap:12px;align-items:flex-start;position:relative;transition:border-color .15s,transform .12s,opacity .2s}
  .item:hover{border-color:var(--line-2)}
  .item.leaving{opacity:0;transform:translateX(14px)}
  .item .stripe{position:absolute;left:0;top:11px;bottom:11px;width:3px;border-radius:99px}
  .item .body{flex:1;min-width:0}
  .item .r1{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:3px}
  .chip{font-family:var(--mono);font-size:.6rem;letter-spacing:.1em;text-transform:uppercase;
    font-weight:600;padding:3px 7px;border-radius:6px}
  .item .title{font-weight:600;font-size:.98rem;line-height:1.3;color:var(--ink)}
  .item .meta{color:var(--soft);font-size:.8rem;margin-top:2px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
  .item .meta .sep{opacity:.4}
  .effort{font-family:var(--mono);font-size:.68rem;color:var(--soft);border:1px solid var(--line-2);padding:1px 6px;border-radius:6px}
  .whybtn{background:transparent;border:0;color:var(--accent);font-weight:600;font-size:.78rem;padding:2px 0;
    display:inline-flex;align-items:center;gap:4px}
  .whybtn:hover{text-decoration:underline}
  .why{margin-top:9px;padding:10px 12px;background:var(--panel-2);border:1px solid var(--line);
    border-radius:10px;font-size:.82rem;color:var(--ink-2)}
  .why ul{margin:0;padding-left:16px} .why li{margin:2px 0} .why li::marker{color:var(--accent)}
  .why .hunter{margin-top:8px;padding-top:8px;border-top:1px dashed var(--line-2);color:var(--soft);font-size:.78rem}
  .why .hunter b{color:var(--accent);font-family:var(--mono)}
  .rail-acts{display:flex;flex-direction:column;gap:6px;flex:0 0 auto}
  .act{width:34px;height:34px;border-radius:9px;border:1px solid transparent;background:transparent;
    color:var(--faint);display:flex;align-items:center;justify-content:center;transition:all .13s}
  .act:hover{color:var(--ink);border-color:var(--soft);transform:translateY(-1px)}
  .act.done:hover{color:var(--accent);border-color:var(--accent)}
  .act svg{width:16px;height:16px}
  .empty{text-align:center;padding:46px 20px;color:var(--soft)}
  .empty .big{font-size:2.4rem;margin-bottom:8px}
  .empty h3{color:var(--ink-2);font-weight:700;font-size:1.05rem}
  .ctxcard{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:15px 16px;box-shadow:var(--sh)}
  .ctxcard h3{font-family:var(--mono);font-size:.68rem;letter-spacing:.13em;text-transform:uppercase;
    color:var(--soft);font-weight:600;margin-bottom:12px;display:flex;justify-content:space-between}
  .tl{position:relative;padding-left:14px}
  .tl .ev{position:relative;padding:0 0 14px 12px;border-left:1px solid var(--line-2)}
  .tl .ev:last-child{border-left-color:transparent;padding-bottom:0}
  .tl .ev::before{content:"";position:absolute;left:-4px;top:4px;width:7px;height:7px;border-radius:50%;background:var(--soft)}
  .tl .ev.now::before{background:var(--accent);box-shadow:0 0 8px var(--accent)}
  .tl .t{font-family:var(--mono);font-size:.72rem;color:var(--soft)}
  .tl .lab{font-size:.86rem;color:var(--ink-2);font-weight:500}
  .up{display:flex;justify-content:space-between;align-items:baseline;padding:7px 0;border-bottom:1px solid var(--line)}
  .up:last-child{border-bottom:0}
  .up .lab{font-size:.86rem;color:var(--ink-2)}
  .up .d{font-family:var(--mono);font-size:.74rem;color:var(--amber)}
  .health .hrow{display:flex;align-items:center;gap:9px;font-size:.84rem;color:var(--ink-2);margin:9px 0}
  .health .hrow svg{width:15px;height:15px;flex:0 0 15px;color:var(--soft);opacity:.9}
  .health .hrow .k{margin-left:auto;font-family:var(--mono);color:var(--ink)}
  .saved{margin-top:11px;padding-top:11px;border-top:1px solid var(--line);font-size:.8rem;color:var(--soft)}
  .saved b{color:var(--accent)}
  .focus{min-height:calc(100dvh - 58px);display:flex;align-items:center;justify-content:center;padding:24px}
  .focuscard{max-width:560px;width:100%;text-align:center}
  .focuscard .prog{font-family:var(--mono);color:var(--soft);letter-spacing:.2em;font-size:.8rem}
  .focuscard .chip{display:inline-block;margin:18px 0 14px}
  .focuscard h2{font-size:1.9rem;line-height:1.2;letter-spacing:-.02em}
  .focuscard .fmeta{color:var(--ink-2);margin-top:14px;font-size:.95rem}
  .focuscard .fwhy{margin:22px auto 0;max-width:420px;text-align:left;background:var(--panel);
    border:1px solid var(--line);border-radius:12px;padding:14px 16px;font-size:.86rem;color:var(--ink-2)}
  .focuscard .fwhy ul{margin:6px 0 0;padding-left:16px} .focuscard .fwhy li::marker{color:var(--accent)}
  .factions{display:flex;gap:10px;justify-content:center;margin-top:26px;flex-wrap:wrap}
  .fbtn{border:1px solid var(--line-2);background:var(--panel-2);color:var(--ink);font-weight:700;
    font-size:.95rem;padding:12px 22px;border-radius:12px;display:inline-flex;align-items:center;gap:8px;min-height:48px}
  .fbtn.primary{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
  .fbtn svg{width:18px;height:18px}
  .fbtn:hover{transform:translateY(-1px)}
  .fbtn kbd{font-family:var(--mono);font-size:.7rem;opacity:.7}
  .focusdone{text-align:center;padding:60px 20px}
  .focusdone .big{font-size:3rem}
  .scrim{position:fixed;inset:0;z-index:60;background:rgba(6,8,5,.62);backdrop-filter:blur(3px);
    display:flex;align-items:flex-start;justify-content:center;padding-top:14vh}
  .palette{width:min(560px,92vw);background:var(--panel);border:1px solid var(--line-2);border-radius:16px;
    box-shadow:0 24px 80px rgba(0,0,0,.6);overflow:hidden}
  .palette input{width:100%;background:transparent;border:0;color:var(--ink);font-family:var(--sans);
    font-size:1.05rem;padding:16px 18px;outline:none;border-bottom:1px solid var(--line)}
  .palette input::placeholder{color:var(--faint)}
  .plist{max-height:340px;overflow-y:auto;padding:6px}
  .prow{display:flex;align-items:center;gap:12px;padding:11px 12px;border-radius:10px;color:var(--ink-2);font-size:.92rem}
  .prow[aria-selected="true"]{background:var(--accent-dim);color:var(--accent)}
  .prow .pk{margin-left:auto;font-family:var(--mono);font-size:.72rem;color:var(--faint)}
  .prow .pi{width:16px;height:16px;opacity:.8}
  .toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%) translateY(16px);z-index:70;
    display:flex;align-items:center;gap:14px;background:var(--raise);border:1px solid var(--line-2);
    color:var(--ink);font-size:.88rem;font-weight:600;padding:11px 15px;border-radius:12px;
    box-shadow:var(--sh);opacity:0;pointer-events:none;transition:opacity .2s,transform .2s}
  .toast.show{opacity:1;transform:translateX(-50%) translateY(0);pointer-events:auto}
  .toast button{background:transparent;border:0;color:var(--accent);font-weight:700;font-size:.86rem}
  .toast .u{font-family:var(--mono);font-size:.7rem;color:var(--soft);border:1px solid var(--line-2);padding:1px 5px;border-radius:5px}
  .botnav{position:fixed;left:0;right:0;bottom:0;z-index:40;display:none;
    background:rgba(15,18,13,.92);backdrop-filter:blur(12px);border-top:1px solid var(--line);
    padding:6px 8px calc(6px + env(safe-area-inset-bottom))}
  .botnav .bwrap{display:flex;justify-content:space-around;max-width:520px;margin:0 auto}
  .bn{display:flex;flex-direction:column;align-items:center;gap:3px;background:transparent;border:0;
    color:var(--soft);font-size:.66rem;font-weight:600;padding:7px 14px;border-radius:10px;min-width:60px}
  .bn svg{width:20px;height:20px}
  .bn[aria-current="true"]{color:var(--accent)}
  @media(max-width:1080px){ .grid{grid-template-columns:minmax(0,1fr) 290px} .rail{display:none} }
  @media(max-width:820px){
    .topbar .tabs,.topbar .cmd{display:none}
    .grid{grid-template-columns:minmax(0,1fr);padding:14px 14px 92px}
    .context{order:2}
    .botnav{display:block}
    .brief{border-radius:16px;padding:17px 17px}
    .brief .hi{font-size:1.35rem}
    .first .go{padding:8px 12px}
  }
  @media(prefers-reduced-motion:reduce){*{transition:none!important}}
"""

_BODY = """
<div class="topbar">
  <div class="brand"><span class="dot"></span>Inbox Scout <small>attention os</small></div>
  <div class="tabs" id="tabs">
    <button class="tab" data-view="today" aria-current="true">Today</button>
    <button class="tab" data-view="focus">Focus</button>
    <button class="tab" data-view="later">Later</button>
    <button class="tab" data-view="done">Done</button>
  </div>
  <div class="spacer"></div>
  <button class="cmd" id="cmdBtn">Search or run <kbd>Ctrl K</kbd></button>
  <div class="date mono" id="dateStr"></div>
</div>
<div id="v-today">
  <div class="grid">
    <aside class="rail"><div class="navcard" id="railNav"></div><div class="radar" id="radar"></div></aside>
    <main class="center"><section class="brief" id="brief"></section><div id="queue"></div></main>
    <aside class="context" id="context"></aside>
  </div>
</div>
<div id="v-focus" hidden><div class="focus" id="focusWrap"></div></div>
<div id="v-later" hidden><div class="grid" style="grid-template-columns:minmax(0,1fr)">
  <main class="center"><section class="brief"><div class="hi">Later</div>
  <div class="status">Set aside without losing them. They come back when you choose. Nothing here nags you now.</div></section>
  <div id="laterList"></div></main></div></div>
<div id="v-done" hidden><div class="grid" style="grid-template-columns:minmax(0,1fr)">
  <main class="center"><section class="brief"><div class="hi">Cleared</div>
  <div class="status" id="doneStatus"></div></section>
  <div id="doneList"></div></main></div></div>
<nav class="botnav"><div class="bwrap" id="botnav">
  <button class="bn" data-view="today" aria-current="true">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12l9-9 9 9M5 10v10h14V10"/></svg>Today</button>
  <button class="bn" data-view="focus">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="2.5" fill="currentColor"/></svg>Focus</button>
  <button class="bn" data-view="later">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>Later</button>
  <button class="bn" data-view="done">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>Done</button>
</div></nav>
<div class="toast" id="toast"></div>
"""

# The front-end script. __DATA__ is replaced with the real JSON. Kept out of any f-string so its { }
# don't need escaping. Actions are wired to the honest backends (task -> worker bridge; mail -> Gmail).
_JS = r"""
(function(){
  "use strict";
  var $=function(s,r){return (r||document).querySelector(s);};
  var esc=function(s){return String(s==null?"":s).replace(/[&<>"']/g,function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];});};

  var DATA=__DATA__;
  var base=location.pathname.replace(/\/?$/,'/');
  function postAction(tid,act){ if(tid==null||tid==="")return;
    try{ fetch(base+'action',{method:'POST',headers:{'content-type':'application/json'},
      body:JSON.stringify({id:String(tid),act:act})}).catch(function(){}); }catch(e){} }
  function byId(id){ return ITEMS.filter(function(i){return i.id===id;})[0]; }

  var KIND = {
    action:      {label:"Needs action", color:"var(--crit)",  dim:"var(--crit-dim)"},
    deadline:    {label:"Deadline",     color:"var(--amber)", dim:"var(--amber-dim)"},
    opportunity: {label:"Opportunity",  color:"var(--accent)",dim:"var(--accent-dim)"},
    personal:    {label:"Personal",     color:"var(--blue)",  dim:"var(--blue-dim)"},
    info:        {label:"Info",         color:"var(--soft)",  dim:"var(--panel-2)"}
  };
  var EFFORT={quick:{t:"Quick",m:4},medium:{t:"Medium",m:15},deep:{t:"Deep",m:45}};

  var ITEMS=DATA.items;
  var DONE_SEED=[];
  var CAL=DATA.today;
  var UPCOMING=DATA.upcoming;
  var HIDDEN_JUNK=DATA.hiddenJunk;

  var state={view:"today",done:{},later:{},expanded:{},collapsed:{},focusIdx:0,filter:null};
  try{var s=JSON.parse(localStorage.getItem("aos")||"{}");
    state.done=s.done||{};state.later=s.later||{};}catch(e){}
  function persist(){try{localStorage.setItem("aos",JSON.stringify({done:state.done,later:state.later}));}catch(e){}}

  function active(){return ITEMS.filter(function(i){return !state.done[i.id]&&!state.later[i.id];});}
  function laterItems(){return ITEMS.filter(function(i){return state.later[i.id]&&!state.done[i.id];});}
  function doneItems(){return ITEMS.filter(function(i){return state.done[i.id];});}
  function greeting(){var h=new Date().getHours();return h<12?"Good morning":h<17?"Good afternoon":"Good evening";}

  var GROUPS=[
    {kind:"action",head:"Needs action"},{kind:"deadline",head:"Deadlines"},
    {kind:"opportunity",head:"Opportunities"},{kind:"personal",head:"Personal"},{kind:"info",head:"Low priority"}
  ];

  var IC={
    done:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M20 6L9 17l-5-5"/></svg>',
    later:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    cal:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4.5" width="18" height="16" rx="2"/><path d="M3 9h18M8 2.5v4M16 2.5v4"/></svg>',
    open:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 17L17 7M9 7h8v8"/></svg>'
  };

  function itemHTML(it){
    var k=KIND[it.kind]||KIND.info;
    var whyOpen=state.expanded[it.id];
    var hunter=it.hunter?'<div class="hunter">Detected in your inbox. Opportunity Hunter relevance <b>'+it.hunter+'/10</b></div>':'';
    var whyList=(it.why||[]).filter(Boolean).map(function(w){return '<li>'+esc(w)+'</li>';}).join('');
    var due=it.due?'<span class="sep">&middot;</span><span style="color:'+(/overdue|late/.test(it.due)?"var(--crit)":(it.kind==="deadline"?"var(--amber)":"var(--soft)"))+'">'+esc(it.due)+'</span>':'';
    var src=it.source==="task"?'<span class="sep">&middot;</span><span style="color:var(--soft)">from TaskFlow</span>':'';
    return '<article class="item" data-id="'+it.id+'">'+
      '<span class="stripe" style="background:'+k.color+'"></span>'+
      '<div class="body">'+
        '<div class="r1"><span class="chip" style="background:'+k.dim+';color:'+k.color+'">'+k.label+'</span>'+
          '<span class="effort">'+(EFFORT[it.effort]?EFFORT[it.effort].t:"Quick")+'</span></div>'+
        '<div class="title">'+esc(it.title)+'</div>'+
        '<div class="meta">'+esc(it.sender)+due+src+
          ' <button class="whybtn" data-why="'+it.id+'">'+(whyOpen?"Hide why":"Why?")+'</button></div>'+
        (whyOpen?'<div class="why"><b style="color:var(--ink-2);font-size:.72rem;font-family:var(--mono);letter-spacing:.1em;text-transform:uppercase">Why this matters</b><ul>'+whyList+'</ul>'+hunter+'</div>':'')+
      '</div>'+
      '<div class="rail-acts">'+
        '<button class="act done" data-act="done" data-id="'+it.id+'" aria-label="Done" title="Done (D)">'+IC.done+'</button>'+
        '<button class="act" data-act="later" data-id="'+it.id+'" aria-label="Later" title="Later (L)">'+IC.later+'</button>'+
        (it.cal?'<button class="act" data-act="cal" data-id="'+it.id+'" aria-label="Add to calendar" title="Calendar">'+IC.cal+'</button>':'')+
        (it.href?'<button class="act" data-act="open" data-id="'+it.id+'" aria-label="Open" title="Open">'+IC.open+'</button>':'')+
      '</div></article>';
  }

  function pillsHTML(items){
    var counts={};GROUPS.forEach(function(g){counts[g.kind]=0;});
    items.forEach(function(i){counts[i.kind]=(counts[i.kind]||0)+1;});
    var p='<button class="pill'+(state.filter===null?' on':'')+'" data-filter="all">All <b>'+items.length+'</b></button>';
    GROUPS.forEach(function(g){if(!counts[g.kind])return;
      p+='<button class="pill'+(state.filter===g.kind?' on':'')+'" data-filter="'+g.kind+'">'+g.head+' <b>'+counts[g.kind]+'</b></button>';});
    if(counts.info)p+='<button class="clearlow" data-act="clearlow" title="Set low-priority aside">Clear '+counts.info+' low</button>';
    return '<div class="pills">'+p+'</div>';
  }
  function groupHTML(g,items,showAll){
    var gi=items.filter(function(i){return i.kind===g.kind;});
    if(!gi.length)return "";
    var col=state.collapsed[g.kind]?" collapsed":"";
    var shown=showAll?gi:gi.slice(0,4), rest=showAll?[]:gi.slice(4);
    var k=KIND[g.kind];
    return '<section class="group'+col+'" data-group="'+g.kind+'">'+
      '<div class="grouphead" data-toggle="'+g.kind+'"><span class="g-ico" style="background:'+k.color+'"></span>'+
        '<h2>'+g.head+'</h2><span class="cnt">'+gi.length+'</span><span class="chev">&#9662;</span></div>'+
      '<div class="items">'+shown.map(itemHTML).join('')+
        (rest.length?'<button class="whybtn" style="align-self:flex-start;padding:6px 4px" data-more="'+g.kind+'">+ '+rest.length+' more</button>'+
          '<div data-morebox="'+g.kind+'" hidden>'+rest.map(itemHTML).join('')+'</div>':'')+
      '</div></section>';
  }
  function renderQueue(){
    var items=active(), q=$("#queue"), bar=pillsHTML(items);
    if(!items.length){
      q.innerHTML=bar+'<div class="empty"><div class="big">&#127811;</div><h3>You are clear.</h3>'+
        '<p>Nothing is waiting on you right now. That is the whole point.</p></div>';
      return;
    }
    var groups=state.filter?GROUPS.filter(function(g){return g.kind===state.filter;}):GROUPS;
    var html=bar, any=false;
    groups.forEach(function(g){var gh=groupHTML(g,items,!!state.filter);if(gh){any=true;html+=gh;}});
    if(!any)html+='<div class="empty"><div class="big">&#10003;</div><h3>Nothing in this filter.</h3><p>Tap <b>All</b>.</p></div>';
    q.innerHTML=html;
  }

  function renderBrief(){
    var items=active();
    var need=items.filter(function(i){return i.kind==="action";}).length;
    var dl=items.filter(function(i){return i.due&&/overdue|late|today|days/.test(i.due);}).length;
    var opp=items.filter(function(i){return i.kind==="opportunity";}).length;
    var overdue=items.filter(function(i){return i.due&&/overdue|late/.test(i.due);}).length;
    var first=items.slice().sort(function(a,b){return b.imp-a.imp;})[0];
    var mins=items.reduce(function(s,i){return s+(EFFORT[i.effort]?EFFORT[i.effort].m:4);},0);
    var firstHTML=first?'<div class="first"><div><div class="lbl">Do this first</div>'+
      '<div class="txt">'+esc(first.title)+'</div></div>'+
      '<button class="go" data-act="focusfirst">Start &#8594;</button></div>':'';
    var cleared=Object.keys(state.done).length, tot=cleared+items.length;
    var pct=tot?Math.round(cleared/tot*100):0, RC=113.1, off=RC*(1-pct/100);
    var ring='<div class="ring" title="'+cleared+' of '+tot+' cleared"><svg width="50" height="50" viewBox="0 0 44 44">'+
      '<circle cx="22" cy="22" r="18" fill="none" stroke="var(--raise)" stroke-width="4"/>'+
      '<circle cx="22" cy="22" r="18" fill="none" stroke="var(--accent)" stroke-width="4" stroke-linecap="round" stroke-dasharray="'+RC+'" stroke-dashoffset="'+off+'" transform="rotate(-90 22 22)"/>'+
      '<text x="22" y="26" text-anchor="middle" font-family="IBM Plex Mono,monospace" font-size="12" fill="var(--ink)">'+cleared+'</text>'+
      '</svg><div style="font-size:.6rem;color:var(--soft);font-family:var(--mono);margin-top:1px">cleared</div></div>';
    $("#brief").innerHTML='<div style="display:flex;align-items:flex-start;gap:14px">'+
      '<div style="flex:1;min-width:0"><div class="hi">'+greeting()+', Mohith.</div>'+
      '<div class="status"><b>'+items.length+'</b> worth your attention &middot; '+need+' need action &middot; '+
        opp+' opportunities &middot; '+overdue+' overdue</div></div>'+ring+'</div>'+
      firstHTML+
      '<div class="briefline">'+
        '<div class="b"><span class="k mono">'+items.length+'</span><span class="v">to review</span></div>'+
        '<div class="b"><span class="k mono">'+dl+'</span><span class="v">time-sensitive</span></div>'+
        '<div class="b"><span class="k mono">~'+mins+'m</span><span class="v">focus if you clear it</span></div>'+
        '<div class="b"><span class="k mono">'+HIDDEN_JUNK+'</span><span class="v">junk you never saw</span></div>'+
      '</div>';
  }

  function renderRail(){
    var items=active();
    var counts={action:0,deadline:0,opportunity:0,personal:0,info:0};
    items.forEach(function(i){counts[i.kind]=(counts[i.kind]||0)+1;});
    var nav=[["today","Today",items.length],["focus","Focus",""],["later","Later",laterItems().length],["done","Done",doneItems().length]];
    var h=nav.map(function(n){return '<button class="navitem" data-view="'+n[0]+'"'+(state.view===n[0]?' aria-current="true"':'')+'>'+
      '<span>'+n[1]+'</span>'+(n[2]!==""?'<span class="n">'+n[2]+'</span>':'')+'</button>';}).join('');
    h+='<div class="railhead">By type</div>';
    GROUPS.forEach(function(g){var k=KIND[g.kind];
      h+='<button class="navitem" data-filter="'+g.kind+'"'+(state.filter===g.kind?' aria-current="true"':'')+'>'+
        '<span class="ico" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:'+k.color+'"></span>'+
        '<span>'+g.head+'</span><span class="n">'+(counts[g.kind]||0)+'</span></button>';});
    $("#railNav").innerHTML=h;
    var wk=UPCOMING.length, crit=items.filter(function(i){return i.imp>=8;}).length,
        waiting=items.filter(function(i){return i.kind==="action";}).length, opp=counts.opportunity;
    function bar(lab,val,max,color){var pct=Math.min(100,Math.round(val/max*100));
      return '<div class="rrow"><div class="rt"><span>'+lab+'</span><b>'+val+'</b></div>'+
        '<div class="bar"><i style="width:'+pct+'%;background:'+color+'"></i></div></div>';}
    $("#radar").innerHTML='<h3>Attention radar</h3>'+
      bar("Critical",crit,4,"var(--crit)")+bar("Deadlines ahead",wk,6,"var(--amber)")+
      bar("Waiting on you",waiting,5,"var(--blue)")+bar("Opportunities",opp,6,"var(--accent)");
  }

  function renderContext(){
    var cal=CAL.length?CAL.map(function(e){return '<div class="ev"><div class="t">'+esc(e.t)+'</div>'+
      '<div class="lab">'+esc(e.lab)+'</div></div>';}).join(''):
      '<div class="lab" style="color:var(--soft);font-size:.86rem">Nothing dated for today.</div>';
    var up=UPCOMING.length?UPCOMING.map(function(u){return '<div class="up"><span class="lab">'+esc(u.lab)+'</span><span class="d">'+esc(u.d)+'</span></div>';}).join(''):
      '<div class="up"><span class="lab" style="color:var(--soft)">No deadlines ahead.</span></div>';
    var dcount=Object.keys(state.done).length, lcount=laterItems().length;
    $("#context").innerHTML=
      '<div class="ctxcard"><h3>Today <span class="mono" style="color:var(--soft)">'+$("#dateStr").textContent+'</span></h3><div class="tl">'+cal+'</div></div>'+
      '<div class="ctxcard"><h3>Deadlines ahead</h3>'+up+'</div>'+
      '<div class="ctxcard health"><h3>Inbox health</h3>'+
        '<div class="hrow">'+IC.done+' Cleared this session <span class="k">'+dcount+'</span></div>'+
        '<div class="hrow">'+IC.later+' Set aside <span class="k">'+lcount+'</span></div>'+
        '<div class="hrow">'+IC.cal+' In your inbox <span class="k">'+DATA.inboxTotal+'</span></div>'+
        '<div class="saved">Inbox Scout hid <b>'+HIDDEN_JUNK+'</b> code &amp; security email(s) before you saw them. That is <b>'+HIDDEN_JUNK+'</b> decisions you did not have to make.</div>'+
      '</div>';
  }

  function renderList(kindWrap,list,emptyMsg){
    var el=$(kindWrap);
    if(!list.length){el.innerHTML='<div class="empty"><div class="big">&#127811;</div><h3>'+emptyMsg+'</h3></div>';return;}
    el.innerHTML='<div class="items" style="margin-top:14px">'+list.map(itemHTML).join('')+'</div>';
  }

  function renderFocus(){
    var items=active().slice().sort(function(a,b){return b.imp-a.imp;});
    var wrap=$("#focusWrap");
    if(!items.length){wrap.innerHTML='<div class="focusdone"><div class="big">&#127881;</div>'+
      '<h2 style="margin:14px 0 6px">Inbox handled.</h2><p style="color:var(--soft)">You made every decision that mattered. Go build something.</p>'+
      '<div class="factions"><button class="fbtn primary" data-view="today">Back to Today</button></div></div>';return;}
    if(state.focusIdx>=items.length)state.focusIdx=0;
    var it=items[state.focusIdx],k=KIND[it.kind]||KIND.info;
    var whyList=(it.why||[]).filter(Boolean).map(function(w){return '<li>'+esc(w)+'</li>';}).join('');
    wrap.innerHTML='<div class="focuscard">'+
      '<div class="prog mono">'+String(state.focusIdx+1).padStart(2,"0")+' / '+String(items.length).padStart(2,"0")+'</div>'+
      '<div><span class="chip" style="background:'+k.dim+';color:'+k.color+'">'+k.label+'</span></div>'+
      '<h2>'+esc(it.title)+'</h2>'+
      '<div class="fmeta">'+esc(it.sender)+(it.due?' &middot; <span style="color:var(--amber)">'+esc(it.due)+'</span>':'')+'</div>'+
      '<div class="fwhy"><b style="font-size:.7rem;font-family:var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--soft)">Why this is here</b><ul>'+whyList+'</ul></div>'+
      '<div class="factions">'+
        '<button class="fbtn primary" data-fact="done">'+IC.done+' '+(it.source==="task"?"Done":"Clear")+' <kbd>D</kbd></button>'+
        '<button class="fbtn" data-fact="later">Later <kbd>L</kbd></button>'+
        '<button class="fbtn" data-fact="skip">Skip <kbd>&rarr;</kbd></button>'+
      '</div>'+
      '<div style="margin-top:16px"><button class="whybtn" data-view="today">Leave focus</button></div>'+
    '</div>';
  }

  function setView(v){
    state.view=v;
    ["today","focus","later","done"].forEach(function(n){$("#v-"+n).hidden=(n!==v);});
    document.querySelectorAll('[data-view]').forEach(function(b){
      if(b.classList.contains("navitem")||b.classList.contains("tab")||b.classList.contains("bn"))
        b.setAttribute("aria-current",b.getAttribute("data-view")===v?"true":"false");});
    if(v==="today"){renderBrief();renderRail();renderQueue();renderContext();}
    else if(v==="focus"){state.focusIdx=0;renderFocus();}
    else if(v==="later"){renderList("#laterList",laterItems(),"Nothing set aside. A calm Later is a good sign.");}
    else if(v==="done"){var d=doneItems();$("#doneStatus").textContent=d.length+" cleared this session. Task completions apply through TaskFlow on the next sync.";
      renderList("#doneList",d,"Nothing cleared yet.");}
    window.scrollTo(0,0);
  }

  var undoFn=null,toastT=null;
  function toast(msg){var t=$("#toast");
    t.innerHTML=esc(msg)+(undoFn?' <button id="undoBtn">Undo</button> <span class="u">Z</span>':'');
    t.classList.add("show");clearTimeout(toastT);toastT=setTimeout(function(){t.classList.remove("show");undoFn=null;},4200);
    var u=$("#undoBtn");if(u)u.onclick=doUndo;}
  function doUndo(){if(undoFn){undoFn();undoFn=null;$("#toast").classList.remove("show");refresh();}}
  function leave(id,cb){var el=document.querySelector('.item[data-id="'+id+'"]');
    if(el){el.classList.add("leaving");setTimeout(cb,180);}else cb();}
  function doAction(id,act){
    var it=byId(id);if(!it)return;
    if(it.source==="task"){
      if(act==="done"||act==="later"){
        var real=(act==="later")?"snooze":"done";
        postAction(it.tid,real);
        leave(id,function(){state.done[id]=1;persist();undoFn=null;
          toast(real==="done"?"Done ✓ applies to TaskFlow on next sync":"Snoozed to tomorrow ⏰");refresh();});
      } else if(act==="cal"){ if(it.cal) window.open(it.cal,"_blank"); }
      return;
    }
    if(act==="open"){ if(it.href) window.open(it.href,"_blank","noopener"); return; }
    if(act==="cal"){ if(it.cal) window.open(it.cal,"_blank","noopener"); else toast("No date on this one."); return; }
    if(act==="later"){ leave(id,function(){state.later[id]=1;persist();
      undoFn=function(){delete state.later[id];persist();};toast("Set aside for Later.");refresh();}); return; }
    if(act==="done"){ leave(id,function(){state.done[id]=1;persist();
      undoFn=function(){delete state.done[id];persist();};toast("Cleared from your view.");refresh();}); return; }
  }
  function refresh(){if(state.view==="today"){renderBrief();renderRail();renderQueue();renderContext();}
    else if(state.view==="focus")renderFocus();
    else if(state.view==="later")renderList("#laterList",laterItems(),"Nothing set aside.");
    else if(state.view==="done"){var d=doneItems();renderList("#doneList",d,"Nothing cleared yet.");}}

  function setFilter(k){state.filter=k;renderRail();renderQueue();}
  function clearLow(){
    var lows=active().filter(function(i){return i.kind==="info";});
    if(!lows.length){toast("No low-priority items to clear.");return;}
    var ids=lows.map(function(i){return i.id;});
    ids.forEach(function(id){state.later[id]=1;});persist();
    undoFn=function(){ids.forEach(function(id){delete state.later[id];});persist();};
    toast("Set "+ids.length+" low-priority aside.");refresh();}

  function doFocus(f){var items=active().slice().sort(function(a,b){return b.imp-a.imp;});var cur=items[state.focusIdx];
    if(!cur)return;
    if(f==="done"){ if(cur.source==="task")postAction(cur.tid,"done"); state.done[cur.id]=1;persist();
      toast(cur.source==="task"?"Done ✓ applies on next sync":"Cleared."); }
    else if(f==="later"){ if(cur.source==="task")postAction(cur.tid,"snooze"); state.later[cur.id]=1;persist(); }
    else if(f==="skip"){state.focusIdx++;}
    renderFocus();}

  document.addEventListener("click",function(e){
    var t=e.target.closest("[data-view]");if(t){setView(t.getAttribute("data-view"));return;}
    var act=e.target.closest("[data-act]");if(act){
      var a=act.getAttribute("data-act");
      if(a==="focusfirst"){setView("focus");return;}
      if(a==="clearlow"){clearLow();return;}
      doAction(+act.getAttribute("data-id"),a);return;}
    var why=e.target.closest("[data-why]");if(why){var id=+why.getAttribute("data-why");
      state.expanded[id]=!state.expanded[id];renderQueue();return;}
    var more=e.target.closest("[data-more]");if(more){var box=document.querySelector('[data-morebox="'+more.getAttribute("data-more")+'"]');
      if(box){box.hidden=false;more.remove();}return;}
    var tog=e.target.closest("[data-toggle]");if(tog){var g=tog.getAttribute("data-toggle");
      state.collapsed[g]=!state.collapsed[g];tog.closest(".group").classList.toggle("collapsed");return;}
    var filt=e.target.closest("[data-filter]");if(filt){var fv=filt.getAttribute("data-filter");
      setFilter(fv==="all"?null:fv);return;}
    var fact=e.target.closest("[data-fact]");if(fact){doFocus(fact.getAttribute("data-fact"));if(state.view==="today")refresh();return;}
    if(e.target.closest("#cmdBtn")){openPalette();}
  });

  var PACTIONS=[
    {t:"Go to Today",k:"T",run:function(){setView("today");}},
    {t:"Start Focus mode",k:"F",run:function(){setView("focus");}},
    {t:"Go to Later",k:"L",run:function(){setView("later");}},
    {t:"Go to Done",k:"",run:function(){setView("done");}},
    {t:"Clear low-priority",k:"",run:function(){setView("today");clearLow();}},
    {t:"Filter: Needs action",k:"",run:function(){setView("today");setFilter("action");}},
    {t:"Filter: Opportunities",k:"",run:function(){setView("today");setFilter("opportunity");}},
    {t:"Filter: Deadlines",k:"",run:function(){setView("today");setFilter("deadline");}},
    {t:"Clear filter, show all",k:"",run:function(){setView("today");setFilter(null);}}
  ];
  var palSel=0,palScrim=null;
  function openPalette(){
    palSel=0;palScrim=document.createElement("div");palScrim.className="scrim";
    palScrim.innerHTML='<div class="palette" role="dialog" aria-label="Command menu">'+
      '<input type="text" placeholder="What do you want to do?" id="palIn" autocomplete="off">'+
      '<div class="plist" id="palList"></div></div>';
    document.body.appendChild(palScrim);
    palScrim.addEventListener("click",function(e){if(e.target===palScrim)closePalette();});
    var inp=$("#palIn");inp.addEventListener("input",drawPal);
    inp.addEventListener("keydown",palKeys);drawPal();inp.focus();
  }
  function closePalette(){if(palScrim){palScrim.remove();palScrim=null;}}
  function palResults(){
    var q=($("#palIn")?$("#palIn").value:"").toLowerCase().trim();
    var acts=PACTIONS.filter(function(a){return !q||a.t.toLowerCase().indexOf(q)>=0;})
      .map(function(a){return {label:a.t,k:a.k,dot:"",run:a.run};});
    var its=[];
    if(q){its=active().filter(function(i){return (i.title+" "+i.sender).toLowerCase().indexOf(q)>=0;})
      .slice(0,6).map(function(i){return {label:i.title,k:i.sender,dot:(KIND[i.kind]||KIND.info).color,
        run:function(){setView("today");setFilter(i.kind);}};});}
    return acts.concat(its);
  }
  function drawPal(){var list=palResults();if(palSel>=list.length)palSel=0;
    $("#palList").innerHTML=list.map(function(a,i){
      var ic=a.dot?'<span class="pi" style="width:8px;height:8px;border-radius:50%;background:'+a.dot+'"></span>':'<span class="pi">'+IC.open+'</span>';
      return '<div class="prow" aria-selected="'+(i===palSel)+'" data-pi="'+i+'">'+ic+esc(a.label)+
        (a.k?'<span class="pk">'+esc(a.k)+'</span>':'')+'</div>';}).join('')||
      '<div class="prow" style="color:var(--faint)">No matches</div>';
    Array.prototype.forEach.call($("#palList").children,function(r){r.onclick=function(){
      var i=+r.getAttribute("data-pi");var a=palResults()[i];if(a){closePalette();a.run();}};});}
  function palKeys(e){var list=palResults();
    if(e.key==="ArrowDown"){e.preventDefault();palSel=(palSel+1)%list.length;drawPal();}
    else if(e.key==="ArrowUp"){e.preventDefault();palSel=(palSel-1+list.length)%list.length;drawPal();}
    else if(e.key==="Enter"){e.preventDefault();var a=list[palSel];if(a){closePalette();a.run();}}
    else if(e.key==="Escape"){closePalette();}}

  document.addEventListener("keydown",function(e){
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k"){e.preventDefault();palScrim?closePalette():openPalette();return;}
    if(palScrim)return;
    if(e.target.tagName==="INPUT")return;
    var key=e.key.toLowerCase();
    if(key==="z"&&undoFn){doUndo();return;}
    if(state.view==="focus"){
      if(key==="d"){doFocus("done");}else if(key==="l"){doFocus("later");}
      else if(e.key==="ArrowRight"||key==="j"){doFocus("skip");}
      else if(key==="escape"){setView("today");}
      return;}
    if(key==="t")setView("today");else if(key==="f")setView("focus");
    else if(key==="l")setView("later");else if(key==="?"){openPalette();}
  });

  $("#dateStr").textContent=new Date().toLocaleDateString(undefined,{weekday:"short",month:"short",day:"numeric"});
  setView("today");
})();
"""


def render_html(summary: dict) -> str:
    data = _build_data(summary)
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    js = _JS.replace("__DATA__", data_json)
    title = html.escape(str(summary.get("window", "today")))
    return ("<!doctype html>\n<html lang=\"en\"><head>\n"
            "<meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>My Inbox — {title}</title>\n"
            "<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">\n"
            "<link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>\n"
            "<link rel=\"stylesheet\" href=\"https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap\">\n"
            "<style>" + _CSS + "</style></head><body>\n"
            + _BODY
            + "<script>" + js + "</script>\n</body></html>")
