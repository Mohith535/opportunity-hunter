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


def _notify(new_items, test):
    """Send one digest desktop + phone notification summarizing the run.

    The body lists a per-source breakdown (so you can see which sources fired)
    plus the top few items by score.
    """
    if not new_items:
        return
    from collections import Counter

    counts = Counter(it.source for it in new_items)
    src_line = " | ".join(f"{src}: {n}" for src, n in counts.most_common())
    top = sorted(new_items, key=policy.effective_score, reverse=True)[:3]
    top_lines = "\n".join(
        f"[{policy.effective_score(it)}] {it.source}: {it.title[:55]}" for it in top
    )

    title = f"🎯 {len(new_items)} new opportunities"
    message = f"{src_line}\n\n{top_lines}"

    send_desktop("Opportunity Hunter", f"{len(new_items)} new — {src_line}")
    if not test:  # --test suppresses the phone push
        levels = {policy.decide(it).level for it in new_items}
        prio = "urgent" if "CRITICAL" in levels else "high" if "HIGH" in levels else "default"
        send_phone(title, message, priority=prio)


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
