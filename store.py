"""
Persistence layer — deduplication (seen_items.json) + history (history.json).

The only module that touches those files. Sources/filters/main never read or
write JSON directly. Dedup identity comes from Opportunity.dedup_key(), which
already canonicalizes URLs and prefers source-native IDs.
"""

import json
from datetime import date

import config


def _load(path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Corrupt/partial file -> start clean rather than crash the run.
            return {}
    return {}


def _save(path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ─── SEEN / DEDUP ────────────────────────────────────────────────────
def load_seen() -> dict:
    data = _load(config.SEEN_FILE)
    return data if "items" in data else {"items": {}}


def is_seen(seen: dict, item) -> bool:
    return item.dedup_key() in seen["items"]


def should_resurface(item) -> bool:
    """Exception to dedup (CLAUDE.md §11): re-show a maxed-out item if its
    deadline is within 3 days, even if already seen."""
    if policy_score(item) >= 10 and item.deadline:
        days_left = (item.deadline - date.today()).days
        return 0 <= days_left <= 3
    return False


def policy_score(item) -> int:
    # Local import avoids a circular import at module load.
    from filters import policy

    return policy.effective_score(item)


def mark_seen(seen: dict, item) -> None:
    key = item.dedup_key()
    today = date.today().isoformat()
    entry = seen["items"].get(key)
    if entry:
        entry["times_seen"] = entry.get("times_seen", 1) + 1
        entry["last_seen"] = today
    else:
        seen["items"][key] = {
            "title": item.title,
            "first_seen": today,
            "last_seen": today,
            "times_seen": 1,
        }


def save_seen(seen: dict) -> None:
    _save(config.SEEN_FILE, seen)


# ─── HISTORY ─────────────────────────────────────────────────────────
def append_history(items: list) -> None:
    """Append this run's relevant items to the rolling history log."""
    data = _load(config.HISTORY_FILE)
    runs = data.get("runs", [])
    runs.append({
        "date": date.today().isoformat(),
        "items": [it.to_dict() for it in items],
    })
    _save(config.HISTORY_FILE, {"runs": runs})


def write_feed(limit: int = 100) -> None:
    """Write a compact, key-bearing feed of the top opportunities for the cloud bot
    (Cloudflare Worker) to consume — so it never has to parse the whole history or
    re-derive dedup keys. Union of recent runs, deduped by key, sorted by score."""
    from models import dedup_key_from_dict

    data = _load(config.HISTORY_FILE)
    runs = data.get("runs", [])
    by_key: dict = {}
    for run in runs[-12:]:                 # recent runs cover what's in live digests
        for d in run.get("items", []):
            key = d.get("key") or dedup_key_from_dict(d)
            by_key[key] = d                # latest wins

    def _score(d: dict) -> int:
        ai = d.get("ai_score", -1)
        return ai if ai is not None and ai >= 0 else d.get("score", 0)

    top = sorted(by_key.values(), key=_score, reverse=True)[:limit]
    feed = []
    for d in top:
        feed.append({
            "key": d.get("key") or dedup_key_from_dict(d),
            "title": d.get("title", ""),
            "url": d.get("url", ""),
            "source": d.get("source", ""),
            "score": _score(d),
            "deadline": d.get("deadline"),
            "tags": d.get("tags", []),
            "ai_summary": d.get("ai_summary", ""),
            "action_plan": d.get("action_plan", []),
        })
    _save(config.FEED_FILE, {"updated_at": date.today().isoformat(), "items": feed})


if __name__ == "__main__":
    from models import Opportunity

    item = Opportunity("Test Opportunity", "https://example.com/x?utm=1", "test",
                       native_id="demo-123")
    seen = load_seen()
    print("seen before:", is_seen(seen, item))
    mark_seen(seen, item)
    save_seen(seen)

    seen2 = load_seen()
    print("seen after (reload):", is_seen(seen2, item))
    print("times_seen:", seen2["items"][item.dedup_key()]["times_seen"])
