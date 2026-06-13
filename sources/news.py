"""
News sources (CLAUDE.md §5.3).

Phase: Hacker News now; Reddit will be added here later as fetch_reddit().

Hacker News: fetch the top story IDs, then pull each item's detail concurrently
(ThreadPoolExecutor) for speed. Only `story` items with titles are kept; the
relevance filter then drops everything that isn't AI/CS by keyword. Stories with
no external URL fall back to the HN permalink.
"""

import concurrent.futures

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


if __name__ == "__main__":
    results = fetch_hackernews()
    print(f"Fetched {len(results)} HN stories (pre-filter)\n")
    for o in results[:15]:
        print(f"• {o.title}\n    {o.url}")
