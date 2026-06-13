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
