"""
Taste-Learning (Phase C+) — the agent learns YOUR real taste over time.

You already give the signals: tapping ✅ Applied / ➕ Plan is a 👍, ⏭ Skip is a 👎.
This reads those signals from the tracker, tallies the tags of what you engage with
vs. skip, and distils a short "learned preferences" line that gets fed into the LLM
scorer's profile prompt. So the more you use it, the more it scores like you.

Local-only (reads the local tracker; writes data/taste.json, gitignored). Fully
explainable — `/taste` shows exactly what it concluded, and nothing is hidden.
"""

import json
from collections import Counter
from datetime import date

import config

TASTE_FILE = config.DATA_DIR / "taste.json"

_POSITIVE = {"applied", "planned"}
_NEGATIVE = {"skipped"}
# Structural/noise tags that say nothing about taste — ignored when learning.
_STOPLIST = {"ophunter", "inbox", "opportunity", "program", "in-season",
             "opening-soon", "learning", "news"}
_MIN_SIGNALS = 3   # don't show conclusions until there's a little evidence


def _tally(tracker_data: dict) -> tuple[Counter, Counter]:
    pos, neg = Counter(), Counter()
    for entry in tracker_data.values():
        status = entry.get("status")
        tags = [t.lower() for t in (entry.get("tags") or []) if t.lower() not in _STOPLIST]
        if status in _POSITIVE:
            for t in tags:
                pos[t] += 1
        elif status in _NEGATIVE:
            for t in tags:
                neg[t] += 1
    return pos, neg


def relearn() -> dict:
    """Recompute likes/avoids from the tracker and persist them."""
    import tracker
    pos, neg = _tally(tracker._load())
    net = {t: pos[t] - neg[t] for t in set(pos) | set(neg)}
    likes = sorted([t for t, v in net.items() if v > 0], key=lambda t: -net[t])[:6]
    avoids = sorted([t for t, v in net.items() if v < 0], key=lambda t: net[t])[:6]
    data = {
        "likes": likes, "avoids": avoids,
        "pos": dict(pos), "neg": dict(neg),
        "signals": sum(pos.values()) + sum(neg.values()),
        "updated_at": date.today().isoformat(),
    }
    try:
        TASTE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    except OSError:
        pass
    return data


def load() -> dict:
    try:
        return json.loads(TASTE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def summary_line() -> str:
    """One line for the LLM profile prompt. '' until there's enough evidence."""
    d = load()
    if d.get("signals", 0) < _MIN_SIGNALS:
        return ""
    likes, avoids = d.get("likes") or [], d.get("avoids") or []
    parts = []
    if likes:
        parts.append("gravitates toward: " + ", ".join(likes))
    if avoids:
        parts.append("tends to skip: " + ", ".join(avoids))
    return ("LEARNED FROM BEHAVIOUR — " + "; ".join(parts) + ".") if parts else ""


def report_line() -> str:
    """A friendly version for the /taste command (Telegram HTML)."""
    d = load()
    sig = d.get("signals", 0)
    if sig < _MIN_SIGNALS:
        return (f"🧪 Still learning your taste — {sig} signal(s) so far. "
                "Tap ✅/➕/⏭ on a few more and I'll start spotting patterns.")
    likes = ", ".join(d.get("likes") or []) or "—"
    avoids = ", ".join(d.get("avoids") or []) or "—"
    return (f"🧠 <b>What I've learned about your taste</b> ({sig} signals)\n"
            f"👍 You go for: <b>{likes}</b>\n"
            f"👎 You skip: <b>{avoids}</b>")


if __name__ == "__main__":
    print("taste:", relearn())
    print("prompt line:", summary_line() or "(not enough signals yet)")
