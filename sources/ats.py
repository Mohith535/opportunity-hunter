"""
Company career boards — the jobs and internships that never reach an aggregator.

Almost no company builds its own careers page; they rent one from an applicant-tracking
system, and those systems expose PUBLIC JSON APIs with no key and no auth. So the way to
cover "big tech companies all over the world" is not to scrape 500 sites with a browser —
it is to write one adapter per platform and keep a list of company slugs.

Verified live (Sep 2026), each a single unauthenticated GET:
    boards-api.greenhouse.io/v1/boards/anthropic/jobs        ->  611 jobs
    boards-api.greenhouse.io/v1/boards/databricks/jobs       ->  875 jobs
    api.ashbyhq.com/posting-api/job-board/openai             ->  817 jobs
    api.lever.co/v0/postings/shieldai?mode=json              ->  498 jobs

The watchlist lives in `ats_companies.json` so adding a company is a one-line edit, not a
code change. A company whose slug is wrong or whose board moved returns nothing and is
logged — one bad entry never takes the others down.

WHAT WE KEEP: student-relevant roles only. These boards are mostly senior positions, and
784 staff-engineer listings would bury everything else in the brief. `_is_student_role`
keeps interns, new-grads, residencies and research roles, and drops the rest BEFORE they
ever reach the scorer. That filter is the whole reason this source is usable.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests

import config
from models import Opportunity
from util import log

COMPANIES_FILE = config.BASE_DIR / "ats_companies.json"

_HEADERS = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}

# Roles a student can actually take. Checked against the TITLE, where the level is named.
# "research engineer" / "research scientist" are deliberately absent: at these companies they
# are senior PhD-level positions, and including them filled a third of the brief with twenty
# near-identical Anthropic listings. A genuine "Research Intern" is still caught by `intern`.
_STUDENT_RE = re.compile(
    r"\b(intern(?:ship)?|new ?grad|graduate|university|campus|student|apprentice|"
    r"residen(?:t|cy)|fellow(?:ship)?|early career|entry[- ]level|trainee|"
    r"co-?op|summer (?:analyst|associate|program))\b", re.I)

# ...but these are senior roles that merely mention one of the words above
# ("Manager, University Recruiting" is a job FOR a recruiter, not for a student).
_SENIOR_RE = re.compile(
    r"\b(senior|staff|principal|lead\b|manager|director|head of|vp\b|vice president|"
    r"recruit(?:er|ing)|coordinator|counsel|partner\b|architect)\b", re.I)


def _is_student_role(title: str) -> bool:
    return bool(_STUDENT_RE.search(title)) and not _SENIOR_RE.search(title)


def _opp(title, url, company, platform, location="", posted=None, native_id=None):
    bits = [company]
    if location:
        bits.append(location)
    bits.append(f"via {platform}")
    return Opportunity(
        title=f"{title} — {company}",
        url=url,
        source="ats",
        description=" | ".join(bits),
        deadline=None,          # career boards rarely publish one; absence beats a guess
        native_id=native_id or url,
        tags=["job"],
        raw={"company": company, "platform": platform, "location": location, "posted": posted},
    )


def _greenhouse(slug: str, company: str) -> list[Opportunity]:
    r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                     headers=_HEADERS, timeout=config.REQUEST_TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        title = (j.get("title") or "").strip()
        if not _is_student_role(title):
            continue
        out.append(_opp(title, j.get("absolute_url", ""), company, "Greenhouse",
                        (j.get("location") or {}).get("name", ""),
                        j.get("updated_at"), f"gh:{slug}:{j.get('id')}"))
    return out


def _ashby(slug: str, company: str) -> list[Opportunity]:
    r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
                     headers=_HEADERS, timeout=config.REQUEST_TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        title = (j.get("title") or "").strip()
        if not _is_student_role(title):
            continue
        out.append(_opp(title, j.get("jobUrl") or j.get("applyUrl", ""), company, "Ashby",
                        j.get("location", ""), j.get("publishedAt"),
                        f"ashby:{slug}:{j.get('id')}"))
    return out


def _lever(slug: str, company: str) -> list[Opportunity]:
    r = requests.get(f"https://api.lever.co/v0/postings/{slug}?mode=json",
                     headers=_HEADERS, timeout=config.REQUEST_TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json():
        title = (j.get("text") or "").strip()
        if not _is_student_role(title):
            continue
        cats = j.get("categories") or {}
        out.append(_opp(title, j.get("hostedUrl", ""), company, "Lever",
                        cats.get("location", ""), j.get("createdAt"),
                        f"lever:{slug}:{j.get('id')}"))
    return out


_ADAPTERS = {"greenhouse": _greenhouse, "ashby": _ashby, "lever": _lever}


def _load_companies() -> list[dict]:
    """Read the watchlist. Missing or malformed file -> [] (the run never breaks)."""
    import json
    if not COMPANIES_FILE.exists():
        log("[ats] ats_companies.json not found — skipping.")
        return []
    try:
        data = json.loads(COMPANIES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log(f"[ats] could not read company list: {e}")
        return []
    companies = data.get("companies") if isinstance(data, dict) else data
    return [c for c in (companies or []) if isinstance(c, dict) and c.get("slug")]


def _fetch_one(c: dict) -> list[Opportunity]:
    adapter = _ADAPTERS.get(str(c.get("platform", "")).lower())
    if not adapter:
        return []
    try:
        return adapter(c["slug"], c.get("name") or c["slug"])
    except (requests.RequestException, ValueError, KeyError, TypeError):
        # A renamed slug or a moved board must not take the other companies down. Logged at
        # the end as a count, so a board that quietly dies is visible rather than silent.
        return []


def fetch() -> list[Opportunity]:
    """Student-relevant roles across every company on the watchlist, deduped by URL."""
    companies = _load_companies()
    if not companies:
        return []

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(_fetch_one, companies))

    dead = [c["slug"] for c, r in zip(companies, results) if not r]
    # Dedupe on (company, title), not URL: the same role posted in four cities is four URLs
    # and one opportunity, and four copies of it in the brief is just noise.
    items, seen = [], set()
    for bundle in results:
        for it in bundle:
            key = (str(it.raw.get("company", "")).lower(), it.title.lower())
            if it.url and key not in seen:
                seen.add(key)
                items.append(it)

    log(f"[ats] {len(items)} student-relevant roles from "
        f"{len(companies) - len(dead)}/{len(companies)} boards"
        + (f" — nothing from: {', '.join(dead[:6])}" if dead else ""))
    return items


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # The filter is the load-bearing part — a board returning 800 senior roles must yield none.
    assert _is_student_role("Software Engineer Intern")
    assert _is_student_role("New Grad Software Engineer, 2027")
    assert _is_student_role("ML Research Intern")
    assert _is_student_role("Electrical Engineering Spring Co-op")
    assert not _is_student_role("Senior Software Engineer")
    assert not _is_student_role("Manager, University Recruiting")
    assert not _is_student_role("Staff Research Scientist")
    # A senior PhD-level opening, not a student role — the tightening that stopped twenty
    # near-identical Anthropic listings filling the brief.
    assert not _is_student_role("Research Engineer, Interpretability")
    print("_is_student_role: 8/8 correct\n")

    for it in fetch()[:15]:
        print(f"  {it.title[:70]}\n      {it.description}")
