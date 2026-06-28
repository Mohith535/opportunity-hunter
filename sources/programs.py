"""
Flagship programs — a curated watchlist of the elite, recurring opportunities that
generic feeds miss: GSoC, MLH Fellowship, Outreachy, Microsoft Student Ambassadors,
NVIDIA DLI, Kaggle, Hugging Face, IBM SkillsBuild, Anthropic, Google programs...

Why a curated list and not a scraper: these live on JS-heavy marketing pages with
no clean feed, and scraping them is brittle. A maintained JSON file never breaks —
and the Phase-2 LLM scorer ranks each entry against Mohith's profile, so the elite
ones rise and stale ones sink. That makes "make sure my agent catches all these
programs" a guarantee, not a hope.

These are PUBLIC programs, so the list (flagship_programs.json) is committed. Edit
that file to curate; this module just reads it. Missing/!malformed file -> [] (the
run never breaks), exactly like every other source.
"""

import json
from datetime import date

import config
from models import Opportunity
from util import log

PROGRAMS_FILE = config.BASE_DIR / "flagship_programs.json"


def _parse_deadline(value):
    """A program carries a real deadline only when we know one; else None."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def fetch() -> list[Opportunity]:
    if not PROGRAMS_FILE.exists():
        log("[programs] flagship_programs.json not found — skipping.")
        return []
    try:
        data = json.loads(PROGRAMS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log(f"[programs] could not read flagship list: {e}")
        return []

    programs = data.get("programs") if isinstance(data, dict) else data
    items: list[Opportunity] = []
    for p in programs or []:
        if not isinstance(p, dict):
            continue
        title = (p.get("title") or "").strip()
        if not title:
            continue
        # Fold the typical window into the description so the scorer can reason
        # about timing even when there's no hard deadline.
        window = p.get("window")
        desc = (p.get("description") or "").strip()
        if window:
            desc = f"{desc} (Typical window: {window})".strip()
        items.append(
            Opportunity(
                title=title,
                url=p.get("url", ""),
                source="programs",
                description=desc,
                deadline=_parse_deadline(p.get("deadline")),
                native_id=p.get("id") or title,
                tags=p.get("tags") or ["program"],
                raw={"org": p.get("org"), "window": window},
            )
        )
    return items


if __name__ == "__main__":
    progs = fetch()
    print(f"Loaded {len(progs)} flagship programs:\n")
    for o in progs:
        print(f"  • {o.title}  [{o.raw.get('org')}]")
        print(f"      {o.url}")
