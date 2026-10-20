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

import html
import json as _json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlencode

import requests

import config
from models import Opportunity
from util import log

COMPANIES_FILE = config.BASE_DIR / "ats_companies.json"

_HEADERS = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
# Big-company career sites (Workday, Microsoft, Google, Avature) answer a browser-shaped agent; a bare
# one came back empty from Microsoft on 20 Oct. It still names this program, so a log reader knows who called.
_BROWSER = {"User-Agent": f"Mozilla/5.0 (compatible; {config.USER_AGENT})", "Accept": "application/json, text/html"}

# Wall-clock budget per board, and a hard size cap.
#
# requests' `timeout` is NOT a total-time limit — it bounds the connect and the gap BETWEEN
# bytes. A board that streams a huge body slowly never trips it: measured on live boards,
# lever/shieldai took 236s and lever/paytm 105s against a 10s REQUEST_TIMEOUT, and those two
# alone turned a 65-board fetch into 3.5 minutes. So we stream and enforce our own deadline.
# A board that cannot answer inside the budget is skipped and named in the log, never silently.
BOARD_BUDGET_SEC = 25
BOARD_MAX_BYTES = 16 * 1024 * 1024    # OpenAI's Ashby board was 13.5 MB on 21 Oct (3 s to fetch); 8 MB skipped it


def _get_json(url: str, budget: float = BOARD_BUDGET_SEC, body: dict | None = None, text: bool = False):
    """GET JSON under a real wall-clock budget. Raises on timeout/oversize like any fetch error,
    so one slow board is handled by the same path as one broken board.

    Boards fetch in parallel, so total run time is the SLOWEST board, not the sum. That is why a
    company worth waiting for can raise its own budget (`"budget": 120` in ats_companies.json)
    without every other board paying for it."""
    hdr = _BROWSER if (body is not None or text or "careers.microsoft" in url) else _HEADERS
    r = (requests.post(url, json=body, headers=hdr, timeout=config.REQUEST_TIMEOUT, stream=True) if body is not None
         else requests.get(url, headers=hdr, timeout=config.REQUEST_TIMEOUT, stream=True))
    try:
        r.raise_for_status()
        started, size, chunks = time.monotonic(), 0, []
        for chunk in r.iter_content(64 * 1024):
            chunks.append(chunk)
            size += len(chunk)
            if time.monotonic() - started > budget:
                raise requests.Timeout(f"exceeded {budget}s budget")
            if size > BOARD_MAX_BYTES:
                raise requests.RequestException(f"body over {BOARD_MAX_BYTES} bytes")
        raw = b"".join(chunks).decode("utf-8", "replace")
        return raw if text else _json.loads(raw)
    finally:
        r.close()

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


def _greenhouse(slug: str, company: str, budget=BOARD_BUDGET_SEC, entry=None) -> list[Opportunity]:
    data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", budget)
    out = []
    for j in data.get("jobs", []):
        title = (j.get("title") or "").strip()
        if not _is_student_role(title):
            continue
        out.append(_opp(title, j.get("absolute_url", ""), company, "Greenhouse",
                        (j.get("location") or {}).get("name", ""),
                        j.get("updated_at"), f"gh:{slug}:{j.get('id')}"))
    return out


def _ashby(slug: str, company: str, budget=BOARD_BUDGET_SEC, entry=None) -> list[Opportunity]:
    data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", budget)
    out = []
    for j in data.get("jobs", []):
        title = (j.get("title") or "").strip()
        if not _is_student_role(title):
            continue
        out.append(_opp(title, j.get("jobUrl") or j.get("applyUrl", ""), company, "Ashby",
                        j.get("location", ""), j.get("publishedAt"),
                        f"ashby:{slug}:{j.get('id')}"))
    return out


def _lever(slug: str, company: str, budget=BOARD_BUDGET_SEC, entry=None) -> list[Opportunity]:
    out = []
    for j in _get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json", budget):
        title = (j.get("text") or "").strip()
        if not _is_student_role(title):
            continue
        cats = j.get("categories") or {}
        out.append(_opp(title, j.get("hostedUrl", ""), company, "Lever",
                        cats.get("location", ""), j.get("createdAt"),
                        f"lever:{slug}:{j.get('id')}"))
    return out


# ── The big companies (21 Oct 2026). They do not rent Greenhouse/Lever/Ashby, so 65 boards never saw
# NVIDIA, Adobe, Microsoft, Google or EA — the EA internship he applied to on 4 Oct came from Instagram.
# Each endpoint was called live and its robots.txt read on 20 Oct (docs/PLAN-opportunity-intelligence.md).
# Endpoint shapes cross-checked against career-ops (MIT), providers/{workday,amazon,google,avature}.mjs.
def _q(entry, default="intern"):
    return str((entry or {}).get("query") or default)


def _workday(slug: str, company: str, budget=BOARD_BUDGET_SEC, entry=None) -> list[Opportunity]:
    """slug = "<host>/<tenant>/<site>", e.g. nvidia.wd5/nvidia/NVIDIAExternalCareerSite. Workday's CXS
    search is a POST, 20 per page; its robots.txt leaves /wday/cxs open."""
    host, tenant, site = slug.split("/")
    base = f"https://{host}.myworkdayjobs.com"
    out = []
    for page in range(int((entry or {}).get("pages") or 3)):
        data = _get_json(f"{base}/wday/cxs/{tenant}/{site}/jobs", budget,
                         body={"searchText": _q(entry), "limit": 20, "offset": page * 20, "appliedFacets": {}})
        posts = data.get("jobPostings") or []
        for j in posts:
            title, path = (j.get("title") or "").strip(), j.get("externalPath") or ""
            if path and _is_student_role(title):
                out.append(_opp(title, f"{base}/{site}{path}", company, "Workday",
                                j.get("locationsText", ""), j.get("postedOn"), f"workday:{slug}:{path}"))
        if len(posts) < 20:
            break
    return out


# Amazon's "intern" search in India is mostly fulfilment and admin roles (120 + 73 of 444 on 20 Oct).
_AMAZON_TECH = {"Software Development", "Applied Science", "Machine Learning Science", "Data Science",
                "Research Science", "Business Intelligence", "Hardware Development",
                "Systems, Quality, & Security Engineering", "Solutions Architect",
                "Operations, IT, & Support Engineering"}


def _amazon(slug: str, company: str, budget=BOARD_BUDGET_SEC, entry=None) -> list[Opportunity]:
    """slug = ISO alpha-3 country (IND). `loc_query` is NOT a filter — 1 of 100 "India" results was in
    India on 20 Oct — so the country goes in normalized_country_code[] and is checked again per job."""
    data = _get_json("https://www.amazon.jobs/en/search.json?" + urlencode(
        {"base_query": _q(entry), "normalized_country_code[]": slug, "result_limit": 100}), budget)
    out = []
    for j in data.get("jobs", []):
        title = (j.get("title") or "").strip()
        if j.get("country_code") == slug and j.get("job_category") in _AMAZON_TECH and _is_student_role(title):
            out.append(_opp(title, "https://www.amazon.jobs" + (j.get("job_path") or ""), company, "Amazon",
                            j.get("normalized_location") or j.get("location", ""), j.get("posted_date"),
                            f"amazon:{slug}:{j.get('id_icims')}"))
    return out


def _microsoft(slug: str, company: str, budget=BOARD_BUDGET_SEC, entry=None) -> list[Opportunity]:
    """slug = a location ("India"). apply.careers.microsoft.com robots.txt: Disallow / but Allow /api/pcsx."""
    data = _get_json("https://apply.careers.microsoft.com/api/pcsx/search?" + urlencode(
        {"domain": "microsoft.com", "query": _q(entry), "location": slug, "start": 0}), budget)
    out = []
    for j in (data.get("data") or {}).get("positions") or []:
        title = (j.get("name") or "").strip()
        if _is_student_role(title):
            out.append(_opp(title, f"https://apply.careers.microsoft.com/careers/job/{j.get('id')}", company,
                            "Microsoft Careers", "; ".join(j.get("locations") or []), j.get("postedTs"),
                            f"msft:{j.get('id')}"))
    return out


def _google(slug: str, company: str, budget=BOARD_BUDGET_SEC, entry=None) -> list[Opportunity]:
    """slug = a location. Server-rendered HTML; FIRST PAGE ONLY, because google.com/robots.txt disallows
    every ?page= results URL. Each card's link carries the title in its aria-label."""
    page = _get_json("https://www.google.com/about/careers/applications/jobs/results/?" + urlencode(
        {"q": _q(entry), "location": slug}), budget, text=True)
    out, seen = [], set()
    for m in re.finditer(r'href="jobs/results/(\d+)-([^"?]+)[^"]*"\s+aria-label="Learn more about ([^"]+)"', page):
        jid, path, title = m.group(1), m.group(2), html.unescape(m.group(3)).strip()
        if jid not in seen and _is_student_role(title):
            seen.add(jid)
            out.append(_opp(title, f"https://www.google.com/about/careers/applications/jobs/results/{jid}-{path}",
                            company, "Google Careers", slug, None, f"google:{jid}"))
    return out


def _avature(slug: str, company: str, budget=BOARD_BUDGET_SEC, entry=None) -> list[Opportunity]:
    """slug = "<host>/<locale>/careers", e.g. jobs.ea.com/en_US/careers (EA). 20 cards a page, paged
    with jobOffset; its robots.txt allows /*/careers (only ?qtvc= links are disallowed)."""
    out = []
    for page in range(int((entry or {}).get("pages") or 4)):
        body = _get_json(f"https://{slug}/SearchJobs/{_q(entry)}?jobOffset={page * 20}", budget, text=True)
        cards = re.findall(r'<article class="article article--result.*?</article>', body, re.S)
        for c in cards:
            link = re.search(r'href="(https://[^"]+/JobDetail/[^"]+)"[^>]*>\s*([^<]+?)\s*</a>', c)
            where = re.search(r'class="list-item-location"[^>]*>\s*([^<]+?)\s*<', c)
            if link and _is_student_role(html.unescape(link.group(2))):
                rid = link.group(1).rstrip("/").rsplit("/", 1)[-1]
                out.append(_opp(html.unescape(link.group(2)), link.group(1), company, "Avature",
                                html.unescape(where.group(1)) if where else "", None, f"avature:{slug}:{rid}"))
        if len(cards) < 20:
            break
    return out


_ADAPTERS = {"greenhouse": _greenhouse, "ashby": _ashby, "lever": _lever, "workday": _workday,
             "amazon": _amazon, "microsoft": _microsoft, "google": _google, "avature": _avature}


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


_ERRORS: dict[str, str] = {}


def _fetch_one(c: dict) -> list[Opportunity]:
    adapter = _ADAPTERS.get(str(c.get("platform", "")).lower())
    if not adapter:
        return []
    try:
        return adapter(c["slug"], c.get("name") or c["slug"],
                       float(c.get("budget") or BOARD_BUDGET_SEC), c)
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        # A renamed slug or a moved board must not take the other companies down. Logged at the
        # end BY NAME AND REASON: "nothing from" used to mix a board with no student roles today
        # and a board that answered 429, and the two need opposite responses.
        code = getattr(getattr(e, "response", None), "status_code", None)
        _ERRORS[c.get("name") or c["slug"]] = str(code or type(e).__name__)
        return []


def fetch() -> list[Opportunity]:
    """Student-relevant roles across every company on the watchlist, deduped by URL."""
    companies = _load_companies()
    if not companies:
        return []
    _ERRORS.clear()

    # 8, not 24. The boards are NOT independent hosts: every Ashby board is api.ashbyhq.com, every
    # Greenhouse board boards-api.greenhouse.io. Measured 21 Oct on 73 boards: 24 workers → 27 SSL
    # handshake failures (every Ashby board, OpenAI included) and 299 roles in 108 s; 8 workers → 0 SSL
    # failures and 348 roles in 119 s. The 5-minute runs that once made 8 look slow came from boards
    # streaming without a deadline, which BOARD_BUDGET_SEC fixed since.
    with ThreadPoolExecutor(max_workers=min(8, len(companies))) as ex:
        results = list(ex.map(_fetch_one, companies))

    dead = [c["slug"] for c, r in zip(companies, results) if not r and (c.get("name") or c["slug"]) not in _ERRORS]
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
        f"{len(companies) - len(dead) - len(_ERRORS)}/{len(companies)} boards"
        + (f" — no student roles today: {len(dead)}" if dead else "")
        + (" — FAILED: " + ", ".join(f"{k} ({v})" for k, v in list(_ERRORS.items())[:8]) if _ERRORS else ""))
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
