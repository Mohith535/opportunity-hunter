"""
Daily brief — rich terminal output (CLAUDE.md §9).

Groups scored opportunities by level (CRITICAL/HIGH/MEDIUM/LEARNING) and prints
a stats footer. Pure presentation: takes already-scored items + a stats dict and
renders them. No fetching, no side effects.
"""

from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

import config
from filters import policy

console = Console()

_LEVEL_STYLE = {
    "CRITICAL": ("🔥 CRITICAL (9-10) — Act Today", "bold red"),
    "HIGH": ("⚡ HIGH (7-8) — Act This Week", "bold yellow"),
    "MEDIUM": ("📌 MEDIUM (5-6) — Review When Free", "bold cyan"),
}


def _deadline_str(item) -> str:
    if not item.deadline:
        return ""
    days = (item.deadline - datetime.now().date()).days
    if days < 0:
        return f"Deadline: {item.deadline} (passed)"
    return f"Deadline: {item.deadline} ({days}d left)"


def _render_item(item, dumped: bool) -> Text:
    score = policy.effective_score(item)
    t = Text()
    t.append(f"  [{score}/10] ", style="bold")
    t.append(f"{item.title}\n", style="bold white")
    meta = [item.source]
    dl = _deadline_str(item)
    if dl:
        meta.append(dl)
    if item.url:
        meta.append(item.url)
    t.append(f"          {'  |  '.join(meta)}\n", style="dim")
    if dumped:
        t.append("          → Added to TaskFlow ✓\n", style="green")
    return t


def render(items: list, stats: dict, dumped_keys: set | None = None) -> None:
    """Print the full daily brief.

    items: scored Opportunity objects (already deduped/filtered).
    stats: dict with keys scanned, relevant, high_priority, dumps, sources_ok, sources_total.
    dumped_keys: dedup_keys that were dumped to TaskFlow (for the ✓ marker).
    """
    dumped_keys = dumped_keys or set()
    now = datetime.now()

    header = Text(f"🌅  OPPORTUNITY HUNTER — DAILY BRIEF\n", style="bold")
    header.append(now.strftime("%A, %d %B %Y   |   %H:%M"), style="dim")
    console.print(Panel(header, expand=False, border_style="blue"))

    # Bucket by level.
    buckets: dict[str, list] = {"CRITICAL": [], "HIGH": [], "MEDIUM": [], "LEARNING": []}
    for it in items:
        lvl = policy.classify(policy.effective_score(it))
        buckets["LEARNING" if lvl == "LOW" else lvl].append(it)

    for level in ("CRITICAL", "HIGH", "MEDIUM"):
        bucket = buckets[level]
        if not bucket:
            continue
        label, style = _LEVEL_STYLE[level]
        console.print(f"\n{label}", style=style)
        console.print("━" * 48, style=style)
        for it in sorted(bucket, key=lambda x: policy.effective_score(x), reverse=True):
            console.print(_render_item(it, it.dedup_key() in dumped_keys))

    # Lower-scored items shown as a compact learning feed.
    if buckets["LEARNING"]:
        console.print("\n📚 LEARNING / FYI", style="bold green")
        console.print("━" * 48, style="green")
        for it in buckets["LEARNING"][:8]:
            # markup=False: titles/sources may contain '[' which rich would
            # otherwise parse as style tags.
            console.print(f"  • [{it.source}] {it.title}", style="dim", markup=False)

    # Stats footer.
    console.print("\n📊 SCAN STATS", style="bold")
    console.print("━" * 48)
    console.print(f"  Scanned:        {stats.get('scanned', 0)} items")
    console.print(f"  Relevant:       {stats.get('relevant', 0)} items")
    console.print(f"  High priority:  {stats.get('high_priority', 0)} items")
    console.print(f"  TaskFlow dumps: {stats.get('dumps', 0)} tasks")
    console.print(f"  Sources OK:     {stats.get('sources_ok', 0)}/{stats.get('sources_total', 0)}")
    console.print(f"\n  Next scan: daily at {config.DAILY_RUN_TIME}\n", style="dim")


if __name__ == "__main__":
    from datetime import timedelta

    from models import Opportunity

    demo = [
        Opportunity("Google Summer of Code 2026", "https://g.co/gsoc", "devpost",
                    "Remote open-source internship with stipend for students.",
                    deadline=datetime.now().date() + timedelta(days=5)),
        Opportunity("AI Hackathon — Devpost", "https://devpost.com/x", "devpost",
                    "Online machine learning hackathon, $5000 prize.",
                    deadline=datetime.now().date() + timedelta(days=14)),
        Opportunity("Scaling Laws for Reward Models", "https://arxiv.org/abs/2606.1", "arxiv",
                    "A deep learning study."),
    ]
    for d in demo:
        from filters.scorer import score_item
        d.score = score_item(d)
    stats = {"scanned": 47, "relevant": 11, "high_priority": 2, "dumps": 2,
             "sources_ok": 1, "sources_total": 1}
    render(demo, stats, dumped_keys={demo[0].dedup_key(), demo[1].dedup_key()})
