"""
Remote jobs open to India — Himalayas (22 Oct 2026).

The remote boards that state WHERE a candidate may be (the field the StackAdapt card lacked). Measured
live on 22 Oct: Himalayas had 121 entry-level software roles searchable for India, ~20 real tech roles a
page, each with `locationRestrictions` (countries a candidate must be in) — which the eligibility rules
read exactly. Remotive was measured too and left out: its "intern" search returned 10 jobs, mostly
assistants, sales and copywriters, under a 4-calls-a-day limit.

Himalayas' terms (himalayas.app/api, read 22 Oct): automation and AI agents are an intended use; jobs are
shown only in an app he operates, never passed to other boards; the apply link is used unchanged and
Himalayas is named as the source. Hence `url` = its applicationLink and "via Himalayas" on every item.
No key: one shared public allowance, data refreshed daily — four calls a run.
"""

from __future__ import annotations

import html
import re

import requests

import config
from models import Opportunity
from util import log

SEARCH = "https://himalayas.app/jobs/api/search"
QUERIES = [{"employment_type": "Intern", "country": "IN"},
           {"seniority": "Entry-level", "country": "IN", "q": "software"}]
PAGES = 2
_TECH = re.compile(r"engineer|developer|software|data|machine learning|\bai\b|\bml\b|back-?end|front-?end|"
                   r"full.?stack|devops|cloud|python|research|sde\b|programm", re.I)
_NOT = re.compile(r"co-?founder|\bcmo\b|\bceo\b|sales|marketing|recruit|account exec|business develop", re.I)


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def place(job: dict) -> str:
    """Where a candidate may be: "Remote (worldwide)" when the job states no restriction, else the
    countries — the eligibility rules read "Remote — Canada, Germany" as remote only from inside them."""
    where = [str(c) for c in job.get("locationRestrictions") or [] if str(c).strip()]
    return "Remote (worldwide)" if not where else "Remote — " + ", ".join(where[:6])


def to_opportunity(job: dict) -> Opportunity | None:
    title = (job.get("title") or "").strip()
    if not title or not _TECH.search(title) or _NOT.search(title):
        return None
    m = re.match(r"https://himalayas\.app/companies/([^/]+)/jobs/([^/?#]+)", job.get("guid") or "")
    kind = "internship" if job.get("employmentType") == "Intern" or re.search(r"\bintern", title, re.I) else "job"
    pay = ""
    if job.get("maxSalary"):
        pay = f" | pays {job.get('currency') or ''} {job.get('minSalary') or ''}–{job['maxSalary']} ({job.get('salaryPeriod') or 'annual'})"
    loc = place(job)
    return Opportunity(
        title=f"{title} — {job.get('companyName', '')}",
        url=job.get("applicationLink") or job.get("guid") or "",
        source="remote",
        description=(f"{kind} | {job.get('companyName', '')} | {loc} | {job.get('employmentType') or ''}{pay} "
                     f"| via Himalayas | {_text(job.get('excerpt') or job.get('description'))[:500]}"),
        native_id=f"himalayas:{m.group(1)}:{m.group(2)}" if m else (job.get("guid") or title),
        tags=[kind],
        raw={"company": job.get("companyName", ""), "location": loc, "platform": "Himalayas",
             "remote": not job.get("locationRestrictions") or "India" in (job.get("locationRestrictions") or [])},
    )


def fetch() -> list[Opportunity]:
    out, seen = [], set()
    for q in QUERIES:
        for page in range(1, PAGES + 1):
            r = requests.get(SEARCH, params={**q, "page": page},
                             headers={"User-Agent": f"{config.USER_AGENT} (source credited: Himalayas)"},
                             timeout=max(config.REQUEST_TIMEOUT, 30))
            if r.status_code != 200:
                log(f"[remote] Himalayas answered {r.status_code} — skipped")
                break
            jobs = r.json().get("jobs") or []
            for j in jobs:
                o = to_opportunity(j)
                if o and o.url and o.native_id not in seen:
                    seen.add(o.native_id)
                    out.append(o)
            if len(jobs) < 20:
                break
    log(f"[remote] {len(out)} tech roles open to India or worldwide, via Himalayas")
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for o in fetch()[:12]:
        print(f"  {o.title[:70]}\n      {o.raw['location']} | {o.url[:70]}")
