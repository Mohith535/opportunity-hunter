"""
Competitive-programming contests via clist.by API v4.

clist.by aggregates ~200 judges (Codeforces, CodeChef, AtCoder, LeetCode, ...)
but requires a free API key (it 401s without one). Credentials come from the
environment (CLIST_USERNAME + CLIST_API_KEY). If they're missing the source
skips cleanly — it never crashes the run, and the other sources are unaffected.

We keep only the major CP judges and the soonest upcoming contests. The contest
start is the act-by deadline (feeds deadline-urgency scoring); "competitive
programming" is injected into the description so the relevance filter matches.
"""

from datetime import datetime, timezone

import requests

import config
from models import Opportunity
from util import log

CLIST_API = "https://clist.by/api/v4/contest/"
MAX_ITEMS = 20

# clist exposes hundreds of resources; keep the competitive-programming ones.
CP_RESOURCES = {
    "codeforces.com", "codechef.com", "atcoder.jp", "leetcode.com",
    "topcoder.com", "hackerrank.com", "hackerearth.com", "geeksforgeeks.org",
    "naukri.com", "codingcompetitions.withgoogle.com", "facebook.com/hackercup",
}


def _auth_header() -> dict | None:
    if config.CLIST_USERNAME and config.CLIST_API_KEY:
        return {"Authorization": f"ApiKey {config.CLIST_USERNAME}:{config.CLIST_API_KEY}"}
    return None


def _resource_name(c: dict) -> str:
    r = c.get("resource") or c.get("host") or ""
    return r.get("name", "") if isinstance(r, dict) else r


def fetch_clist() -> list[Opportunity]:
    auth = _auth_header()
    if not auth:
        log("[clist] no API key set (CLIST_USERNAME + CLIST_API_KEY) — skipping", level="WARN")
        return []

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    params = {
        "start__gt": now,        # only upcoming contests
        "order_by": "start",     # soonest first
        "limit": 50,
        "format": "json",
    }
    headers = {"User-Agent": config.USER_AGENT, **auth}
    resp = requests.get(CLIST_API, headers=headers, params=params, timeout=config.REQUEST_TIMEOUT)
    resp.raise_for_status()

    items: list[Opportunity] = []
    for c in resp.json().get("objects", []):
        resource = _resource_name(c)
        if resource not in CP_RESOURCES:
            continue
        start = c.get("start", "")
        try:
            deadline = datetime.fromisoformat(start).date() if start else None
        except ValueError:
            deadline = None
        items.append(
            Opportunity(
                title=f"{c.get('event', '')} ({resource})",
                url=c.get("href", ""),
                source="clist",
                description=f"competitive programming contest on {resource}; starts {start}",
                deadline=deadline,
                native_id=str(c.get("id", "")),
                tags=["contest", "competitive programming"],
                raw={"resource": resource, "duration": c.get("duration")},
            )
        )
        if len(items) >= MAX_ITEMS:
            break
    return items


if __name__ == "__main__":
    r = fetch_clist()
    print(f"Fetched {len(r)} contests")
    for o in r[:15]:
        print(f"  • {o.title[:55]:55}  {o.deadline}")
