"""
Aggregator source — SimplifyJobs × Pitt CSC internships feed.

A community-curated + auto-scraped list of tech internships, updated daily, with
per-listing `active` / `is_visible` flags that Simplify re-checks ~hourly. That
gives us a first layer of verification (we keep only active+visible roles), and
the pipeline runs these through verifier.py for an independent liveness check
before any reach you — because aggregators carry stale/dead listings.

We keep this AI/ML/SWE-relevant and capped (newest first), so the LLM scorer ranks
the genuinely-good ones up and the generic ones never reach your phone.
"""

import re

import requests

import config
from models import Opportunity

FEED = ("https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships"
        "/dev/.github/scripts/listings.json")

# AI/ML/data/research roles first; plain software still allowed (LLM ranks it lower).
_RELEVANT = re.compile(
    r"machine learning|deep learning|\bml\b|\bai\b|artificial intelligence|"
    r"data scien|research scien|applied scien|\bnlp\b|\bllm\b|computer vision|"
    r"software|backend|full.?stack|developer",
    re.IGNORECASE,
)
MAX_ITEMS = 25


def fetch() -> list[Opportunity]:
    resp = requests.get(FEED, headers={"User-Agent": config.USER_AGENT},
                        timeout=max(config.REQUEST_TIMEOUT, 30))
    resp.raise_for_status()
    listings = resp.json()

    rows = []
    for x in listings:
        # Layer 1 verification: trust Simplify's own liveness flags.
        if not (x.get("active") and x.get("is_visible", True)):
            continue
        title = x.get("title") or ""
        if not _RELEVANT.search(title):
            continue
        posted = x.get("date_posted") or x.get("date_updated") or 0
        rows.append((posted, x))

    rows.sort(key=lambda r: r[0], reverse=True)  # newest postings first

    items: list[Opportunity] = []
    for _, x in rows[:MAX_ITEMS]:
        company = (x.get("company_name") or "").strip()
        title = (x.get("title") or "").strip()
        locs = ", ".join(x.get("locations") or [])
        terms = ", ".join(x.get("terms") or [])
        spons = x.get("sponsorship") or ""
        url = x.get("url") or x.get("company_url") or ""
        desc = f"internship | {company} | {locs} | {terms}"
        if spons:
            desc += f" | {spons}"
        items.append(
            Opportunity(
                title=f"{company} — {title}" if company else title,
                url=url,
                source="internships",
                description=desc,
                native_id=str(x.get("id") or url),
                tags=["internship"],
                raw={"company": company, "locations": x.get("locations"),
                     "aggregator": x.get("source")},
            )
        )
    return items


if __name__ == "__main__":
    out = fetch()
    print(f"Fetched {len(out)} active internships (newest first):\n")
    for o in out[:12]:
        print(f"  • {o.title[:60]}")
        print(f"      {o.url[:70]}")
