"""
Verifier (Phase B+) — independent liveness check for AGGREGATOR opportunities.

Aggregators (e.g. the SimplifyJobs internships feed) are high-volume but carry
stale/dead listings. Original sources (Devpost, company pages, the curated
watchlist) are authoritative and skip this. For aggregator items we hit the
application URL ourselves and DROP only the ones that are clearly dead (404/410/
gone). Anything that's alive — or merely uncertain (timeout, bot-block 403,
network error) — is KEPT, so we never throw away a real opportunity on a flaky
check. Checks run concurrently and are time-boxed; the whole thing is best-effort
and never raises.

This is the cheap, reliable verification layer. (A deeper LLM "is this real and
still open, what's the true deadline" pass over the original page is a future add.)
"""

from concurrent.futures import ThreadPoolExecutor

import requests

import config
from util import log

# Sources whose items get independently verified. Everything else is trusted.
AGGREGATOR_SOURCES = {"internships"}

_DEAD_CODES = {404, 410}
_TIMEOUT = 8
_HEADERS = {"User-Agent": config.USER_AGENT}


def _is_alive(url: str):
    """True = reachable, False = clearly dead (404/410), None = uncertain (keep)."""
    if not url:
        return None
    try:
        r = requests.head(url, headers=_HEADERS, timeout=_TIMEOUT, allow_redirects=True)
        if r.status_code in _DEAD_CODES:
            return False
        if r.status_code in (405, 403, 501):       # HEAD not allowed/blocked → try GET
            r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT,
                             allow_redirects=True, stream=True)
        return False if r.status_code in _DEAD_CODES else True
    except requests.RequestException:
        return None                                 # uncertain → keep


def filter_dead(items: list) -> list:
    """Drop aggregator-sourced items whose application URL is clearly dead.
    Non-aggregator items pass straight through untouched."""
    targets = [it for it in items if it.source in AGGREGATOR_SOURCES and it.url]
    if not targets:
        return items

    with ThreadPoolExecutor(max_workers=min(10, len(targets))) as ex:
        results = list(ex.map(lambda it: _is_alive(it.url), targets))

    dead = {id(it) for it, alive in zip(targets, results) if alive is False}
    if dead:
        log(f"[verifier] dropped {len(dead)}/{len(targets)} dead aggregator link(s).")
    return [it for it in items if id(it) not in dead]


if __name__ == "__main__":
    from models import Opportunity

    samples = [
        Opportunity("alive", "https://example.com", "internships", "x"),
        Opportunity("dead", "https://httpstat.us/404", "internships", "x"),
        Opportunity("trusted (not checked)", "https://httpstat.us/404", "devpost", "x"),
    ]
    kept = filter_dead(samples)
    print("kept:", [o.title for o in kept])
