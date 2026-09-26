"""
THE APPLICATION PACK — two files per opportunity, written for a human who applies by hand.

Most ATS forbid bots, and an application is a thing you have to stand behind. So this module
deliberately stops one step short of applying: it prepares, it never submits. What it produces
is the pack you would want open in two tabs while you fill the form yourself.

    applications/<company>-<role>-<date>/
        job.md      Everything known about the job, with nothing dropped: the real apply link,
                    the FULL description straight from the employer's own API, the
                    requirements as the employer listed them, pay, location, deadline, why
                    OPHunter ranked it where it did, and what you must verify before applying.
        resume.md   That job's resume — your real evidence, reordered and reworded for this
                    specific posting, with every claim traceable to career_profile.json.

Where the full description comes from: the same public ATS APIs the `ats` source already reads.
Verified live (Sep 2026) — Greenhouse `?content=true` returns the whole posting (about 6,000
characters), Lever returns `descriptionPlain` plus `lists`, which is the requirements already
broken into "what you will do" and "you should apply if", and Ashby returns `descriptionPlain`
with a compensation block. No scraping, no browser, no credits.

The honesty rule is the same one the rest of this package runs on and it is not negotiable:
nothing is invented. The resume reorders and rephrases what is already in your profile. Where a
bullet would be stronger with a number your profile does not contain, it leaves a visible
`[add metric: ...]` for you to fill rather than making one up. A fabricated resume is a much
worse outcome than a plain one, and it is the kind of thing that ends a career rather than
starting one.

Usage:
    py -m resume.apply --list           # open opportunities, re-scored today, ⛔ not-eligible hidden
    py -m resume.apply --list --all     # ...including the ones you cannot apply to (same numbers)
    py -m resume.apply 3                # build the pack for #3 in that list
    py -m resume.apply <url>            # ...or for a specific opportunity URL
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import requests

import config
from util import log

APPLICATIONS_DIR = config.BASE_DIR / "applications"
_HEADERS = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
_FETCH_TIMEOUT = 25


# ─── plain text ───────────────────────────────────────────────────────────────────────────
def _text(raw: str) -> str:
    """HTML -> readable text, keeping the paragraph and bullet structure an ATS description
    carries. A job description flattened into one wall of prose is technically complete and
    practically useless."""
    if not raw:
        return ""
    s = html.unescape(str(raw))
    if "&lt;" in s or "&gt;" in s:      # Greenhouse double-escapes its content
        s = html.unescape(s)
    s = re.sub(r"(?i)<\s*(br|/p|/div|/h[1-6]|/li)\s*/?>", "\n", s)
    s = re.sub(r"(?i)<\s*li[^>]*>", "\n- ", s)
    s = re.sub(r"(?i)<\s*(h[1-6])[^>]*>", "\n\n**", s)
    s = re.sub(r"(?i)</\s*h[1-6]\s*>", "**\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    # One more unescape AFTER the tags are gone. Greenhouse escapes its markup once and its
    # entities twice, so a single pass turns `&lt;div&gt;` into a tag but leaves `&amp;nbsp;`
    # as a literal `&nbsp;` in the middle of the prose.
    s = html.unescape(s).replace(" ", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return s.strip()


# ─── the full posting, from the employer's own API ────────────────────────────────────────
def _greenhouse_detail(slug: str, job_id: str) -> dict:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}?questions=false"
    j = requests.get(url, headers=_HEADERS, timeout=_FETCH_TIMEOUT).json()
    return {
        "description": _text(j.get("content")),
        "apply_url": j.get("absolute_url", ""),
        "company": j.get("company_name", ""),
        "location": (j.get("location") or {}).get("name", ""),
        "posted": j.get("first_published") or j.get("updated_at"),
        "closes": j.get("application_deadline"),
        "departments": [d.get("name") for d in (j.get("departments") or []) if d.get("name")],
        "offices": [o.get("name") for o in (j.get("offices") or []) if o.get("name")],
    }


def _ashby_detail(slug: str, job_id: str) -> dict:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
    jobs = requests.get(url, headers=_HEADERS, timeout=_FETCH_TIMEOUT).json().get("jobs", [])
    j = next((x for x in jobs if str(x.get("id")) == str(job_id)), None) or {}
    comp = j.get("compensation") or {}
    return {
        "description": j.get("descriptionPlain") or _text(j.get("descriptionHtml")),
        "apply_url": j.get("applyUrl") or j.get("jobUrl", ""),
        "location": j.get("location", ""),
        "posted": j.get("publishedAt"),
        "employment_type": j.get("employmentType", ""),
        "remote": j.get("isRemote"),
        "team": j.get("team") or j.get("department", ""),
        "other_locations": [str(x) for x in (j.get("secondaryLocations") or [])],
        "pay_note": comp.get("compensationTierSummary")
                    or comp.get("scrapeableCompensationSalarySummary") or "",
    }


def _lever_detail(slug: str, job_id: str) -> dict:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    jobs = requests.get(url, headers=_HEADERS, timeout=_FETCH_TIMEOUT).json()
    j = next((x for x in jobs if str(x.get("id")) == str(job_id)), None) or {}
    cats = j.get("categories") or {}
    # Lever's `lists` is the single best requirements source any of these APIs gives: the
    # employer has already split it into "what will you do" / "you should apply if you have".
    sections = []
    for block in j.get("lists") or []:
        head = (block.get("text") or "").strip().rstrip(":")
        body = _text(block.get("content"))
        if head or body:
            sections.append(f"**{head.title()}**\n{body}")
    return {
        "description": "\n\n".join(
            x for x in [j.get("descriptionPlain") or _text(j.get("description")),
                        "\n\n".join(sections),
                        j.get("additionalPlain") or _text(j.get("additional"))] if x),
        "apply_url": j.get("applyUrl") or j.get("hostedUrl", ""),
        "location": cats.get("location", ""),
        "team": cats.get("team") or cats.get("department", ""),
        "employment_type": cats.get("commitment", ""),
        "workplace": j.get("workplaceType", ""),
        "posted": j.get("createdAt"),
    }


_ATS = {"gh": _greenhouse_detail, "ashby": _ashby_detail, "lever": _lever_detail}

_UNSTOP_DETAIL = "https://unstop.com/api/public/competition/{id}"


def _unstop_detail(oid: str) -> dict:
    """The full Unstop listing. The search API gives a truncated blurb — job.md used to cut a
    hackathon's rules off mid-word ("ROUND 0 — Ideation & Screening: R") — while this endpoint returns
    the complete description AND eligibility as data: allowed courses with their passout years, team
    size, gender and city restrictions, region, pay and the registration deadline."""
    from sources.hackathons import _unstop_pay_location  # noqa: PLC0415
    r = requests.get(_UNSTOP_DETAIL.format(id=oid),
                     headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                              "Accept": "application/json"}, timeout=_FETCH_TIMEOUT)
    r.raise_for_status()
    data = r.json().get("data") or {}
    c = data.get("competition") or data
    pl = _unstop_pay_location({"jobDetail": c.get("job_detail") or c.get("jobDetail"),
                               "locations": c.get("locations"), "region": c.get("region")})
    reg = c.get("regnRequirements") or {}
    org = c.get("organisation") if isinstance(c.get("organisation"), dict) else {}
    jd = c.get("job_detail") or {}
    pay = ""
    if pl["pay_max"]:
        pay = (f"Rs {pl['pay_min']:,}–{pl['pay_max']:,}/month" if pl["pay_min"] and pl["pay_min"] != pl["pay_max"]
               else f"Rs {pl['pay_max']:,}/month")
    elif str(jd.get("paid_unpaid", "")).lower() == "unpaid":
        pay = "unpaid"
    # An offline hackathon keeps its city in the venue address, not in `locations` — the Elevate
    # hackathon is in MUMBAI, and job.md said "not stated" for exactly the city he is aiming for.
    addr = c.get("address_with_country_logo") or {}
    city = ", ".join(x for x in [addr.get("city"), addr.get("state")] if x) if isinstance(addr, dict) else ""
    kind = " · ".join(x for x in [str(jd.get("timing") or "").replace("_", " "),
                                  str(jd.get("internship_duration") or "")] if x)
    perks = [p.get("text") for p in jd.get("perks") or [] if isinstance(p, dict) and p.get("value") and p.get("text")]
    return {
        "description": _text(c.get("details")),
        "company": (org or {}).get("name", ""),
        "location": ", ".join(pl["cities"]) or city or ("Online" if pl["remote"] else ""),
        "remote": pl["remote"],
        # jobDetail.type is where the work happens; `region` is only how you register ("Online" on
        # every job), so it describes the workplace only for events that have no type.
        "workplace": {"wfh": "Work from home", "in_office": "In office", "hybrid": "Hybrid",
                      "on_field": "On field"}.get(str(jd.get("type") or "").lower())
                     or (c.get("region") or "").title(),
        "employment_type": kind,
        "perks": perks,
        "openings": jd.get("openings"),
        "pay_note": pay,
        "closes": reg.get("end_regn_dt") or c.get("end_date"),
        "unstop": {"regnRequirements": reg, "filters": c.get("filters") or []},
    }


def fetch_full_jd(item: dict) -> dict:
    """Everything the employer publishes about this role, or {} when we cannot get more.

    Never raises: a pack built from the listing alone is worth far more than a crash, and the
    pack says plainly which of the two it got."""
    native = str(item.get("native_id") or "")
    if item.get("source") == "unstop" and native.isdigit():
        try:
            got = _unstop_detail(native)
            if got.get("description"):
                return got
        except (requests.RequestException, ValueError, KeyError, TypeError) as e:
            log(f"[apply] could not fetch the Unstop listing {native}: {type(e).__name__}")
        return {}
    parts = native.split(":", 2)
    if len(parts) == 3 and parts[0] in _ATS:
        try:
            got = _ATS[parts[0]](parts[1], parts[2])
            if got.get("description"):
                return got
        except (requests.RequestException, ValueError, KeyError, TypeError) as e:
            log(f"[apply] could not fetch full JD ({native}): {type(e).__name__}")
    return {}


# ─── finding the opportunity ──────────────────────────────────────────────────────────────
def recent_items(limit: int = 40) -> list[dict]:
    """The most recent run's items, best first — the same feed the brief and Nova read."""
    try:
        data = json.loads(config.HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    runs = data.get("runs") if isinstance(data, dict) else data
    if not runs:
        return []
    items = list(runs[-1].get("items", []) if isinstance(runs[-1], dict) else [])
    if len(items) < limit:                       # top up from the previous run
        for prev in reversed(runs[:-1]):
            items += list(prev.get("items", []))
            if len(items) >= limit * 2:
                break

    def score(i):
        s = i.get("ai_score", -1)
        return s if s >= 0 else i.get("score", 0)

    seen, out = set(), []
    for i in sorted(items, key=score, reverse=True):
        k = i.get("url") or i.get("title")
        if k and k not in seen:
            seen.add(k)
            out.append(i)
    return out[:limit]


_ELIG_ORDER = {"YES": 0, "NOT_STATED": 1, "CHECK": 2, "NO": 3}


def ranked_items(pool: int = 150, today: date | None = None) -> list[tuple]:
    """(number, item, today's score, eligibility verdict, off_focus), best first — the ONE ranking behind both
    `--list` and `py -m resume.apply <number>`.

    Numbers are given over the whole list, ineligible jobs included, and `--list` merely hides the ⛔
    rows. So "#5" is the same job whether or not you passed --all; a list that renumbered itself after
    filtering would build the pack for a job you never picked. Past deadlines are dropped outright —
    a pack for a closed opportunity is a wasted evening."""
    from filters import focus, target  # noqa: PLC0415
    today = today or date.today()
    cand = _candidate()
    wanted = set(focus.active())
    rows = []
    for i in recent_items(pool):
        dl = str(i.get("deadline") or "")[:10]
        if dl:
            try:
                if date.fromisoformat(dl) < today:
                    continue
            except ValueError:
                pass
        o = _as_opp(i)
        rows.append((i, rescore(i), eligibility_of(i, None, cand), {
            "off": bool(wanted) and focus.kind_of(o) not in wanted,
            "nudge": target.adjustment(o),
            "ai": i.get("ai_score", -1) if isinstance(i.get("ai_score"), int) else -1,
            "dl": dl or "9999"}))
    # The score is capped at 10 and the day's best items all reach it, so a straight sort by score
    # put a Tuesday meetup above an internship. Same zones as the brief's "first" mode — the kinds
    # your target hunts on top — and the ties broken by YOUR target's nudge (Mumbai, pay) before
    # anything else, then the LLM's judgement where it exists, then who can apply, then urgency.
    rows.sort(key=lambda r: (r[3]["off"], -r[1], -r[3]["nudge"], -r[3]["ai"],
                             _ELIG_ORDER.get(r[2].level, 9), r[3]["dl"]))
    return [(n, i, s, v, x["off"]) for n, (i, s, v, x) in enumerate(rows, 1)]


def resolve(ref: str) -> dict | None:
    """An opportunity by list position, dedup key, URL, or a distinctive bit of its title."""
    ref = (ref or "").strip()
    if ref.isdigit():
        n = int(ref)
        return next((r[1] for r in ranked_items() if r[0] == n), None)
    items = recent_items(150)
    low = ref.lower()
    for i in items:
        if ref in (i.get("key", ""), i.get("native_id", "")) or low == (i.get("url", "") or "").lower():
            return i
    for i in items:
        if low and low in (i.get("title", "") or "").lower():
            return i
    return None


# ─── writing the pack ─────────────────────────────────────────────────────────────────────
def _slug(*bits: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", " ".join(b for b in bits if b).lower()).strip("-")
    return (s[:60] or "opportunity").rstrip("-")


def _fmt(v) -> str:
    if v in (None, "", [], {}):
        return "_not stated_"
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v if x) or "_not stated_"
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v)


def _profile() -> dict:
    try:
        return json.loads((config.DATA_DIR / "career_profile.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _candidate(profile: dict | None = None):
    from filters import target  # noqa: PLC0415
    from .eligibility import candidate_from  # noqa: PLC0415
    return candidate_from(profile if profile is not None else _profile(), target.load())


def _as_opp(d: dict):
    """A history dict back as a real Opportunity, carrying its saved facts as `raw` — so today's
    scorer, target and focus can judge it exactly as they judge a fresh item."""
    from models import Opportunity  # noqa: PLC0415
    dl = None
    if d.get("deadline"):
        try:
            dl = date.fromisoformat(str(d["deadline"])[:10])
        except ValueError:
            pass
    return Opportunity(title=d.get("title", ""), url=d.get("url", ""), source=d.get("source", ""),
                       description=d.get("description", "") or "", deadline=dl, tags=list(d.get("tags") or []),
                       native_id=d.get("native_id"), raw=dict(d.get("facts") or d.get("raw") or {}))


def rescore(d: dict) -> int:
    """Score an item with TODAY's rules. History stores the score from the day it was found — before
    the off-domain penalty, the domain credit and the standing target existed — which is why the list
    once showed "Software Sales Internship" and "SEO Trainee" at 10/10. He picked one."""
    from filters import target  # noqa: PLC0415
    from filters.scorer import score_item  # noqa: PLC0415
    o = _as_opp(d)
    return max(0, min(10, score_item(o) + target.adjustment(o)))


def eligibility_of(d: dict, full: dict | None = None, cand=None):
    """The eligibility verdict: from the full posting when we have it, else from what history stored."""
    from .eligibility import assess, from_description, location_rules, title_rules, _verdict  # noqa: PLC0415
    cand = cand or _candidate()
    senior = title_rules(d.get("title", ""), cand)
    if full and full.get("description"):
        v = assess(cand, full.get("description", ""), full.get("location", ""),
                   full.get("remote"), full.get("unstop"))
        return _verdict(senior + list(v.reasons)) if senior else v
    v = from_description(d.get("description", "") or "", cand)
    facts = d.get("facts") or {}
    loc = facts.get("location") or ", ".join(facts.get("cities") or [])
    extra = location_rules(loc or "Online", facts.get("remote"), cand) if (loc or facts.get("remote")) else []
    return _verdict(senior + list(v.reasons) + extra) if (senior or extra) else v


def build_job_md(item: dict, full: dict, report: dict | None = None) -> str:
    """job.md — everything known, and honest about what is missing.

    It opens with its own three-second read, because the first question about a job is not "what
    is it" but "can I even apply, and do I fit" — and OPHunter used to rank roles highly that a
    stated rule excluded him from (graduation year, year of study, a country he cannot work in)."""
    from filters import focus, target
    from .eligibility import team_note
    from .fit import BUILT, GAP, LEARNED, skill_evidence

    profile = _profile()
    title = item.get("title", "Untitled")
    src = item.get("source", "?")
    listing_url = item.get("url", "")
    apply_url = full.get("apply_url") or listing_url
    facts = item.get("facts") or {}
    jd_text = full.get("description") or item.get("description", "")
    verdict = eligibility_of(item, full, _candidate(profile))
    rows_fit = skill_evidence(jd_text, profile)
    built = sum(1 for r in rows_fit if r[1] == BUILT)
    learned = sum(1 for r in rows_fit if r[1] == LEARNED)
    team = team_note(full.get("unstop") or {})
    location = full.get("location") or facts.get("location") or ", ".join(facts.get("cities") or [])
    pay = full.get("pay_note") or _pay_line(item)

    L = [f"# {title}", ""]
    # ── the three-second read ──
    L.append(f"> **{verdict.icon} {verdict.label}**")
    for lvl, why in verdict.reasons[:4]:
        L.append(f"> {'⛔' if lvl == 'NO' else '⚠' if lvl == 'CHECK' else '✓'} {why}")
    if rows_fit:
        L.append(f"> **Fit:** {built + learned} of {len(rows_fit)} skills this posting names are backed "
                 f"— {built} you have built with, {learned} you have studied.")
    at = " · ".join(x for x in [location, pay, team] if x)
    if at:
        L.append(f"> {at}")
    L += ["", f"_Pack built {date.today().isoformat()} by Opportunity Hunter. **Nothing here was "
              f"submitted anywhere** — you apply by hand._", ""]

    L += ["## Apply", "",
          f"- **Apply link** — {apply_url or '_none found_'}",
          f"- Listing — {listing_url or '_n/a_'}",
          f"- Source — `{src}`" + (f" · company **{full['company']}**" if full.get("company") else ""),
          ""]

    L += ["## The facts", "", "| | |", "|---|---|"]
    rows = [
        ("Kind", focus.kind_of(_as_opp(item))),
        ("Location", location),
        ("Other locations", full.get("other_locations")),
        ("Remote", full.get("remote") if full.get("remote") is not None else facts.get("remote")),
        ("Employment type", full.get("employment_type")),
        ("Team", team or full.get("team") or full.get("departments")),
        ("Pay", pay),
        ("Perks", full.get("perks")),
        ("Openings", full.get("openings")),
        ("Deadline", item.get("deadline") or full.get("closes")),
        ("Posted", full.get("posted")),
        ("Tags", item.get("tags")),
    ]
    L += [f"| {k} | {_fmt(v)} |" for k, v in rows]
    L.append("")

    if rows_fit:
        mark = {BUILT: "✓ built", LEARNED: "◐ studied", GAP: "✗ gap"}
        L += ["## Do you fit?", "",
              "Every skill this posting names, and how you can back it. **Built** means code that "
              "uses it; **studied** means a certificate or course but no project — say so honestly in "
              "an interview rather than overclaiming.", "",
              "| The job asks for | You | Your evidence |", "|---|---|---|"]
        L += [f"| {t} | {mark[lvl]} | {ev or '—'} |" for t, lvl, ev in rows_fit]
        L.append("")

    L += ["## Why OPHunter surfaced this", "",
          f"- Score today **{rescore(item)}/10** (re-scored with the current rules)"]
    if item.get("ai_summary"):
        L.append(f"- {item['ai_summary']}")
    for why, delta in target.reasons(_Obj(item)):
        L.append(f"- {'+' if delta > 0 else ''}{delta} — {why}")
    dims = item.get("dimensions") or {}
    if dims:
        L.append("- Dimensions — " + ", ".join(f"{k} {v}" for k, v in dims.items()
                                               if isinstance(v, int)))
    L.append("")

    L += ["## Full description", ""]
    if full.get("description"):
        L += [f"_Straight from the employer's own API — this is the complete posting._", "",
              full["description"], ""]
    else:
        L += ["_The employer's API did not give us the full text, so this is what the listing "
              "carried. **Open the apply link and read the real posting before you write "
              "anything.**_", "", item.get("description") or "_no description_", ""]

    gaps = sorted(set((report or {}).get("gaps") or []) | set((report or {}).get("unverified_terms") or []))
    L += ["## Gaps you could close", ""]
    if gaps:
        L += ["This job asks for these, and your profile has no evidence of them. **They are not on "
              "your resume** — putting them there is what gets caught in the first interview "
              "question. Learn one, build something small with it, and it becomes true.", "",
              *[f"- `{g}`" for g in gaps], ""]
    else:
        L += ["_None found — every skill this listing names is backed by your profile._", ""]

    L += ["## Before you apply — verify these yourself", "",
          "OPHunter reads feeds and APIs. It cannot tell you whether a listing is real, current, "
          "or worth your time. These are the checks it genuinely cannot do for you:", "",
          "- [ ] The apply link opens a real application form on the employer's own domain",
          "- [ ] The role is still open (aggregators keep dead listings for weeks)",
          "- [ ] You meet the hard requirements — degree year, location, work authorisation",
          "- [ ] The pay above matches what the posting actually says",
          "- [ ] The company is real: website, LinkedIn, employees, funding",
          "- [ ] **No application fee, no deposit, no 'training charge'** — a real employer never asks",
          "- [ ] Every line of the resume in this folder is true and you can defend it in an interview",
          "",
          "## Notes", "", "_Your notes — what you sent, who you spoke to, what they said._", ""]
    return "\n".join(L)


def _pay_line(item: dict) -> str:
    from filters import target
    pay = target.pay_of(_Obj(item))
    return f"about Rs {pay:,}/month" if pay else ""


class _Obj:
    """Adapts a history dict to the attribute access filters/ expect."""

    def __init__(self, d: dict):
        self._d = d
        self.title = d.get("title", "")
        self.description = d.get("description", "") or d.get("ai_summary", "")
        self.source = d.get("source", "")
        self.tags = d.get("tags") or []
        # History items carry their pay / place / remote in `facts` (raw itself is never saved).
        self.raw = d.get("raw") or d.get("facts") or {}
        self.score = d.get("score", 0)
        self.ai_score = d.get("ai_score", -1)
        dl = d.get("deadline")
        self.deadline = None
        if dl:
            try:
                self.deadline = date.fromisoformat(str(dl)[:10])
            except ValueError:
                pass


# Text damage that must never reach an employer. Found the hard way: career_profile.json was
# rebuilt from a PDF, and PDF extraction had mapped the arrow glyph to the "fi" ligature — so a
# real generated resume read "TaskFlow v1.0 fi v8.5" and "blue fi amber fi red deadline urgency".
# The generator was working perfectly and faithfully reproducing corrupt input.
#
# A resume is the one document where a silent defect is most expensive, so this shouts instead.
_CORRUPTION = [
    (re.compile(r"�"), "replacement characters (U+FFFD) — text decoded with the wrong codec"),
    (re.compile(r"ﬀ|ﬁ|ﬂ|ﬃ|ﬄ"), "ligature glyphs left in by a PDF extractor"),
    (re.compile(r"â€|Ã¢|Ã©|Ã¼|â€™|Ã"), "mojibake — UTF-8 bytes read as Latin-1"),
    (re.compile(r"&(nbsp|amp|lt|gt|quot|#\d+);"), "raw HTML entities"),
    (re.compile(r"<[a-z/][^>]*>", re.I), "raw HTML tags"),
    (re.compile(r"\bTODO\b|\bFIXME\b|\blorem ipsum\b", re.I), "placeholder text"),
]

def _lost_arrow(word: str) -> bool:
    """Is this word a mangled arrow rather than an ordinary word containing 'fi'?

    A word list was the first attempt and it was the wrong shape — "Pacific" and "file" are
    perfectly good words, and the list would have to grow forever. The damage has a much
    narrower signature than "contains fi":
      * the word IS "fi"                    -> "TaskFlow v1.0 fi v8.5"
      * it contains "fi" more than once     -> "bluefiamberfired" (blue/amber/red)
      * "fi" sits against a digit           -> "v1.0fiv8.5"
    Every real English word fails all three."""
    w = word.lower()
    if w == "fi":
        return True
    if w.count("fi") > 1:
        return True
    return bool(re.search(r"\dfi|fi\d", w))


def corruption_warnings(text: str) -> list[str]:
    """Human-readable problems found in generated resume text. Empty list = clean."""
    out = []
    for pat, why in _CORRUPTION:
        hits = {m.group(0).strip()[:24] for m in pat.finditer(text)}
        if hits:
            out.append(f"{why} — e.g. {', '.join(sorted(hits)[:4])}")

    # The lost-arrow check runs per WORD, not per fragment: "certifications" contains "fi" and
    # is perfectly fine, so testing the matched substring alone cries wolf on half a resume.
    bad = {w for w in re.findall(r"\b[\w.+-]*fi[\w.+-]*\b", text, re.I) if _lost_arrow(w)}
    if bad:
        out.append("a stray 'fi' that is probably a lost arrow — e.g. "
                   + ", ".join(sorted(bad)[:4]))
    return out


def build_resume(item: dict, full: dict, company: str = "") -> tuple[str, dict]:
    """(resume.md, report) — this job's resume from career_profile.json, every claim verified.

    The report comes back to build() so job.md can list the job's skills you do not have yet as
    GAPS YOU COULD CLOSE. That is where those terms belong. The first version of this pipeline put
    three of them on the resume as skills you already had."""
    from .generate import generate_resume_ex

    jd = "\n".join(x for x in [full.get("description", ""), item.get("description", "")] if x)
    try:
        profile = json.loads((config.DATA_DIR / "career_profile.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ("# Resume\n\n_No `data/career_profile.json` yet._\n\n"
                "Build it first (a rebuild now keeps your curated layers):\n\n"
                "    py -m resume.profile --github Mohith535 --certs \"E:/certificates\" "
                "--linkedin \"E:/linkedin-agent/data/linkedin-export\"\n"), {}

    body, report = generate_resume_ex(profile, jd, role=item.get("title", ""), company=company)

    problems = corruption_warnings(body)
    placeholders = len(re.findall(r"\[add [^\]]+\]", body))
    notes = [f"Tailored for: {item.get('title','')} — {date.today().isoformat()}",
             "Every claim was checked against data/career_profile.json before it got here."]
    if report.get("removed"):
        notes.append(f"VERIFIER removed {len(report['removed'])} model-written sentence(s) your "
                     f"profile could not back:")
        notes += [f"     - {s[:110]}" for s in report["removed"]]
    if report.get("banned"):
        notes.append("VOICE removed sentences using: " + ", ".join(report["banned"]))
    if report.get("drift"):
        notes.append("facts.yml has moved on from your profile — update it:")
        notes += [f"     - {d}" for d in report["drift"]]
    if report.get("lint"):
        notes.append("Voice notes:")
        notes += [f"     - {d}" for d in report["lint"]]
    if placeholders:
        notes.append(f"{placeholders} [add ...] placeholder(s) to fill in — a real number beats a "
                     f"vague claim, and an invented one ends the interview.")
    if problems:
        notes.append("!! TEXT PROBLEMS FOUND — fix these in data/career_profile.json before "
                     "sending, they came in with the source data:")
        notes += [f"     - {p}" for p in problems]
    notes.append("Delete this comment before you send it.")
    head = "<!--\n" + "\n".join(f"  {n}" for n in notes) + "\n-->\n\n"

    if report.get("removed"):
        print(f"\n  verifier removed {len(report['removed'])} unbacked sentence(s): "
              f"{', '.join(report.get('unverified_terms') or []) or 'numbers'}")
    if report.get("drift"):
        print(f"  facts.yml drift: {len(report['drift'])} item(s) — see resume.md header")
    if problems:
        print("\n  !! resume.md has text problems inherited from career_profile.json:")
        for p in problems:
            print(f"       - {p}")
    if placeholders:
        print(f"  {placeholders} [add ...] placeholder(s) in resume.md — fill them in, never invent them.")
    return head + body, report


def build_resume_md(item: dict, full: dict) -> str:
    """Backwards-compatible: only the Markdown."""
    return build_resume(item, full)[0]


def build(ref: str) -> Path | None:
    item = resolve(ref)
    if not item:
        print(f"No opportunity matching {ref!r}. Try `py -m resume.apply --list`.")
        return None

    full = fetch_full_jd(item)
    from .render import short_company  # noqa: PLC0415
    company = short_company(company_of(item, full))   # "DJSCE", not the organiser's full legal name
    title = item.get("title", "")
    prefix = "" if company and company.lower() in title.lower() else company   # no "microsoft-microsoft-…"
    out = APPLICATIONS_DIR / _slug(prefix, title, date.today().isoformat())
    out.mkdir(parents=True, exist_ok=True)

    resume_md, report = build_resume(item, full, company)
    (out / "job.md").write_text(build_job_md(item, full, report), encoding="utf-8")
    md_path = out / "resume.md"
    md_path.write_text(resume_md, encoding="utf-8")

    got = "full posting from the employer API" if full.get("description") else "listing text only"
    print(f"\n  {item.get('title','')[:70]}")
    print(f"  {out}")
    print(f"    job.md     {got}")
    print(f"    resume.md  tailored from career_profile.json")

    # The files a recruiter actually receives. The PDF exists only if reading it back proves the text
    # is really in it — the check his hand-made PDF would have failed.
    try:
        from .render import write  # noqa: PLC0415
        r = write(md_path, company=company)
        if r["pdf"]:
            print(f"    {r['pdf'].name:<34} {r['pages']} page(s), text layer verified"
                  + (f", {r['page1_projects']} projects on page 1" if r["page1_projects"] else ""))
        else:
            print("    PDF NOT WRITTEN — failed the read-back gate: " + "; ".join(r["problems"][:3]))
        if r["docx"]:
            print(f"    {r['docx'].name:<34} read back clean")
    except ImportError as e:
        print(f"    (PDF/DOCX skipped — install the renderer: pip install typst python-docx pymupdf; {e.name})")
    if report.get("role_section"):
        print(f"    + 'What I would bring to {company or 'this role'}' ({len(report['role_section'])} verified bullets)")

    print(f"\n  Read job.md first — the verification checklist at the bottom is the part "
          f"OPHunter cannot do for you.\n")
    return out


def company_of(item: dict, full: dict) -> str:
    """The employer's name, for the file name and the role section. ATS APIs give it directly;
    otherwise it is read from the title, which the sources write as "Role — Company" (ATS) or
    "Company — Role" (the internships feed) — the side without a job word is the company."""
    c = full.get("company") or (item.get("raw") or {}).get("company") or ""
    if c:
        return c
    parts = [p.strip() for p in (item.get("title") or "").split(" — ") if p.strip()]
    if len(parts) == 2:
        job = re.compile(r"intern|engineer|developer|analyst|scientist|associate|trainee|fellow|"
                         r"manager|designer|research|role|position|graduate", re.I)
        others = [p for p in parts if not job.search(p)]
        if len(others) == 1:
            return others[0]
    return ""


def _arg_int(args: list[str], flag: str, default: int) -> int:
    try:
        return int(args[args.index(flag) + 1])
    except (ValueError, IndexError):
        return default


def show_list(show_all: bool = False, limit: int = 25) -> int:
    rows = ranked_items()
    if not rows:
        print("No open opportunities in history — run `py main.py --now` first.")
        return 1
    from filters import focus, target  # noqa: PLC0415
    shown = [r for r in rows if show_all or r[3].level != "NO"]
    hidden = len(rows) - len(shown)
    kinds = ", ".join(focus.active())
    print(f"\n{len(shown)} open opportunities, scored with today's rules and your target"
          + (f" — showing {limit}" if len(shown) > limit else "") + ":")
    zone = None
    for n, i, s, v, off in shown[:limit]:
        if kinds and off != zone:
            zone = off
            print("\n  ⭐ ALSO WORTH YOUR TIME\n" if off else f"\n  🎯 YOUR FOCUS: {kinds}\n")
        o = _as_opp(i)
        # A warning beats a compliment: for ⚠/⛔ say what to check; otherwise say why it ranks here.
        warn = next((w for lvl, w in v.reasons if lvl in ("NO", "CHECK")), "")
        why = warn or target.note(o) or (v.reasons[0][1] if v.reasons else "")
        print(f"  {n:>3}. [{s:>2}/10] {v.icon} {(i.get('title') or '')[:62]}")
        print(f"       {focus.kind_of(o):10} {i.get('source', ''):11} {i.get('deadline') or 'no deadline':11}"
              + (f"  {why[:72]}" if why else ""))
    print("\n  ✅ eligible  ❔ rules not stated  ⚠ check yourself  ⛔ not eligible")
    if hidden and not show_all:
        print(f"  {hidden} not-eligible job(s) hidden — `--list --all` shows them. Numbers stay the same.")
    print("  py -m resume.apply <number>\n")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if args[0] == "--list":
        return show_list(show_all="--all" in args, limit=_arg_int(args, "--top", 25))
    return 0 if build(args[0]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
