"""
Hackathon sources (CLAUDE.md §5.1).

Phase: Devpost now; MLH + Unstop added later (most fragile, so last).

Devpost's `.atom` feed is hard-blocked (HTTP 406 for non-browser clients), so we
use its public JSON API instead — which is richer anyway: it carries location,
submission dates, prize amount, and themes. That makes Devpost the first source
with a real, parseable deadline, which feeds the deadline-urgency scoring and
makes items genuinely dump-worthy (TaskFlow path).
"""

import re
from datetime import datetime

import requests

import config
from models import Opportunity

DEVPOST_API = "https://devpost.com/api/hackathons"
# Devpost 406s the bot UA; use a browser-like UA for this source.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def _strip(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(text or ""))).strip()


def _parse_deadline(period: str):
    """'May 19 - Aug 17, 2026' -> date(2026, 8, 17). Returns None if unparseable."""
    if not period:
        return None
    end = period.split("-")[-1].strip()  # take the closing date
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(end, fmt).date()
        except ValueError:
            continue
    return None


def fetch_devpost() -> list[Opportunity]:
    resp = requests.get(DEVPOST_API, headers=_HEADERS, timeout=config.REQUEST_TIMEOUT)
    resp.raise_for_status()
    hackathons = resp.json().get("hackathons", [])

    items: list[Opportunity] = []
    for h in hackathons:
        location = _strip(h.get("displayed_location", {}).get("location")
                          if isinstance(h.get("displayed_location"), dict)
                          else h.get("displayed_location"))
        dates = _strip(h.get("submission_period_dates"))
        prize = _strip(h.get("prize_amount"))
        themes = ", ".join(t.get("name", "") for t in h.get("themes", []) if t.get("name"))
        # Fold all signal into description so the keyword filter/scorer see it:
        # "hackathon" guarantees an interest match; location feeds remote/online;
        # prize feeds the money bonus; themes feed topical relevance.
        description = (
            f"hackathon | {location} | {dates} | prize {prize} | themes: {themes}"
        )
        items.append(
            Opportunity(
                title=_strip(h.get("title")),
                url=h.get("url", ""),
                source="devpost",
                description=description,
                deadline=_parse_deadline(dates),
                native_id=str(h.get("id", "")) or h.get("url", ""),
                tags=["hackathon"],
                raw={
                    "open_state": h.get("open_state"),
                    "time_left": _strip(h.get("time_left_to_submission")),
                    "prize_amount": prize,
                },
            )
        )
    return items


# Convenience alias for the registry.
fetch = fetch_devpost


if __name__ == "__main__":
    from filters.scorer import score_item

    results = fetch_devpost()
    print(f"Fetched {len(results)} Devpost hackathons\n")
    for o in results:
        o.score = score_item(o)
    for o in sorted(results, key=lambda x: x.score, reverse=True):
        dl = f"deadline {o.deadline}" if o.deadline else "no deadline"
        print(f"  [{o.score}] {o.title[:50]}  ({dl})")
