"""
Scorer — rule-based 1-10 relevance/urgency score (CLAUDE.md §6.2).

Phase 2 will add `ai_score_item()` (LLM scoring). The stub is here now so the
upgrade is "fill in the function", not "refactor everything". The *decision* of
what to do with a score lives in policy.py, not here.
"""

import re
from datetime import date

import config

_INTEREST_RE = [re.compile(r"\b" + re.escape(k.lower()) + r"\b") for k in config.INTERESTS]
_COMPANY_RE = [re.compile(r"\b" + re.escape(k.lower()) + r"\b") for k in config.KNOWN_COMPANIES]
_REMOTE_RE = [re.compile(r"\b" + re.escape(k) + r"\b") for k in ("remote", "online")]
_STUDENT_RE = [re.compile(r"\b" + re.escape(k) + r"\b") for k in ("student", "intern", "internship")]
_MONEY_WORDS = [re.compile(r"\b" + re.escape(k) + r"\b") for k in ("prize", "stipend", "scholarship", "funded", "grant")]
_MONEY_SYMBOLS = ("$", "₹", "€", "£")


def _any(patterns, text: str) -> bool:
    return any(p.search(text) for p in patterns)


def score_item(item) -> int:
    """Return an additive score capped at 10. Higher = more important."""
    score = 0
    title = item.title.lower()
    desc = item.description.lower()
    text = item.text

    if _any(_INTEREST_RE, title):
        score += 3
    if _any(_INTEREST_RE, desc):
        score += 2

    # Deadline urgency (only sources that actually carry a deadline benefit).
    if item.deadline:
        days_left = (item.deadline - date.today()).days
        if 0 <= days_left <= 7:
            score += 3
        elif days_left <= 30:
            score += 1

    if _any(_REMOTE_RE, text):
        score += 2
    if _any(_STUDENT_RE, text):
        score += 1
    if _any(_COMPANY_RE, text):
        score += 2
    if _any(_MONEY_WORDS, text) or any(sym in text for sym in _MONEY_SYMBOLS):
        score += 1

    return min(score, 10)


# ─── PHASE 2 — LLM scoring ───────────────────────────────────────────
def ai_score_item(item) -> int:
    """Intelligently (re)score a single item via Gemini, in place.

    Returns the new ai_score, or -1 if LLM scoring was unavailable (no key,
    quota, SDK missing) — in which case policy.effective_score() keeps using the
    rule-based score. For batch scoring (the efficient path the pipeline uses)
    call filters.llm_scorer.score_items() directly.
    """
    from filters import llm_scorer
    from user_profile import load_profile

    llm_scorer.score_items([item], load_profile())
    return item.ai_score


if __name__ == "__main__":
    from datetime import timedelta

    from models import Opportunity

    samples = [
        Opportunity("Google Summer of Code 2026", "u", "devpost",
                    "Open source internship, remote, stipend provided for students.",
                    deadline=date.today() + timedelta(days=5)),
        Opportunity("Deep Learning paper on transformers", "u", "arxiv",
                    "A study of attention in machine learning."),
        Opportunity("Random local news", "u", "news", "nothing relevant here"),
    ]
    for s in samples:
        print(f"score={score_item(s):>2}  | {s.title}")
