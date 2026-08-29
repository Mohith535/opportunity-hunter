"""
Deadline Radar — read OPHunter's OWN opportunity feed for anything closing soon, and fold it into the
My Day plan. This is the seam that makes the phone dashboard the single place you see EVERYTHING with a
deadline: your tasks, your email deadlines, and your ranked opportunities.

Strictly READ-ONLY on OPHunter's *output* file (`data/feed.json`, falling back to `data/history.json`)
— it never touches OPHunter's code, and OPHunter stays frozen. If the feed is missing, stale, or has no
future deadlines, this returns [] and the plan simply doesn't show an opportunities row.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data"


def _score(it: dict) -> int:
    """Prefer the LLM score when it's a real positive number, else the rule score (Nova's contract:
    only items scored > 0 are shown)."""
    ai = it.get("ai_score")
    if isinstance(ai, (int, float)) and ai > 0:
        return int(ai)
    s = it.get("score")
    return int(s) if isinstance(s, (int, float)) else 0


def _items_from(path: Path) -> list:
    """Pull the flat item list out of either shape: {"items":[…]} (feed) or {"runs":[{"items":[…]}]}
    (history), or a bare list."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("items"), list):
            return data["items"]
        if isinstance(data.get("runs"), list):
            out = []
            for run in data["runs"]:
                if isinstance(run, dict) and isinstance(run.get("items"), list):
                    out.extend(run["items"])
            return out
    return []


def _parse_date(v):
    if not v:
        return None
    try:
        return datetime.date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def read_opportunity_deadlines(today: datetime.date | None = None,
                               horizon_days: int = 21, min_score: int = 5) -> list[dict]:
    """Opportunities from OPHunter's feed whose deadline is today..+horizon and that score at least
    `min_score`, soonest first. Each row: {title, url, date, source, score, summary}. Deduped by
    url/title. [] on any failure. READ-ONLY."""
    today = today or datetime.date.today()
    horizon = today + datetime.timedelta(days=horizon_days)

    items = _items_from(_DATA / "feed.json") or _items_from(_DATA / "history.json")
    rows, seen = [], set()
    for it in items:
        if not isinstance(it, dict):
            continue
        d = _parse_date(it.get("deadline"))
        if not d or d < today or d > horizon:
            continue
        if _score(it) < min_score:
            continue
        key = (it.get("url") or it.get("title") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append({
            "title": (it.get("title") or "").strip(),
            "url": (it.get("url") or "").strip(),
            "date": d.isoformat(),
            "source": (it.get("source") or "").strip(),
            "score": _score(it),
            "summary": (it.get("ai_summary") or it.get("description") or "").strip(),
        })
    rows.sort(key=lambda r: (r["date"], -r["score"]))
    return rows
