"""
Hackathon sources (CLAUDE.md §5.1).

Phase: Devpost now; MLH + Unstop added later (most fragile, so last).

Devpost's `.atom` feed is hard-blocked (HTTP 406 for non-browser clients), so we
use its public JSON API instead — which is richer anyway: it carries location,
submission dates, prize amount, and themes. That makes Devpost the first source
with a real, parseable deadline, which feeds the deadline-urgency scoring and
makes items genuinely dump-worthy (TaskFlow path).
"""

import html
import json
import re
from datetime import date, datetime
from urllib.parse import unquote

import requests

import config
from models import Opportunity

DEVPOST_API = "https://devpost.com/api/hackathons"
DEVFOLIO_API = "https://api.devfolio.co/api/hackathons"
DEVFOLIO_MAX = 25  # keep the soonest upcoming ones
# Devpost 406s the bot UA; use a browser-like UA for this source.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def _strip(text: str) -> str:
    # unescape entities too - stripping tags but leaving "&ndash;" in the text is half a job,
    # and that text goes straight to the ranker.
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))).strip()


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


# ─── DEVFOLIO (India-focused hackathon platform) ─────────────────────
def _parse_iso(ts: str):
    """Parse Devfolio's ISO timestamps ('2026-06-20T02:30:00.000Z')."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_devfolio() -> list[Opportunity]:
    """Upcoming/ongoing hackathons from Devfolio's JSON API, soonest first.

    The API lists ~1900 hackathons (incl. past), so we drop finished events,
    sort by start date, and keep the nearest DEVFOLIO_MAX. `starts_at` is used as
    the act-by deadline (register before it starts); ongoing events fall back to
    `ends_at`.
    """
    resp = requests.get(
        DEVFOLIO_API, headers=_HEADERS, params={"filter": "all", "page": 1},
        timeout=config.REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    today = date.today()

    upcoming = []
    for h in resp.json().get("result", []):
        starts = _parse_iso(h.get("starts_at"))
        ends = _parse_iso(h.get("ends_at"))
        if ends and ends.date() < today:
            continue  # already finished
        upcoming.append((starts, ends, h))
    upcoming.sort(key=lambda x: x[0] or datetime.max.replace(tzinfo=x[0].tzinfo if x[0] else None))

    items: list[Opportunity] = []
    for starts, ends, h in upcoming[:DEVFOLIO_MAX]:
        if starts and starts.date() >= today:
            deadline = starts.date()           # register before it starts
        elif ends:
            deadline = ends.date()             # ongoing -> submission end
        else:
            deadline = None
        online = bool(h.get("is_online"))
        location = "online" if online else ", ".join(
            p for p in (h.get("city"), h.get("country")) if p
        )
        themes = ", ".join(
            t.get("name", "") for t in (h.get("themes") or []) if t.get("name")
        )
        slug = h.get("slug", "")
        description = f"hackathon | {location} | themes: {themes}"
        items.append(
            Opportunity(
                title=_strip(h.get("name")),
                url=f"https://{slug}.devfolio.co" if slug else "https://devfolio.co",
                source="devfolio",
                description=description,
                deadline=deadline,
                native_id=h.get("uuid") or slug,
                tags=["hackathon"],
                raw={"is_online": online, "country": h.get("country"),
                     "starts_at": h.get("starts_at")},
            )
        )
    return items


# ─── MLH (Major League Hacking) ──────────────────────────────────────
# MLH's old `div.event-wrapper` markup is gone (modern JS site). Events now link
# out to events.mlh.io/events/{id}-{slug}, with a clean title in the link's
# utm_content. We scrape those links resiliently; if MLH changes again, this
# yields 0 (via safe_fetch) without breaking the run. No structured date is
# exposed on the listing, so deadline stays None.
MLH_SEASON_URL = "https://mlh.io/seasons/{year}/events"
MLH_MAX = 15
_MLH_LINK_RE = re.compile(r'href="(https://events\.mlh\.io/events/(\d+)-[^"?]+)[^"]*"')


def fetch_mlh() -> list[Opportunity]:
    # Cover the season rollover by checking the current and next season pages.
    years = sorted({date.today().year, date.today().year + 1})
    found: dict[str, tuple[str, str]] = {}
    for y in years:
        try:
            html = requests.get(
                MLH_SEASON_URL.format(year=y), headers=_HEADERS,
                timeout=config.REQUEST_TIMEOUT,
            ).text
        except requests.RequestException:
            continue
        for m in _MLH_LINK_RE.finditer(html):
            url, eid = m.group(1), m.group(2)
            if eid in found:
                continue
            cm = re.search(r"utm_content=([^&\"]+)", m.group(0))
            title = unquote(cm.group(1).replace("+", " ")) if cm else f"MLH event {eid}"
            found[eid] = (_strip(title), url)

    items: list[Opportunity] = []
    for eid, (title, url) in list(found.items())[:MLH_MAX]:
        items.append(
            Opportunity(
                title=title,
                url=url,
                source="mlh",
                description=f"hackathon | MLH event | {title}",
                native_id=f"mlh-{eid}",
                tags=["hackathon"],
            )
        )
    return items


# ─── UNSTOP (India-focused opportunities) ────────────────────────────
# Same public JSON API across categories — so beyond hackathons we also pull
# internships, competitions, and scholarships (where Google/Microsoft/Amazon
# student programs and AI challenges are routinely posted). One category failing
# never kills the others; ids are deduped across categories.
UNSTOP_API = "https://unstop.com/api/public/opportunity/search-result"
# Probed against the live API (Sep 2026): these are the categories that actually return data.
# workshops/conferences give him the MEETUPS he asked for and jobs gives full-time roles — all
# through the adapter we already had, so neither needed a new scraper. Categories returning 0
# (webinars, courses, mentorships, cultural-events) are left out rather than fetched pointlessly.
UNSTOP_CATEGORIES = ("hackathons", "internships", "competitions", "scholarships",
                     "jobs", "workshops", "conferences")
# Singular labels for the ones whose plural does not simply lose an "s".
UNSTOP_LABELS = {"conferences": "conference"}
# We used to take the top 8 per category, once. Measured against the live API that was 4% of
# open hackathons and 1.3% of open competitions — which is exactly how "Fund My Crazy" (Google
# Gemini, Rs 1 crore, listed on Unstop) was never seen: it sat in the other 98.7%.
#
# The API is paginated and free, so we now read several pages. This does NOT cost more LLM
# quota — llm_scorer caps itself at LLM_MAX_ITEMS and picks the best of what it is given, so a
# wider net only improves what that cap gets to choose from. config.INTAKE_BUDGET is the
# downstream guard for everything else.
UNSTOP_PER_CATEGORY = 30
UNSTOP_PAGES = 3


def _elig_text(raw) -> str:
    """Unstop returns eligibility as a JSON blob. Dumping it raw wastes tokens and reads like
    noise; parsed, it is one of the most useful signals we have - it is what lets the scorer's
    eligibility gate correctly reject school-only or PhD-only listings."""
    if not raw:
        return ""
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return _strip(raw)[:200]
    if not isinstance(data, dict):
        return _strip(str(data))[:200]

    bits = []
    for key, label in (("sector", "open to: "), ("others", ""), ("experience", "experience: ")):
        vals = [str(v) for v in (data.get(key) or []) if v and str(v) != "all"]
        if vals:
            bits.append(label + ", ".join(vals[:4]))
    courses, years = [], set()
    if "allCourses" in (data.get("engineering") or []):
        courses.append("allEngineering")           # every engineering course, B.Tech included
    for group in ("engineering", "bSchools", "arts", "medicine", "law", "others"):
        for entry in data.get(group) or []:
            if not isinstance(entry, dict):
                continue
            c = str(entry.get("course") or "")
            if c and c not in courses:
                courses.append(c)                  # engineering first: it is the group that decides
            for y in entry.get("passoutYear") or []:
                if str(y) != "all":
                    years.add(str(y))
    for y in data.get("studentPassoutYearsSelected") or []:     # e.g. [2027, 2028, 2029, 2030]
        if str(y).isdigit():
            years.add(str(y))
    # This line used to be `sorted(courses)[:6]`. Alphabetically, btech comes after artsOthers, ba,
    # barch, bba, bca and bdes — so it was cut from nearly every list, and the eligibility check
    # read "courses: artsOthers, ba, barch, bba, bca, bdes" as "not open to B.Tech" and hid 33 real
    # internships and hackathons from him. Engineering first now, and a cut list SAYS it was cut.
    # Short, decisive fields first — who, experience, passout — and the long course list last, so the
    # 200-character cap in the description never cuts "open to: fresher" down to "open to: fr" again.
    if years:
        bits.append("passout: " + ", ".join(sorted(years)))
    if courses:
        more = len(courses) - 6
        bits.append("courses: " + ", ".join(courses[:6]) + (f" (+{more} more)" if more > 0 else ""))
    return "; ".join(bits)[:220]


def _unstop_deadline(o: dict):
    """The registration deadline Unstop hands us in every listing. The old parser ignored it,
    which is why only 9% of the whole corpus ever had a deadline to score against."""
    reg = o.get("regnRequirements") or {}
    for raw in (reg.get("end_regn_dt"), o.get("end_date")):
        if not raw:
            continue
        try:
            return datetime.fromisoformat(str(raw)).date()
        except (ValueError, TypeError):
            continue
    return None


def _unstop_pay_location(o: dict) -> dict:
    """Pull PAY and PLACE out of the listing — the two facts that decide whether a paid role in a
    specific city is even worth reading. Both were being discarded, same as the deadline was.

    `jobDetail` carries min_salary / max_salary / currency / locations / type (wfh|in_office).
    Returns {pay_min, pay_max, remote, cities} with pay normalised to RUPEES PER MONTH.

    NOTE on `isPaid`: do not use it. Measured across 235 live listings it was false/absent on
    every single one, including listings quoting a 25,000/month stipend. A filter built on it
    would reject everything. `max_salary > 0` is the honest signal.

    ponytail: annual-vs-monthly is a threshold heuristic (>= 100000 means annual CTC), because
    the API does not say which unit it used. Internship stipends are monthly and job salaries
    are usually annual, so the split is right for the common case and wrong for a 1.2L/yr job.
    Upgrade path: read `subtype` per listing if that ever matters more than it does now."""
    jd = o.get("jobDetail") or {}
    cities = [str(c).strip() for c in (jd.get("locations") or []) if c]
    if not cities:
        cities = [str(l.get("city", "")).strip() for l in (o.get("locations") or [])
                  if isinstance(l, dict) and l.get("city")]

    def per_month(v):
        try:
            n = int(v or 0)
        except (TypeError, ValueError):
            return 0
        return round(n / 12) if n >= 100_000 else n

    # `region` is "online" on every internship and job (60 of 60 live, Sep 2026) — it is how you
    # register. Where the work happens is `jobDetail.type`: wfh, in_office, hybrid or on_field. Reading
    # region made 33 in-office roles "remote", so the Mumbai lever never fired on a Mumbai job. Region
    # only decides for listings with no jobDetail type: hackathons and other events.
    jtype = str(jd.get("type") or "").lower()
    remote = jtype == "wfh" if jtype else str(o.get("region", "")).lower() == "online"
    return {
        "pay_min": per_month(jd.get("min_salary")),
        "pay_max": per_month(jd.get("max_salary")),
        "remote": remote,
        "cities": [c for c in cities if c],
    }


def _unstop_description(o: dict, label: str, region: str, tag_text: str) -> str:
    """A real description built from fields the API already returns: event details, prize money,
    eligibility and team size. The old code synthesised '<label> | <region> | India | tags: ' -
    about 34 characters - so the ranker was effectively judging on the title alone."""
    parts = [f"{label} | {region or 'India'}"]
    if tag_text:
        parts.append(f"tags: {tag_text}")

    # Pay and place, stated plainly. In the text as well as in `raw` so the LLM scorer and the
    # brief can both see it, not just the target filter.
    pl = _unstop_pay_location(o)
    if pl["pay_max"]:
        lo, hi = pl["pay_min"], pl["pay_max"]
        parts.append(f"Pay: Rs {lo:,}-{hi:,}/month" if lo and lo != hi else f"Pay: Rs {hi:,}/month")
    if pl["cities"]:
        parts.append("Location: " + ", ".join(pl["cities"][:4]))
    if pl["remote"]:
        parts.append("Remote/WFH")

    reg = o.get("regnRequirements") or {}
    elig = _elig_text(reg.get("eligibility"))
    if elig:
        parts.append(f"Eligibility: {elig[:200]}")
    lo, hi = reg.get("min_team_size"), reg.get("max_team_size")
    if lo or hi:
        parts.append(f"Team size: {lo or 1}-{hi or lo}")

    cash = 0
    for p in o.get("prizes") or []:
        try:
            cash = max(cash, int(p.get("cash") or 0))
        except (TypeError, ValueError):
            continue
    if cash:
        # Also feeds the rule scorer's "prize/stipend mentioned" point, which could never fire
        # before because the synthetic description contained no money at all.
        parts.append(f"Prize: cash {cash}")

    skills = [s.get("name", "") if isinstance(s, dict) else str(s)
              for s in (o.get("required_skills") or [])]
    skills = [s for s in skills if s]
    if skills:
        parts.append("Skills: " + ", ".join(skills[:8]))

    org = (o.get("organisation") or {}).get("name") if isinstance(o.get("organisation"), dict) else None
    if org:
        parts.append(f"By {org}")

    details = _strip(o.get("details") or "")
    if details:
        parts.append(details[:700])
    return " | ".join(parts)


def _unstop_page(category: str, page: int) -> list:
    """One page of listings, or [] when the page is past the end."""
    resp = requests.get(
        UNSTOP_API, headers={**_HEADERS, "Accept": "application/json"},
        params={"opportunity": category, "page": page,
                "per_page": UNSTOP_PER_CATEGORY, "oppstatus": "open"},
        timeout=config.REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json().get("data", {})
    listings = data.get("data") if isinstance(data, dict) else data
    return listings or []


def _fetch_unstop_category(category: str) -> list[Opportunity]:
    listings: list = []
    for page in range(1, UNSTOP_PAGES + 1):
        try:
            batch = _unstop_page(category, page)
        except requests.RequestException:
            break  # keep whatever earlier pages gave us; a partial read beats none
        if not batch:
            break  # ran off the end of this category
        listings.extend(batch)

    # hackathons -> hackathon, internships -> internship, conferences -> conference
    label = UNSTOP_LABELS.get(category, category.rstrip("s"))
    items: list[Opportunity] = []
    for o in listings:
        seo = o.get("seo_url") or ""
        url = seo if seo.startswith("http") else f"https://unstop.com/{o.get('public_url', '')}"
        region = o.get("region", "")
        tags = o.get("tags") or []
        tag_text = ", ".join(t.get("name", "") for t in tags if isinstance(t, dict) and t.get("name"))
        items.append(
            Opportunity(
                title=_strip(o.get("title")),
                url=url,
                source="unstop",
                description=_unstop_description(o, label, region, tag_text),
                deadline=_unstop_deadline(o),
                native_id=str(o.get("id", "")),
                tags=[label],
                raw={"status": o.get("status"), "region": region, "category": category,
                     "registrations": o.get("registerCount"), "views": o.get("viewsCount"),
                     **_unstop_pay_location(o)},
            )
        )
    return items


def fetch_unstop() -> list[Opportunity]:
    """Open opportunities across Unstop categories, deduped by id."""
    seen: set[str] = set()
    items: list[Opportunity] = []
    for category in UNSTOP_CATEGORIES:
        try:
            for it in _fetch_unstop_category(category):
                if it.native_id and it.native_id in seen:
                    continue
                seen.add(it.native_id)
                items.append(it)
        except requests.RequestException:
            continue  # this category failed; keep the others
    return items


if __name__ == "__main__":
    from filters.scorer import score_item

    print("===== Devpost =====")
    dp = fetch_devpost()
    for o in dp:
        o.score = score_item(o)
    for o in sorted(dp, key=lambda x: x.score, reverse=True):
        dl = f"deadline {o.deadline}" if o.deadline else "no deadline"
        print(f"  [{o.score}] {o.title[:50]}  ({dl})")

    print(f"\n===== Devfolio ({len(fetch_devfolio())} upcoming) =====")
    df = fetch_devfolio()
    for o in df:
        o.score = score_item(o)
    for o in sorted(df, key=lambda x: x.score, reverse=True)[:12]:
        loc = o.raw.get("country") or ("online" if o.raw.get("is_online") else "?")
        print(f"  [{o.score}] {o.title[:40]:40}  start/deadline {o.deadline}  ({loc})")
