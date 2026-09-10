"""Explainable ranking — say WHY an opportunity scored what it did.

The LLM scorer already returns six dimensions per item (career / interest / prestige / deadline /
skill / time) and we recompute the final 0-10 from them using config.SCORE_WEIGHTS. Until now those
dimensions were computed, stored, and never shown. This module turns them into one honest line.

Honesty rule: an item that was never LLM-scored has no dimensions, so we return "" rather than
inventing a rationale. A missing explanation is better than a made-up one.
"""

from __future__ import annotations

import config

LABELS = {
    "career": "career fit",
    "interest": "interest match",
    "prestige": "prestige",
    "deadline": "urgency",
    "skill": "skill growth",
    "time": "effort-to-payoff",
}

STRONG, WEAK = 7, 4


def dimensions_of(item) -> dict:
    """The six real dimensions as numbers. Ignores the non-numeric extras we stash alongside
    them (eligible / elig_note / regret)."""
    dims = getattr(item, "dimensions", None) or {}
    return {k: dims[k] for k in config.SCORE_WEIGHTS
            if isinstance(dims.get(k), (int, float))}


def explain(item) -> str:
    """One line: what drove the score up, and what held it back. '' if it was never LLM-scored."""
    vals = dimensions_of(item)
    if not vals:
        return ""

    # A dimension matters as much as its weight says it does, so rank by contribution.
    ranked = sorted(vals.items(), key=lambda kv: -kv[1] * config.SCORE_WEIGHTS[kv[0]])
    strong = [LABELS[k] for k, v in ranked if v >= STRONG][:2]
    # The weakness worth naming is the one that COSTS the most, not the lowest raw number:
    # career 3 (weight .35) hurts far more than prestige 2 (weight .15).
    cost = [(k, config.SCORE_WEIGHTS[k] * (10 - v)) for k, v in vals.items()
            if v <= WEAK and config.SCORE_WEIGHTS[k] >= 0.10]
    weak = [LABELS[max(cost, key=lambda kv: kv[1])[0]]] if cost else []

    parts = []
    if strong:
        parts.append("strong " + " + ".join(strong))
    if weak:
        parts.append("weak on " + weak[0])
    if not parts:
        parts.append("balanced, nothing standout")

    line = ", ".join(parts)

    # Eligibility is the one thing that overrides everything else, so lead with it.
    dims = getattr(item, "dimensions", None) or {}
    elig = str(dims.get("eligible") or "").lower()
    if elig == "no":
        note = dims.get("elig_note") or ""
        return f"not eligible{' (' + note + ')' if note else ''} - {line}"
    if elig == "unclear":
        return f"{line} - verify eligibility"
    return line


def breakdown(item) -> str:
    """Compact numeric trail for the curious: career 9 - interest 8 - skill 3 ..."""
    vals = dimensions_of(item)
    if not vals:
        return ""
    ordered = sorted(vals.items(), key=lambda kv: -config.SCORE_WEIGHTS[kv[0]])
    return "  ".join(f"{LABELS[k]} {v}" for k, v in ordered)
