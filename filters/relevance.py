"""
Relevance filter — keyword match against the developer profile.

Word-boundary matching (not naive substring) so EXCLUDE "sports" doesn't kill
"esports" and "politics" doesn't kill "political-economy of compute". Multi-word
phrases like "machine learning" are matched as a whole.
"""

import re

import config

# Pre-compile one regex per keyword list for speed and correctness.
# \b...\b gives word boundaries; phrases keep their internal spaces.
_INTEREST_RE = [re.compile(r"\b" + re.escape(k.lower()) + r"\b") for k in config.INTERESTS]
_EXCLUDE_RE = [re.compile(r"\b" + re.escape(k.lower()) + r"\b") for k in config.EXCLUDE_KEYWORDS]


def _first_match(text: str, patterns) -> str | None:
    for pat in patterns:
        if pat.search(text):
            return pat.pattern
    return None


def is_relevant(item) -> bool:
    """True if the item matches an INTEREST and no EXCLUDE keyword.

    Logic (per CLAUDE.md §6.1):
      1. lowercased title + description
      2. any interest keyword present -> candidate
      3. any exclude keyword present -> reject
      4. candidate and not rejected -> relevant
    """
    text = item.text
    if _first_match(text, _EXCLUDE_RE):
        return False
    return _first_match(text, _INTEREST_RE) is not None


def matched_interests(item) -> list[str]:
    """Which interests matched — handy for debugging/tuning."""
    text = item.text
    return [pat.pattern for pat in _INTEREST_RE if pat.search(text)]


if __name__ == "__main__":
    from models import Opportunity

    samples = [
        Opportunity("Deep Learning for Computer Vision", "u1", "arxiv",
                    "A study of neural networks."),
        Opportunity("New esports tournament announced", "u2", "news",
                    "Biggest gaming event of the year."),          # esports != sports
        Opportunity("Cooking with AI: smart recipes", "u3", "news",
                    "machine learning in the kitchen"),            # excluded by 'cooking'
        Opportunity("Civil Engineering Internship", "u4", "jobs",
                    "Bridges and roads."),                          # excluded
        Opportunity("Local bakery opens downtown", "u5", "news",
                    "Fresh bread daily."),                          # no interest match
    ]
    for s in samples:
        print(f"relevant={is_relevant(s)!s:<5}  matched={matched_interests(s)}  | {s.title}")
