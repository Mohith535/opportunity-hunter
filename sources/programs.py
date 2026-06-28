"""
Flagship programs — a curated watchlist of the elite, recurring opportunities that
generic feeds miss: GSoC, MLH Fellowship, Outreachy, Microsoft Student Ambassadors,
NVIDIA DLI, Kaggle, Hugging Face, IBM, Anthropic, Amazon ML Summer School, Samsung
PRISM, LFX, Google/Meta/OpenAI programs...

Why a curated list and not a scraper: these live on JS-heavy marketing pages with
no clean feed, and scraping them is brittle. A maintained JSON file never breaks —
and the Phase-2 LLM scorer ranks each entry against Mohith's profile.

DEADLINE RADAR (Phase B+): each program carries a plain-English `window` (e.g.
"Registration ~May-Jun", "autumn", "Spring/Summer/Fall"). The radar infers the
window MONTHS from that text and, when a program is IN SEASON this month, it:
  * gives it a synthetic deadline (end of month) so urgency scoring + the deadline
    display kick in,
  * re-keys its id per year (`<id>-<year>`) so it RE-SURFACES once each season
    instead of being deduped forever,
  * tags it `in-season` and prefixes the description with [WINDOW OPEN].
Programs whose window opens NEXT month are tagged `opening-soon`. Rolling/always-on
programs (no month in their window text) are unaffected — surfaced once, normally.

These are PUBLIC programs, so flagship_programs.json is committed. Edit that file to
curate; this module just reads it. Missing/!malformed file -> [] (run never breaks).
"""

import calendar
import json
import re
from datetime import date

import config
from models import Opportunity
from util import log

PROGRAMS_FILE = config.BASE_DIR / "flagship_programs.json"

_MONTH_ABBR = ["jan", "feb", "mar", "apr", "may", "jun",
               "jul", "aug", "sep", "oct", "nov", "dec"]
_SEASONS = {
    "spring": [3, 4, 5], "summer": [6, 7, 8],
    "autumn": [9, 10, 11], "fall": [9, 10, 11], "winter": [12, 1, 2],
    "early year": [1, 2, 3], "year-end": [11, 12], "year end": [11, 12],
}
# Words that mean "no fixed season" — the radar leaves these alone.
_ROLLING = ("rolling", "always", "anytime", "self-paced", "self paced",
            "year-round", "year round", "continuous")


def _window_months(window: str) -> list[int]:
    """Infer the window months (1-12) from the plain-English `window` text.
    Returns [] for rolling/always-on programs (no radar nudging)."""
    if not window:
        return []
    text = window.lower()
    if any(r in text for r in _ROLLING) and not any(
        re.search(rf"\b{a}", text) for a in _MONTH_ABBR
    ):
        return []
    months: set[int] = set()
    for i, abbr in enumerate(_MONTH_ABBR, start=1):
        if re.search(rf"\b{abbr}", text):   # matches jan/january, jun/june, ...
            months.add(i)
    for season, ms in _SEASONS.items():
        if season in text:
            months.update(ms)
    return sorted(months)


def _end_of_month(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _parse_deadline(value):
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
    today = date.today()
    next_month = today.month % 12 + 1

    items: list[Opportunity] = []
    for p in programs or []:
        if not isinstance(p, dict):
            continue
        title = (p.get("title") or "").strip()
        if not title:
            continue

        window = p.get("window")
        deadline = _parse_deadline(p.get("deadline"))
        native_id = p.get("id") or title
        tags = list(p.get("tags") or ["program"])
        desc = (p.get("description") or "").strip()

        # ── Deadline Radar ───────────────────────────────────────────
        months = _window_months(window or "")
        status = ""
        if not deadline and months:
            if today.month in months:
                status = "WINDOW OPEN"
                deadline = _end_of_month(today)        # synthetic urgency
                native_id = f"{native_id}-{today.year}"  # re-surface once per year
                tags.append("in-season")
            elif next_month in months:
                status = "OPENS SOON"
                tags.append("opening-soon")

        if window:
            desc = f"{desc} (Typical window: {window})".strip()
        if status:
            desc = f"[{status}] {desc}"

        items.append(
            Opportunity(
                title=title,
                url=p.get("url", ""),
                source="programs",
                description=desc,
                deadline=deadline,
                native_id=native_id,
                tags=tags,
                raw={"org": p.get("org"), "window": window, "radar": status or None},
            )
        )
    return items


if __name__ == "__main__":
    progs = fetch()
    today = date.today()
    print(f"Loaded {len(progs)} flagship programs (today: {today})\n")
    live = [o for o in progs if o.raw.get("radar")]
    print(f"Radar — {len(live)} program(s) in/near their window this month:")
    for o in live:
        print(f"  [{o.raw['radar']:11}] {o.title}  "
              f"(deadline: {o.deadline or '—'})")
