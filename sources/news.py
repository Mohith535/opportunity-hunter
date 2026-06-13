"""
News sources (CLAUDE.md §5.3): Hacker News + Reddit.

Hacker News: fetch the top story IDs, then pull each item's detail concurrently
(ThreadPoolExecutor) for speed. Only `story` items with titles are kept; the
relevance filter then drops everything that isn't AI/CS by keyword. Stories with
no external URL fall back to the HN permalink.

Reddit: the unauthenticated JSON endpoint is rate-limited and frequently 403s
from datacenter IPs (e.g. GitHub Actions runners), so each subreddit tries JSON
first and falls back to the public `.rss` feed. A subreddit blocked on both paths
is skipped (returns nothing) rather than crashing the run. Post IDs are normalized
to Reddit's base36 id so JSON and RSS produce the same dedup key.
"""

import concurrent.futures
import re
import time

import feedparser
import requests

import config
from models import Opportunity

TOP_STORIES = "https://hacker-news.firebaseio.com/v0/topstories.json"
ITEM = "https://hacker-news.firebaseio.com/v0/item/{}.json"
PERMALINK = "https://news.ycombinator.com/item?id={}"
TOP_N = 30


def _get_item(item_id: int) -> dict | None:
    try:
        resp = requests.get(ITEM.format(item_id), timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None  # one bad item shouldn't sink the batch


def fetch_hackernews() -> list[Opportunity]:
    resp = requests.get(TOP_STORIES, timeout=config.REQUEST_TIMEOUT)
    resp.raise_for_status()
    ids = resp.json()[:TOP_N]

    items: list[Opportunity] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        for data in ex.map(_get_item, ids):
            if not data or data.get("type") != "story" or not data.get("title"):
                continue
            hid = data["id"]
            items.append(
                Opportunity(
                    title=data["title"],
                    url=data.get("url") or PERMALINK.format(hid),
                    source="hackernews",
                    description="",  # HN stories carry no body; title drives matching
                    native_id=str(hid),
                    tags=["news"],
                    raw={"hn_score": data.get("score", 0), "by": data.get("by", "")},
                )
            )
    return items


# Convenience alias for the registry.
fetch = fetch_hackernews


# ─── REDDIT ──────────────────────────────────────────────────────────
REDDIT_SUBS = ["MachineLearning", "developersIndia"]
REDDIT_LIMIT = 10
# Truthful topic hint injected into the description so the curated subreddit's
# theme is matchable by the keyword filter (e.g. r/MachineLearning -> "machine
# learning"). developersIndia posts then surface via opportunity keywords in the
# title (internship/python/AI/...), which is the behaviour we want.
_SUB_TOPIC = {
    "MachineLearning": "machine learning research",
    "developersIndia": "india software developer",
}
_REDDIT_HEADERS = {"User-Agent": config.USER_AGENT}


def _post_id(url: str) -> str | None:
    """Extract Reddit's base36 post id from a permalink/URL so the JSON and RSS
    paths dedup to the same key."""
    m = re.search(r"/comments/([a-z0-9]+)", url or "")
    return m.group(1) if m else None


def _reddit_item(sub: str, title: str, url: str, native_id: str | None, score=0) -> Opportunity:
    return Opportunity(
        title=title,
        url=url,
        source="reddit",
        description=f"r/{sub} | {_SUB_TOPIC.get(sub, '')} | score {score}",
        native_id=native_id or url,
        tags=["news", f"r/{sub}"],
        raw={"subreddit": sub, "score": score},
    )


def _reddit_json(sub: str) -> list[Opportunity]:
    url = f"https://www.reddit.com/r/{sub}/top.json?limit={REDDIT_LIMIT}&t=day"
    resp = requests.get(url, headers=_REDDIT_HEADERS, timeout=config.REQUEST_TIMEOUT)
    resp.raise_for_status()
    out = []
    for child in resp.json().get("data", {}).get("children", []):
        d = child.get("data", {})
        out.append(_reddit_item(
            sub,
            title=d.get("title", ""),
            url="https://www.reddit.com" + d.get("permalink", ""),
            native_id=d.get("id"),
            score=d.get("score", 0),
        ))
    return out


def _reddit_rss(sub: str) -> list[Opportunity]:
    url = f"https://www.reddit.com/r/{sub}/top/.rss?t=day"
    resp = requests.get(url, headers=_REDDIT_HEADERS, timeout=config.REQUEST_TIMEOUT)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    out = []
    for e in feed.entries[:REDDIT_LIMIT]:
        link = e.get("link", "")
        out.append(_reddit_item(
            sub,
            title=e.get("title", ""),
            url=link,
            native_id=_post_id(link) or _post_id(e.get("id", "")) or e.get("id"),
        ))
    return out


def fetch_reddit() -> list[Opportunity]:
    """Top posts from the curated subreddits.

    RSS first: the unauth JSON endpoint reliably 403s now, so trying it first
    just wastes a request and helps throttle the RSS fallback. JSON is kept as a
    secondary path in case it works from some IPs / is restored. A subreddit that
    fails both is skipped — the run continues with whatever else succeeded.
    """
    out: list[Opportunity] = []
    for i, sub in enumerate(REDDIT_SUBS):
        if i:
            time.sleep(3.0)  # be polite — Reddit throttles rapid sequential hits
        try:
            out += _reddit_rss(sub)
        except requests.RequestException:
            try:  # RSS blocked -> try JSON (usually 403, occasionally works)
                out += _reddit_json(sub)
            except requests.RequestException:
                pass  # both paths failed for this sub; skip, keep the run alive
    return out


if __name__ == "__main__":
    results = fetch_hackernews()
    print(f"Fetched {len(results)} HN stories (pre-filter)\n")
    for o in results[:15]:
        print(f"• {o.title}\n    {o.url}")
