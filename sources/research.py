"""
ArXiv source — latest AI/ML/NLP papers.

Chosen as the first source because the ArXiv API is free, auth-free, and very
reliable, so the whole pipeline (filter -> score -> brief -> notify -> TaskFlow)
can be proven end-to-end before we touch any fragile scrapers.
"""

import re

import feedparser

from models import Opportunity

# cs.AI (AI) + cs.LG (machine learning) + cs.CL (computation & language / NLP)
ARXIV_URL = (
    "http://export.arxiv.org/api/query"
    "?search_query=cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CL"
    "&sortBy=submittedDate&sortOrder=descending&max_results=10"
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _arxiv_id(entry_id: str) -> str:
    """'http://arxiv.org/abs/2506.12345v2' -> '2506.12345' (version stripped so a
    new revision of the same paper doesn't re-notify)."""
    m = re.search(r"abs/(.+?)(v\d+)?$", entry_id.strip())
    return m.group(1) if m else entry_id.strip()


def fetch() -> list[Opportunity]:
    """Return the latest AI papers as normalized Opportunity objects.

    Raises on network/parse failure — the caller (util.safe_fetch) handles it so
    one bad source never crashes the run.
    """
    feed = feedparser.parse(ARXIV_URL)

    items: list[Opportunity] = []
    for e in feed.entries:
        authors = ", ".join(a.get("name", "") for a in e.get("authors", []))
        items.append(
            Opportunity(
                title=_clean(e.get("title", "")),
                url=e.get("link", ""),
                source="arxiv",
                description=_clean(e.get("summary", "")),
                native_id=_arxiv_id(e.get("id", "")),
                tags=["research"],
                raw={"authors": authors, "published": e.get("published", "")},
            )
        )
    return items


if __name__ == "__main__":
    # Quick standalone test:  python -m sources.research
    results = fetch()
    print(f"Fetched {len(results)} ArXiv papers\n")
    for o in results[:5]:
        print(f"• {o.title}")
        print(f"    {o.url}  [id={o.native_id}]")
        print(f"    {o.description[:120]}...\n")
