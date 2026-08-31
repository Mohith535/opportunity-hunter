"""
Turn the scan into a calm, premium "Attention OS" dashboard you open on your phone.

Design language: a single self-contained page (all data embedded) in a dark, semantic theme (Hanken
Grotesk + IBM Plex Mono). One brief at the top (a greeting + the one thing to do first), then the
time-sensitive plan (your TaskFlow tasks, email deadlines, and closing opportunities woven together),
then the inbox itself with quick filters. On desktop it opens into a two-column command center; on the
phone it is a clean single column.

Honesty stays intact: it only READS your mail. Task rows carry ✓ done / ⏰ snooze (applied through
TaskFlow's own CLI on the next sync); email rows carry Open + Add-to-Calendar only, because Gmail
access is read-only and we never fake an action we cannot truthfully take.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from datetime import datetime, timedelta

# email category -> (semantic kind for colour/filtering, human label)
_KIND = {
    "ACTION": ("action", "To do"), "REPLY": ("action", "Reply"),
    "DEADLINE": ("deadline", "Deadline"), "OPPORTUNITY": ("opp", "Opportunity"),
    "PERSONAL": ("personal", "Personal"), "INFO": ("info", "Info"),
}
_KIND_LABEL = {"action": "Needs action", "deadline": "Deadlines", "opp": "Opportunities",
               "personal": "Personal", "info": "Info"}
_KIND_ORDER = ["action", "deadline", "opp", "personal", "info"]

# The tap-to-act script (kept OUT of the f-string template so its { } don't need escaping). Each ✓/⏰
# tap POSTs {id, act} to the worker's /action route (relative to this page's own secret path), hides
# the row optimistically, and remembers it in localStorage so a reload stays consistent until the page
# republishes without that task. On a local file (no worker) the POST just fails and the row comes back.
_ACTION_JS = """<script>
(function(){
  var base = location.pathname.replace(/\\/?$/, '/');   // -> /<secret>/
  var KEY = 'inbox_acted';
  function load(){ try{ return JSON.parse(localStorage.getItem(KEY)||'{}'); }catch(e){ return {}; } }
  function save(m){ try{ localStorage.setItem(KEY, JSON.stringify(m)); }catch(e){} }
  var acted = load(), seen = {};
  document.querySelectorAll('.act').forEach(function(b){
    seen[b.dataset.id] = 1;
    if(acted[b.dataset.id]){ var r = b.closest('.task'); if(r) r.style.display='none'; }
  });
  var changed = false;
  Object.keys(acted).forEach(function(k){ if(!seen[k]){ delete acted[k]; changed = true; } });
  if(changed) save(acted);
  var toast;
  function showToast(msg){
    if(!toast){ toast = document.createElement('div'); toast.className='toast'; document.body.appendChild(toast); }
    toast.textContent = msg; toast.classList.add('show');
    clearTimeout(toast._t); toast._t = setTimeout(function(){ toast.classList.remove('show'); }, 2600);
  }
  document.addEventListener('click', function(e){
    var btn = e.target.closest('.act'); if(!btn) return;
    var row = btn.closest('.task'); if(!row || row.classList.contains('acting')) return;
    var id = btn.dataset.id, act = btn.dataset.act;
    row.classList.add('acting');
    fetch(base + 'action', { method:'POST', headers:{'content-type':'application/json'},
      body: JSON.stringify({ id:id, act:act }) })
      .then(function(r){ if(!r.ok) throw new Error(r.status); return r; })
      .then(function(){
        acted[id] = act; save(acted);
        row.classList.add('gone');
        setTimeout(function(){ row.style.display='none'; }, 260);
        showToast(act === 'done' ? 'Done \\u2713 applies on next sync' : 'Snoozed to tomorrow \\u23f0');
      })
      .catch(function(){
        row.classList.remove('acting');
        showToast('Couldn\\'t reach your computer \\u2014 try again');
      });
  });
})();
</script>"""

# Inbox filter pills: hide/show queue items by kind. Pure view state, no network, nothing sent.
_FILTER_JS = """<script>
(function(){
  var pills = document.querySelectorAll('.fpill');
  var items = document.querySelectorAll('.qitem');
  if(!pills.length) return;
  function apply(k){
    pills.forEach(function(p){ p.setAttribute('aria-current', p.dataset.k===k ? 'true':'false'); });
    items.forEach(function(it){ it.hidden = (k!=='all' && it.dataset.kind!==k); });
  }
  pills.forEach(function(p){ p.addEventListener('click', function(){ apply(p.dataset.k); }); });
})();
</script>"""

_CSS = """
  :root{
    --bg:#0F120D; --surface:#161A12; --panel-2:#1B2016; --raise:#20261A;
    --ink:#ECEFE6; --ink-2:#B8C0AE; --soft:#8A9382; --faint:#5E6656;
    --line:#262C1D; --line-2:#323A28;
    --accent:#63C594; --accent-soft:#1E2C22; --accent-ink:#0F120D;
    --gold:#E3A83C; --gold-soft:#2A2213; --hi:#EF7350; --blue:#6FA8DE;
    --sh:0 1px 2px rgba(0,0,0,.4),0 10px 30px rgba(0,0,0,.3);
    --sans:"Hanken Grotesk",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
    font-size:15.5px;line-height:1.5;-webkit-font-smoothing:antialiased;
    background-image:radial-gradient(1100px 520px at 82% -8%, #171C12 0%, transparent 60%);
    background-attachment:fixed}
  h1,h2,h3{margin:0;font-weight:700;letter-spacing:-.01em}
  a{color:var(--accent)}
  .mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
  :focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:8px}

  .wrap{max-width:1200px;margin:0 auto;padding:26px clamp(16px,3vw,40px) 84px}
  @media(min-width:980px){
    .wrap{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:30px;align-items:start}
    .context{position:sticky;top:26px}
  }
  .main{min-width:0;display:flex;flex-direction:column;gap:22px}
  .context{display:flex;flex-direction:column;gap:16px}

  /* brief */
  .brief{background:linear-gradient(160deg,var(--panel-2),var(--surface));border:1px solid var(--line-2);
    border-radius:20px;padding:22px 22px;box-shadow:var(--sh)}
  .brief .hi{font-size:1.55rem;font-weight:800;letter-spacing:-.02em}
  .brief .status{color:var(--ink-2);margin-top:3px;font-size:.96rem}
  .brief .status b{color:var(--ink);font-weight:700}
  .first{display:flex;align-items:center;gap:12px;margin-top:17px;padding:14px 15px;
    background:var(--accent-soft);border:1px solid #244A38;border-radius:13px}
  .first .lbl{font-family:var(--mono);font-size:.6rem;letter-spacing:.15em;text-transform:uppercase;
    color:var(--accent);font-weight:600}
  .first .txt{font-weight:700;color:var(--ink);margin-top:3px;line-height:1.34}
  .briefline{display:flex;gap:18px;flex-wrap:wrap;margin-top:16px;padding-top:15px;
    border-top:1px solid var(--line)}
  .briefline .b .k{font-family:var(--mono);font-size:1.2rem;font-weight:600;color:var(--ink);display:block}
  .briefline .b .v{font-size:.74rem;color:var(--soft)}

  /* day plan (classes reused by _render_day) */
  .day{margin:0}
  .day-head{display:flex;align-items:center;gap:10px;margin:2px 2px 12px}
  .day-head h2{font-size:1.14rem;letter-spacing:-.01em}
  .pill{background:var(--accent-soft);color:var(--accent);font-weight:700;font-size:.8rem;
    padding:5px 12px;border-radius:999px}
  .pill.soft{background:var(--line-2);color:var(--soft)}
  .lead{background:var(--accent-soft);color:var(--accent);font-weight:800;font-size:1rem;line-height:1.4;
    padding:13px 15px;border-radius:13px;margin:0 0 14px}
  .task{display:flex;align-items:center;gap:10px;background:var(--surface);border:1px solid var(--line);
    border-left:3px solid var(--line-2);border-radius:13px;padding:11px 13px;margin-bottom:8px;
    box-shadow:var(--sh)}
  .task .tbody{flex:1;min-width:0}
  .rowacts{display:flex;gap:6px;flex-shrink:0}
  .act{width:40px;height:40px;border-radius:11px;border:1px solid transparent;background:transparent;
    color:var(--faint);font-size:1.02rem;cursor:pointer;padding:0;line-height:1;display:flex;
    align-items:center;justify-content:center;-webkit-tap-highlight-color:transparent;transition:all .13s}
  .act:active{transform:scale(.88)}
  .act.done:hover{background:var(--accent-soft);color:var(--accent)}
  .act.snooze:hover{background:var(--gold-soft);color:var(--gold)}
  .task.acting{opacity:.45}
  .task.gone{opacity:0;transform:translateX(10px);transition:opacity .25s ease,transform .25s ease}
  @media(prefers-reduced-motion:reduce){.act,.task.gone{transition:none}}
  .task.crit{border-left-color:var(--hi)} .task.strat{border-left-color:var(--gold)}
  .task.mail{border-left-color:var(--accent)} .task.opp{border-left-color:var(--gold)}
  .task .t{font-weight:600;font-size:.96rem;line-height:1.32;color:var(--ink);text-decoration:none;display:block}
  a.t:active{opacity:.7}
  .meta{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin-top:4px}
  .late{color:var(--hi);font-weight:700;font-size:.75rem;font-variant-numeric:tabular-nums}
  .today-tag{color:var(--gold);font-weight:700;font-size:.75rem}
  .soon{color:var(--accent);font-weight:700;font-size:.75rem}
  .src{color:var(--soft);font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em}
  .src.opp{color:var(--gold)}
  .ptag{color:var(--soft);font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em}
  .tier-lbl{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;
    color:var(--soft);margin:14px 2px 8px;font-family:var(--mono)}
  .tier-lbl.over{color:var(--hi)} .tier-lbl.today{color:var(--gold)} .tier-lbl.opp{color:var(--gold)}
  .day-note{color:var(--soft);font-size:.84rem;margin:9px 2px 0}
  .day-note.calm{margin:2px 2px 8px}

  /* inbox */
  .sechead{display:flex;align-items:center;gap:10px;margin:0 2px 12px}
  .sechead h2{font-size:1.14rem}
  .sechead .cnt{font-family:var(--mono);font-size:.82rem;color:var(--soft)}
  .fpills{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:14px}
  .fpill{background:var(--surface);border:1px solid var(--line-2);color:var(--ink-2);font-weight:600;
    font-size:.8rem;padding:6px 12px;border-radius:999px;display:inline-flex;gap:6px;align-items:center;
    cursor:pointer;transition:all .13s}
  .fpill b{font-family:var(--mono);color:var(--soft)}
  .fpill:hover{border-color:var(--soft);color:var(--ink)}
  .fpill[aria-current="true"]{background:var(--accent-soft);border-color:#2c5540;color:var(--accent)}
  .fpill[aria-current="true"] b{color:var(--accent)}
  .qitem{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--line-2);
    border-radius:13px;padding:13px 15px;margin-bottom:9px;box-shadow:var(--sh)}
  .qitem.action{border-left-color:var(--hi)} .qitem.deadline{border-left-color:var(--gold)}
  .qitem.opp{border-left-color:var(--accent)} .qitem.personal{border-left-color:var(--blue)}
  .qitem.info{border-left-color:var(--line-2)}
  .qrow1{display:flex;align-items:center;gap:8px;margin-bottom:5px}
  .qchip{font-family:var(--mono);font-size:.6rem;letter-spacing:.1em;text-transform:uppercase;
    font-weight:600;padding:3px 8px;border-radius:6px;background:var(--panel-2);color:var(--ink-2)}
  .qchip.action{color:var(--hi)} .qchip.deadline{color:var(--gold)} .qchip.opp{color:var(--accent)}
  .qchip.personal{color:var(--blue)}
  .qimp{margin-left:auto;font-family:var(--mono);font-size:.74rem;color:var(--soft)}
  .qwho{font-weight:700;font-size:.9rem;color:var(--ink)}
  .qsubj{color:var(--ink-2);font-size:.9rem;margin:2px 0 2px}
  .qsum{color:var(--soft);font-size:.86rem}
  .qacts{margin-top:11px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
  .qbtn{text-decoration:none;font-weight:700;padding:7px 13px;border-radius:999px;font-size:.8rem;
    border:1px solid var(--line-2);color:var(--ink-2);-webkit-tap-highlight-color:transparent}
  .qbtn.open{background:var(--accent-soft);color:var(--accent);border-color:transparent}
  .qbtn.cal{background:var(--gold-soft);color:var(--gold);border-color:transparent}
  .qbtn:active{transform:scale(.97)}
  .qdue{font-size:.8rem;font-weight:700;color:var(--gold)}
  .empty{color:var(--soft);text-align:center;padding:34px 0}

  /* everything else */
  .more{margin:2px 0 4px;border:1px solid var(--line);border-radius:13px;background:var(--surface);
    box-shadow:var(--sh);overflow:hidden}
  .more>summary{cursor:pointer;padding:12px 15px;font-weight:700;font-size:.88rem;color:var(--soft);
    list-style:none;-webkit-tap-highlight-color:transparent}
  .more>summary::-webkit-details-marker{display:none}
  .more>summary::after{content:"\\25be";float:right;color:var(--soft)}
  .more[open]>summary::after{content:"\\25b4"}
  .mrow{display:block;padding:11px 15px;border-top:1px solid var(--line);font-size:.88rem;
    color:var(--ink-2);text-decoration:none}
  .mrow:active{background:var(--panel-2)}
  .mwho{font-weight:700;color:var(--ink)}

  /* context: radar + health */
  .ctxcard{background:var(--surface);border:1px solid var(--line);border-radius:15px;padding:15px 16px;
    box-shadow:var(--sh)}
  .ctxcard h3{font-family:var(--mono);font-size:.66rem;letter-spacing:.13em;text-transform:uppercase;
    color:var(--soft);font-weight:600;margin-bottom:13px}
  .rrow{margin:11px 0}
  .rrow .rt{display:flex;justify-content:space-between;font-size:.82rem;color:var(--ink-2);margin-bottom:5px}
  .rrow .rt b{font-family:var(--mono);color:var(--ink)}
  .bar{height:6px;border-radius:99px;background:var(--raise);overflow:hidden}
  .bar i{display:block;height:100%;border-radius:99px}
  .hrow{display:flex;align-items:center;gap:9px;font-size:.86rem;color:var(--ink-2);margin:9px 0}
  .hrow .k{margin-left:auto;font-family:var(--mono);color:var(--ink)}
  .saved{margin-top:11px;padding-top:11px;border-top:1px solid var(--line);font-size:.8rem;color:var(--soft)}
  .saved b{color:var(--accent)}

  .toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:60;background:var(--raise);
    border:1px solid var(--line-2);color:var(--ink);font-size:.86rem;font-weight:600;padding:11px 16px;
    border-radius:999px;box-shadow:var(--sh);opacity:0;transition:opacity .2s ease;pointer-events:none;
    max-width:88vw;text-align:center}
  .toast.show{opacity:1}
  footer{color:var(--soft);font-size:.78rem;text-align:center;padding-top:8px;grid-column:1/-1}
"""


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


_IMPORTANT = 4  # importance 0-10: at/above this an email is a "worth your time" item; below → collapsed


def _greeting() -> str:
    h = datetime.now().hour
    return "Good morning" if h < 12 else "Good afternoon" if h < 17 else "Good evening"


def _late_label(days: int) -> str:
    return "1 day late" if days == 1 else f"{days} days late"


def _soon_label(days: int) -> str:
    return "tomorrow" if days == 1 else f"in {days} days"


def _parse_dl(s: str):
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _plan_row(title: str, stripe: str, when_html: str, badge_html: str = "", href: str = "",
              actions_html: str = "") -> str:
    """One line in the day plan. Task or email, same shape. `title` links to Gmail when href is given;
    `actions_html` (for TaskFlow tasks) adds the tap-to-act buttons on the right."""
    title = title[:140]
    t = (f'<a class="t" target="_blank" rel="noopener" href="{_e(href)}">{_e(title)}</a>'
         if href else f'<div class="t">{_e(title)}</div>')
    return f"""
      <div class="task {stripe}"><div class="tbody">{t}
        <div class="meta">{when_html}{badge_html}</div></div>{actions_html}</div>"""


def _task_actions(tid) -> str:
    """The ✓ done / ⏰ snooze buttons for a TaskFlow task row (acts via the phone→local bridge)."""
    if tid is None:
        return ""
    i = _e(tid)
    return (f'<div class="rowacts">'
            f'<button class="act done" data-id="{i}" data-act="done" aria-label="Mark done" '
            f'title="Mark done">✓</button>'
            f'<button class="act snooze" data-id="{i}" data-act="snooze" '
            f'aria-label="Snooze to tomorrow" title="Snooze to tomorrow">⏰</button></div>')


def _mail_link(gid: str) -> str:
    return f"https://mail.google.com/mail/u/0/#all/{gid}" if gid else ""


def _qitem(it: dict) -> str:
    """An inbox attention-queue item: semantic colour by category, sender, subject, one-line summary,
    and honest actions (Open in Gmail, and Add-to-Calendar when there's a deadline)."""
    kind, label = _KIND.get(it["category"], ("info", it["category"].title()))
    imp = it["importance"]
    dl = it.get("deadline") or ""
    href = _mail_link(it.get("id") or "")
    acts = []
    if href:
        acts.append(f'<a class="qbtn open" target="_blank" rel="noopener" href="{_e(href)}">Open email</a>')
    if dl:
        cal = gcal_link(it["subject"], dl)
        if cal:
            acts.append(f'<a class="qbtn cal" target="_blank" rel="noopener" href="{_e(cal)}">＋ Calendar</a>')
        acts.append(f'<span class="qdue">⏰ {_e(dl)}</span>')
    acts_html = f'<div class="qacts">{"".join(acts)}</div>' if acts else ""
    chip_cls = kind if kind != "info" else ""
    return f"""
      <article class="qitem {kind}" data-kind="{kind}">
        <div class="qrow1"><span class="qchip {chip_cls}">{_e(label)}</span>
          <span class="qimp" title="importance">{imp}/10</span></div>
        <div class="qwho">{_e(_sender_name(it["from"]))}</div>
        <div class="qsubj">{_e(it["subject"][:120])}</div>
        <div class="qsum">{_e(it["summary"])}</div>
        {acts_html}
      </article>"""


def _pills(important: list) -> str:
    present = []
    for it in important:
        k = _KIND.get(it["category"], ("info",))[0]
        if k not in present:
            present.append(k)
    p = f'<button class="fpill" data-k="all" aria-current="true">All <b>{len(important)}</b></button>'
    for k in _KIND_ORDER:
        if k in present:
            c = sum(1 for it in important if _KIND.get(it["category"], ("info",))[0] == k)
            p += f'<button class="fpill" data-k="{k}">{_KIND_LABEL[k]} <b>{c}</b></button>'
    return f'<div class="fpills">{p}</div>'


def _render_day(day: dict | None, emails: list | None, today, lead: str = "",
                opps: list | None = None) -> str:
    """The 'Today' plan: your TaskFlow tasks, your email deadlines, and OPHunter's closing
    opportunities woven into ONE agenda — Overdue → Today → Coming up → Opportunities closing. Read-only.
    '' when there's nothing to show. (`lead` is rendered in the brief now, so callers pass "".)"""
    day = day or {}
    emails = emails or []
    opps = opps or []
    overdue = day.get("overdue", [])
    due_tasks = day.get("due_today", [])
    up_tasks = day.get("upcoming", [])
    backlog = day.get("backlog_count", 0)

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
        return ""

    blocks = []
    shown_over = overdue[:12]
    if shown_over:
        rows = [_plan_row(t["title"], _priority_class(t["priority"]),
                          f'<span class="late">{_e(_late_label(t["days_over"]))}</span>',
                          f'<span class="ptag">{_e(t["priority"])}</span>' if t.get("priority") else "",
                          actions_html=_task_actions(t.get("id")))
                for t in shown_over]
        blocks.append(f'<div class="tier-lbl over">Overdue</div>{"".join(rows)}')

    today_rows = []
    for t in due_tasks:
        today_rows.append(_plan_row(
            t["title"], _priority_class(t["priority"]), '<span class="today-tag">due today</span>',
            f'<span class="ptag">{_e(t["priority"])}</span>' if t.get("priority") else "",
            actions_html=_task_actions(t.get("id"))))
    for m in mail_today:
        today_rows.append(_plan_row(m["title"], "mail", '<span class="today-tag">due today</span>',
                                    '<span class="src">✉ mail</span>', m["href"]))
    if today_rows:
        blocks.append(f'<div class="tier-lbl today">Today</div>{"".join(today_rows)}')

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
                    f'<span class="ptag">{_e(obj["priority"])}</span>' if obj.get("priority") else "",
                    actions_html=_task_actions(obj.get("id"))))
        blocks.append(f'<div class="tier-lbl">Coming up</div>{"".join(rows)}')

    if opps:
        opps = sorted(opps, key=lambda o: str(o.get("date") or "9999"))
        rows = []
        for o in opps[:8]:
            d = _parse_dl(o.get("date"))
            when = (f'<span class="soon">{_e(_soon_label((d - today).days))}</span>' if d else "")
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


def _render_brief(summary: dict, important: list, other: list, hidden_total: int) -> str:
    shown = summary.get("shown", [])
    day = summary.get("day") or {}
    opps = summary.get("opps") or []
    lead = summary.get("lead", "")
    today = datetime.now().date()

    def cat(c):
        return sum(1 for it in shown if it.get("category") == c)
    dated = len(day.get("overdue", [])) + len(day.get("due_today", [])) + \
        sum(1 for it in shown if it.get("deadline"))
    opp_n = cat("OPPORTUNITY")

    first = (f'<div class="first"><div><div class="lbl">Do this first</div>'
             f'<div class="txt">{_e(lead)}</div></div></div>' if lead else "")
    tiles = [(len(important), "worth your time"), (dated, "time-sensitive"),
             (opp_n, "opportunities"), (hidden_total, "junk hidden")]
    tile_html = "".join(f'<div class="b"><span class="k">{n}</span>'
                        f'<span class="v">{_e(v)}</span></div>' for n, v in tiles)
    total = len(important) + len(other)
    return f"""
    <section class="brief">
      <div class="hi">{_greeting()}, Mohith.</div>
      <div class="status"><b>{total}</b> in your inbox · {len(important)} worth your time ·
        {opp_n} opportunities · {hidden_total} junk hidden</div>
      {first}
      <div class="briefline">{tile_html}</div>
    </section>"""


def _render_context(summary: dict, important: list, hidden_total: int) -> str:
    shown = summary.get("shown", [])
    day = summary.get("day") or {}
    opps = summary.get("opps") or []

    def cat(c):
        return sum(1 for it in shown if it.get("category") == c)
    crit = sum(1 for it in shown if it.get("importance", 0) >= 8)
    deadlines = len(day.get("overdue", [])) + len(day.get("due_today", [])) + \
        len(day.get("upcoming", [])) + len(opps)
    waiting = cat("ACTION") + cat("REPLY")
    opp_n = cat("OPPORTUNITY") + len(opps)

    def bar(lab, val, mx, color):
        pct = min(100, round(val / mx * 100)) if mx else 0
        return (f'<div class="rrow"><div class="rt"><span>{_e(lab)}</span><b>{val}</b></div>'
                f'<div class="bar"><i style="width:{pct}%;background:{color}"></i></div></div>')

    radar = ('<div class="ctxcard"><h3>Attention radar</h3>'
             + bar("Critical", crit, 4, "var(--hi)")
             + bar("Deadlines ahead", deadlines, 6, "var(--gold)")
             + bar("Waiting on you", waiting, 5, "var(--blue)")
             + bar("Opportunities", opp_n, 6, "var(--accent)") + '</div>')
    health = (f'<div class="ctxcard"><h3>Inbox health</h3>'
              f'<div class="hrow">Worth your time <span class="k">{len(important)}</span></div>'
              f'<div class="hrow">In your inbox <span class="k">{len(shown)}</span></div>'
              f'<div class="saved">Inbox Scout hid <b>{hidden_total}</b> code &amp; security '
              f'email(s) before you saw them &mdash; <b>{hidden_total}</b> decisions you did not have '
              f'to make.</div></div>')
    return radar + health


def render_html(summary: dict) -> str:
    shown = summary.get("shown", [])
    hidden = summary.get("hidden", {})
    hidden_total = sum(hidden.values())
    today = datetime.now().date()

    important = sorted([it for it in shown if it.get("importance", 0) >= _IMPORTANT],
                       key=lambda x: -x.get("importance", 0))
    other = [it for it in shown if it.get("importance", 0) < _IMPORTANT]

    day_html = _render_day(summary.get("day"), shown, today, "", summary.get("opps"))
    brief_html = _render_brief(summary, important, other, hidden_total)
    context_html = _render_context(summary, important, hidden_total)

    if important:
        items = _pills(important) + "".join(_qitem(it) for it in important)
    else:
        msg = ("Nothing urgent right now — a quiet inbox is a good inbox. 🌿" if other
               else "Nothing important right now. A quiet inbox is a good inbox. 🌿")
        items = f'<p class="empty">{msg}</p>'

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

    inbox_html = (f'<section><div class="sechead"><h2>Inbox</h2>'
                  f'<span class="cnt">{len(important)} to review</span></div>{items}{more_html}</section>')

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>My Inbox — {_e(summary.get('window', 'today'))}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>{_CSS}</style></head><body>
<div class="wrap">
  <div class="main">
    {brief_html}
    {day_html}
    {inbox_html}
  </div>
  <aside class="context">
    {context_html}
  </aside>
  <footer>Reads your mail and your TaskFlow list · only one-time codes &amp; security are hidden ·
  the ✓ / ⏰ you tap are the only thing sent back, applied through TaskFlow on the next sync. 🌱</footer>
</div>
{_ACTION_JS}
{_FILTER_JS}
</body></html>"""
