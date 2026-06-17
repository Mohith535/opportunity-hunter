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
import time
from datetime import date, datetime

import daily_brief
import store
import config
from filters import policy
from filters.relevance import is_relevant
from filters.scorer import score_item
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


def _clip(text: str, n: int = 24) -> str:
    text = " ".join(text.split())  # collapse whitespace
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _md_link(it) -> str:
    """A Markdown bullet with a clickable link + deadline, safe for ntfy markdown."""
    text = _clip(it.title.replace("[", "(").replace("]", ")"), 46)
    url = it.url.replace("(", "%28").replace(")", "%29")
    dl = _deadline_phrase(it)
    suffix = f" — {dl}" if dl else ""
    return f"- [{text}]({url}){suffix}"


def _format_digest(new_items) -> str:
    """Markdown digest: bold headers, bulleted clickable links, soonest-first.

    Three tiers matching the notification's intent — CRITICAL (9-10),
    HIGH (7-8), and Learning (everything below, e.g. papers/repos/minor items).
    """
    from datetime import date as _date

    buckets = {"CRITICAL": [], "HIGH": [], "LEARNING": []}
    for it in new_items:
        lvl = policy.classify(policy.effective_score(it))
        key = lvl if lvl in ("CRITICAL", "HIGH") else "LEARNING"
        buckets[key].append(it)
    for b in buckets.values():
        b.sort(key=lambda it: (it.deadline or _date.max, -policy.effective_score(it)))

    parts = [f"🌅 **{len(new_items)} new opportunities**", ""]
    sections = [
        ("CRITICAL", "🔥 **CRITICAL**", 5),
        ("HIGH", "⚡ **HIGH**", 5),
        ("LEARNING", "📚 **Learning**", 6),
    ]
    for key, header, cap in sections:
        bucket = buckets[key]
        if not bucket:
            continue
        parts.append(header)
        parts.extend(_md_link(it) for it in bucket[:cap])
        if len(bucket) > cap:
            parts.append(f"_…and {len(bucket) - cap} more_")
        parts.append("")  # blank line between sections

    return "\n".join(parts).strip()


def _actions_header(new_items) -> str:
    """ntfy 'Actions' header: a tap-to-open 'view' button for the top 3 items.

    Must be ASCII (HTTP headers are latin-1) and free of the ',' / ';' that
    delimit the short action format, so labels are sanitized.
    """
    actions = []
    for it in sorted(new_items, key=policy.effective_score, reverse=True)[:3]:
        if not it.url:
            continue
        label = it.title.encode("ascii", "ignore").decode()
        for ch in (",", ";", '"', "'"):
            label = label.replace(ch, " ")
        label = " ".join(label.split())[:22] or it.source
        actions.append(f"view, {label}, {it.url}, clear=true")
    return "; ".join(actions)


def _notify(new_items, test):
    """Send one Markdown digest (clickable links + action buttons) to phone + desktop."""
    if not new_items:
        return

    levels = {policy.decide(it).level for it in new_items}
    body = _format_digest(new_items)
    title = f"{len(new_items)} new opportunities"

    # Keep existing priority logic; emoji conveyed via ntfy tags.
    if "CRITICAL" in levels:
        prio, tags = "urgent", "fire"
    elif "HIGH" in levels:
        prio, tags = "high", "zap"
    else:
        prio, tags = "default", "dart"

    top = max(new_items, key=policy.effective_score)   # tapping body opens this
    actions = _actions_header(new_items)               # top-3 buttons

    from collections import Counter
    src_line = " · ".join(f"{s} {n}" for s, n in Counter(it.source for it in new_items).most_common())
    send_desktop("Opportunity Hunter", f"{len(new_items)} new — {src_line}")
    if not test:  # --test suppresses the phone push
        send_phone(title, body, priority=prio, tags=tags,
                   click=top.url, actions=actions, markdown=True)


def run(source_names=None, test=False):
    """Execute one full hunt."""
    mode = "TEST (dry run)" if test else "LIVE"
    log(f"=== Opportunity Hunter run started [{mode}] ===")

    # 1. Gather
    all_items, sources_ok, sources_total = _gather(source_names)

    # 2. Relevance filter
    relevant = [it for it in all_items if is_relevant(it)]

    # 3. Score
    for it in relevant:
        it.score = score_item(it)

    # 4. Dedup (skip already-seen unless it qualifies to resurface)
    seen = store.load_seen()
    new_items = [
        it for it in relevant
        if not store.is_seen(seen, it) or store.should_resurface(it)
    ]

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
