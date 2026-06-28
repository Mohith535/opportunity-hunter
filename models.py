"""
The normalized data model every source produces and every downstream module
consumes. This is the contract that keeps sources, filters, scorer, dedup, the
brief, and TaskFlow all speaking the same language.

In Phase 2, LLM scoring just writes to `ai_score` / `ai_summary` on this same
object — no source or consumer needs to change.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Optional
from urllib.parse import urlsplit, urlunsplit


def canonicalize_url(url: str) -> str:
    """Strip tracking params, fragments, trailing slashes, and normalize the
    scheme/host so the same opportunity hashes to the same key across runs."""
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
        scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
        netloc = parts.netloc.lower()
        path = parts.path.rstrip("/")
        return urlunsplit((scheme, netloc, path, "", ""))  # drop query + fragment
    except Exception:
        return url.strip()


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


@dataclass
class Opportunity:
    """One opportunity, normalized across all sources."""

    title: str
    url: str
    source: str                      # e.g. "arxiv", "github", "devpost"
    description: str = ""
    deadline: Optional[date] = None
    tags: list[str] = field(default_factory=list)
    native_id: Optional[str] = None  # stable source id (arxiv id, repo, HN id...)

    # Scores
    score: int = 0                   # rule-based score (filters/scorer.py)
    ai_score: int = -1               # Phase 2: LLM score 0-10, -1 = not computed
    ai_summary: str = ""             # Phase 2: one-line "why this matters for Mohith"
    action_plan: list[str] = field(default_factory=list)  # Phase 2: suggested steps
    dimensions: dict = field(default_factory=dict)        # Phase 2: per-dimension scores

    raw: dict = field(default_factory=dict)  # source-specific extras

    def dedup_key(self) -> str:
        """Stable identity. Prefer the source-native id; fall back to a hash of
        the normalized title + canonical URL."""
        if self.native_id:
            base = f"{self.source}:{self.native_id}"
        else:
            base = f"{_normalize_title(self.title)}|{canonicalize_url(self.url)}"
        return hashlib.md5(base.encode("utf-8")).hexdigest()[:12]

    @property
    def text(self) -> str:
        """Lowercased title + description, for keyword matching."""
        return f"{self.title} {self.description}".lower()

    def to_dict(self) -> dict:
        """JSON-serializable view (for history/logging). Drops `raw`."""
        d = asdict(self)
        if isinstance(self.deadline, (date, datetime)):
            d["deadline"] = self.deadline.isoformat()
        d.pop("raw", None)
        return d
