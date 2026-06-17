"""
GitHub Trending source (CLAUDE.md §5.2).

Recently-created, highly-starred repos in AI/ML topics. Auth-free (60 req/hr is
plenty for two queries a day). Topics are folded into the description with
hyphens turned into spaces ("machine-learning" -> "machine learning") so the
word-boundary relevance filter can actually match them.
"""

from datetime import date, timedelta

import requests

import config
from models import Opportunity

API = "https://api.github.com/search/repositories"
HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": config.USER_AGENT,
}
# Authenticate when a token is available (GITHUB_TOKEN). Unauthenticated search
# is 60 req/hr per IP — which 403s from shared datacenter IPs like GitHub
# Actions runners; a token raises it to ~30 req/min, far above our few calls.
if config.GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
# One query per topic — GitHub search rejects (422) an `OR` combined with the
# `created:` qualifier, so we keep each topic separate and dedup in fetch().
QUERIES = [
    "topic:machine-learning",
    "topic:llm",
    "topic:deep-learning",
]
WINDOW_DAYS = 30
PER_PAGE = 4


def _since() -> str:
    return (date.today() - timedelta(days=WINDOW_DAYS)).isoformat()


def _search(query: str) -> list[Opportunity]:
    params = {
        "q": f"{query} created:>{_since()}",
        "sort": "stars",
        "order": "desc",
        "per_page": PER_PAGE,
    }
    resp = requests.get(API, params=params, headers=HEADERS, timeout=config.REQUEST_TIMEOUT)
    resp.raise_for_status()

    items: list[Opportunity] = []
    for repo in resp.json().get("items", []):
        topics = repo.get("topics", []) or []
        desc = (repo.get("description") or "").strip()
        stars = repo.get("stargazers_count", 0)
        topics_text = ", ".join(t.replace("-", " ") for t in topics)
        full_desc = f"{desc} (topics: {topics_text})" if topics_text else desc
        items.append(
            Opportunity(
                title=f"{repo['full_name']} — ★{stars:,}",
                url=repo.get("html_url", ""),
                source="github",
                description=full_desc,
                native_id=repo["full_name"],   # owner/repo: stable id
                tags=["github", "learning"],
                raw={"stars": stars, "topics": topics},
            )
        )
    return items


def fetch() -> list[Opportunity]:
    """Trending AI/ML repos, deduped across the topic queries."""
    seen, out = set(), []
    for q in QUERIES:
        for it in _search(q):
            if it.native_id not in seen:
                seen.add(it.native_id)
                out.append(it)
    return out


if __name__ == "__main__":
    results = fetch()
    print(f"Fetched {len(results)} GitHub repos\n")
    for o in results:
        print(f"• {o.title}")
        print(f"    {o.url}")
        print(f"    {o.description[:110]}\n")
