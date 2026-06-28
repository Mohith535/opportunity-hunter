"""
Opportunity Hunter — entry point, pipeline orchestrator, and scheduler.

Pipeline:  sources -> relevance filter -> score -> dedup -> policy
           -> (notify + TaskFlow dump) -> daily brief -> history

CLI:
    python main.py --now                      run once, full side effects
    python main.py --test                     dry run: no dumps, no phone push
    python main.py --now --sources arxiv       run only the named sources
    python main.py --recap                    re-print the last run's brief
    python main.py                            start the daily scheduler (08:00)
"""

import argparse
import html
import textwrap
import time
from datetime import date, datetime

import daily_brief
import store
import config
from filters import policy
from filters.relevance import is_relevant
from filters.scorer import score_item
from notifiers import telegram
from notifiers.desktop import send_desktop
from notifiers.ntfy import send_phone
from sources import available_sources, get_sources
from taskflow import integration
from util import log, safe_fetch


def _gather(source_names):
    """Fetch from each enabled source, counting how many succeeded."""
    sources = get_sources(source_names)
    items, ok = [], 0
    for name, fetch_fn in sources.items():
        results = safe_fetch(name, fetch_fn)
        if results:
            ok += 1
        items.extend(results)
    return items, ok, len(sources)


def _deadline_phrase(item) -> str:
    """Human deadline countdown, e.g. 'today', 'tomorrow', '5 days left', '12 Jul'."""
    if not item.deadline:
        return ""
    days = (item.deadline - date.today()).days
    if days < 0:
        return "closed"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days <= 14:
        return f"{days} days left"
    return item.deadline.strftime("%d %b")


# Category emoji per source — tells you the TYPE of opportunity at a glance,
# independent of the score tier (the closest thing to colour a push allows).
_CATEGORY_EMOJI = {
    "devpost": "🏆", "devfolio": "🏆", "mlh": "🏆",   # 🏆 Hackathon
    "unstop": "💼",                                    # 💼 Student program / fellowship
    "programs": "🎓",                                  # 🎓 Flagship program (curated)
    "clist": "💻",                                     # 💻 Coding contest
    "arxiv": "📄",                                     # 📄 Research paper
    "github": "🔧",                                    # 🔧 Trending repo
    "reddit": "💬", "hackernews": "💬",                # 💬 Discussion
}


def _cat_emoji(source: str) -> str:
    return _CATEGORY_EMOJI.get(source, "📌")


def _md_link(it, no_deadline: str = "rolling") -> str:
    """A Markdown line: category emoji + clickable link + deadline suffix.

    Titles are shortened at a word boundary (textwrap.shorten), never mid-word.
    Items without a parsed deadline get the `no_deadline` fallback so every line
    has a consistent suffix.
    """
    text = textwrap.shorten(it.title, width=42, placeholder="…")
    text = text.replace("[", "(").replace("]", ")")        # keep link text valid
    url = it.url.replace("(", "%28").replace(")", "%29")
    suffix = _deadline_phrase(it) or no_deadline
    return f"{_cat_emoji(it.source)} [{text}]({url}) — {suffix}"


def _by_deadline(items):
    from datetime import date as _date
    return sorted(items, key=lambda it: (it.deadline or _date.max,
                                          -policy.effective_score(it)))


def _item_block(it, with_plan: bool) -> str:
    """One push block: the clickable link, the LLM 'why it matters' line, and —
    for the elite items — the suggested mini action plan as a numbered list."""
    parts = [_md_link(it)]
    if it.ai_summary:
        parts.append(f"_{it.ai_summary}_")                      # why it matters
    if with_plan and it.action_plan:
        parts.append("  \n".join(f"{n}. {step}"
                                 for n, step in enumerate(it.action_plan, 1)))
    return "  \n".join(parts)


def _format_main(critical, high, cap=6) -> str:
    """Main-push body: CRITICAL + HIGH only, max `cap` combined, soonest first.

    Each item shows its 'why it matters' line; CRITICAL items also show their
    action plan. Tiers are separated by blank lines for CommonMark spacing."""
    pool = _by_deadline(critical + high)
    selected = pool[:cap]
    crit = [i for i in selected if policy.classify(policy.effective_score(i)) == "CRITICAL"]
    hi = [i for i in selected if policy.classify(policy.effective_score(i)) == "HIGH"]

    blocks = []
    if crit:
        body = "\n\n".join(_item_block(i, with_plan=True) for i in crit)
        blocks.append("🔥 **CRITICAL**\n\n" + body)
    if hi:
        body = "\n\n".join(_item_block(i, with_plan=False) for i in hi)
        blocks.append("⚡ **HIGH**\n\n" + body)
    body = "\n\n".join(blocks)

    remaining = len(pool) - len(selected)
    if remaining > 0:
        body += f"\n\n_+{remaining} more — open Nova Scout_"
    return body.strip()


def _format_learning(items, cap=3) -> str:
    """Low-priority body: top `cap` medium/low items + a single count line."""
    ordered = _by_deadline(items)
    body = "  \n".join(_md_link(i, no_deadline=i.source) for i in ordered[:cap])
    rest = len(ordered) - cap
    if rest > 0:
        body += f"\n\n_+{rest} more research/contest items today_"
    return body.strip()


def _actions_header(items) -> str:
    """ntfy 'Actions' header: a tap-to-open 'view' button for the top 3 items.

    Must be ASCII (HTTP headers are latin-1) and free of the ',' / ';' that
    delimit the short action format, so labels are sanitized.
    """
    actions = []
    for it in sorted(items, key=policy.effective_score, reverse=True)[:3]:
        if not it.url:
            continue
        label = it.title.encode("ascii", "ignore").decode()
        for ch in (",", ";", '"', "'"):
            label = label.replace(ch, " ")
        label = " ".join(label.split())[:22] or it.source
        actions.append(f"view, {label}, {it.url}, clear=true")
    return "; ".join(actions)


def _tg_escape(s: str) -> str:
    return html.escape(s or "")


def _telegram_digest(crit, high, cap=6):
    """Build the Telegram message (HTML) + inline keyboard for the urgent set.
    Each item gets an 'Open' (link) and a 'Plan in TaskFlow' (callback) button;
    the callback carries the dedup_key so the listener can find and dump it."""
    pool = _by_deadline(crit + high)[:cap]
    parts, buttons = [], []

    def _block(label, items):
        if not items:
            return
        parts.append(label)
        for it in items:
            dl = _deadline_phrase(it) or "rolling"
            title = _tg_escape(textwrap.shorten(it.title, width=60, placeholder="…"))
            seg = f"{_cat_emoji(it.source)} <b>{title}</b> — {dl}"
            if it.ai_summary:
                seg += f"\n   <i>{_tg_escape(it.ai_summary)}</i>"
            parts.append(seg)
            key = it.dedup_key()
            row1 = []
            if it.url:
                row1.append({"text": "🔗 Open", "url": it.url})
            row1.append({"text": "➕ Plan", "callback_data": f"plan:{key}"})
            buttons.append(row1)
            # Application-tracker row: act on it and the agent remembers.
            buttons.append([
                {"text": "✅ Applied", "callback_data": f"applied:{key}"},
                {"text": "⏭ Skip", "callback_data": f"skip:{key}"},
                {"text": "⏰ Remind", "callback_data": f"remind:{key}"},
            ])

    _block("🔥 <b>CRITICAL</b>", [i for i in pool
                                  if policy.classify(policy.effective_score(i)) == "CRITICAL"])
    _block("⚡ <b>HIGH</b>", [i for i in pool
                             if policy.classify(policy.effective_score(i)) == "HIGH"])
    return "\n\n".join(parts), buttons


def _notify(new_items, test):
    """Send a focused main push (CRITICAL+HIGH) plus a separate low-priority
    learning push (medium/low), to phone + desktop + Telegram (two-way)."""
    if not new_items:
        return
    from collections import Counter

    def _lvl(it):
        return policy.classify(policy.effective_score(it))

    crit = [i for i in new_items if _lvl(i) == "CRITICAL"]
    high = [i for i in new_items if _lvl(i) == "HIGH"]
    medium = [i for i in new_items if _lvl(i) == "MEDIUM"]
    learning = [i for i in new_items if _lvl(i) in ("MEDIUM", "LOW")]

    # Title = short, useful stat line (NOT repeated in the body).
    stat = []
    if crit:
        stat.append(f"{len(crit)} Critical")
    if high:
        stat.append(f"{len(high)} High")
    if medium:
        stat.append(f"{len(medium)} worth a look")
    stat_line = " · ".join(stat) or f"{len(new_items)} new opportunities"

    src_line = " · ".join(f"{s} {n}" for s, n in Counter(it.source for it in new_items).most_common())
    send_desktop("Opportunity Hunter", f"{len(new_items)} new — {src_line}")
    if test:  # --test suppresses phone pushes
        return

    # 1) MAIN push — CRITICAL + HIGH only, with top-3 action buttons.
    if crit or high:
        prio, tags = ("urgent", "fire") if crit else ("high", "zap")
        top = max(crit + high, key=policy.effective_score)
        send_phone(stat_line, _format_main(crit, high),
                   priority=prio, tags=tags, click=top.url,
                   actions=_actions_header(crit + high), markdown=True)

    # 2) LEARNING push — medium/low, low priority, separate notification.
    if learning:
        send_phone(f"{len(learning)} more to explore", _format_learning(learning),
                   priority="low", tags="books", markdown=True)

    # 3) TELEGRAM (two-way) — the urgent set with tap-to-act buttons. Tapping
    # "Plan in TaskFlow" is handled by telegram_listener.py running locally.
    if telegram.is_configured() and (crit or high):
        text, buttons = _telegram_digest(crit, high)
        telegram.send_telegram(f"<b>{_tg_escape(stat_line)}</b>\n\n{text}", buttons=buttons)


def run(source_names=None, test=False):
    """Execute one full hunt."""
    mode = "TEST (dry run)" if test else "LIVE"
    log(f"=== Opportunity Hunter run started [{mode}] ===")

    # 1. Gather
    all_items, sources_ok, sources_total = _gather(source_names)

    # 2. Relevance filter. The curated "programs" watchlist is pre-vetted (every
    # entry was hand-picked as relevant), so it bypasses the keyword gate and goes
    # straight to the LLM scorer — which then ranks it. Noisy sources still pass
    # through the keyword filter as before.
    trusted = {"programs"}
    relevant = [it for it in all_items if it.source in trusted or is_relevant(it)]

    # 3. Score
    for it in relevant:
        it.score = score_item(it)

    # 4. Dedup (skip already-seen unless it qualifies to resurface)
    seen = store.load_seen()
    new_items = [
        it for it in relevant
        if not store.is_seen(seen, it) or store.should_resurface(it)
    ]

    # 4b. LLM scoring (Phase 2) — the "filter by Mohith" brain. Only the fresh,
    # deduped items are scored (quota-frugal); falls back to rule scores if the
    # LLM is unavailable. effective_score() then prefers ai_score automatically.
    if config.USE_LLM_SCORING and new_items:
        from filters import llm_scorer
        from user_profile import load_profile

        prof = load_profile()
        log(f"[profile] scoring against Mohith — layers: {', '.join(prof.sources)}")
        llm_scorer.score_items(new_items, prof)

    # 5. Policy -> side effects
    taskflow_ready = (not test) and integration.is_available()
    dumped_keys, dumps, high_priority = set(), 0, 0
    for it in new_items:
        decision = policy.decide(it)
        if decision.level in ("CRITICAL", "HIGH"):
            high_priority += 1
        if not test and decision.dump_to_taskflow and taskflow_ready:
            if integration.dump(it, policy.effective_score(it)):
                dumped_keys.add(it.dedup_key())
                dumps += 1
        store.mark_seen(seen, it)
    # A dry run must not persist state, or a later real run would treat
    # everything as already-seen and show nothing.
    if not test:
        store.save_seen(seen)
        if new_items:  # don't record empty runs (keeps --recap meaningful)
            store.append_history(new_items)

    # 6. Notify
    _notify(new_items, test)

    # 7. Brief
    stats = {
        "scanned": len(all_items),
        "relevant": len(relevant),
        "high_priority": high_priority,
        "dumps": dumps,
        "sources_ok": sources_ok,
        "sources_total": sources_total,
    }
    daily_brief.render(new_items, stats, dumped_keys)
    log(f"=== run finished: {len(all_items)} scanned, {len(relevant)} relevant, "
        f"{len(new_items)} new, {dumps} dumped ===")


def recap():
    """Re-render the most recent run from history.json."""
    from models import Opportunity

    data = store._load(config.HISTORY_FILE)
    runs = data.get("runs", [])
    if not runs:
        print("No history yet. Run `python main.py --now` first.")
        return
    last = runs[-1]
    items = []
    for d in last["items"]:
        dl = d.get("deadline")
        item = Opportunity(
            title=d["title"], url=d.get("url", ""), source=d.get("source", ""),
            description=d.get("description", ""), tags=d.get("tags", []),
            native_id=d.get("native_id"),
        )
        item.score = d.get("score", 0)
        item.ai_score = d.get("ai_score", -1)
        item.ai_summary = d.get("ai_summary", "")
        item.action_plan = d.get("action_plan", [])
        item.dimensions = d.get("dimensions", {})
        if dl:
            try:
                item.deadline = date.fromisoformat(dl)
            except ValueError:
                pass
        items.append(item)
    stats = {"scanned": len(items), "relevant": len(items),
             "high_priority": 0, "dumps": 0, "sources_ok": 0, "sources_total": 0}
    print(f"(recap of last run: {last['date']})\n")
    daily_brief.render(items, stats)


def scheduler():
    """Run once a day at config.DAILY_RUN_TIME (local time)."""
    log(f"Scheduler started — daily run at {config.DAILY_RUN_TIME}. Ctrl+C to stop.")
    last_run_date = None
    while True:
        now = datetime.now()
        if now.strftime("%H:%M") == config.DAILY_RUN_TIME and last_run_date != now.date():
            run()
            last_run_date = now.date()
        time.sleep(30)


def main():
    parser = argparse.ArgumentParser(description="Opportunity Hunter")
    parser.add_argument("--now", action="store_true", help="run once immediately")
    parser.add_argument("--test", action="store_true",
                        help="dry run: no TaskFlow dumps, no phone notifications")
    parser.add_argument("--recap", action="store_true", help="re-show last run's brief")
    parser.add_argument("--sources", type=str, default=None,
                        help=f"comma-separated subset of: {','.join(available_sources())}")
    args = parser.parse_args()

    source_names = [s.strip() for s in args.sources.split(",")] if args.sources else None

    if args.recap:
        recap()
    elif args.now or args.test:
        run(source_names=source_names, test=args.test)
    else:
        scheduler()


if __name__ == "__main__":
    main()
