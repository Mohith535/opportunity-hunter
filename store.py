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


# ─── THE CLOUD'S COPY (22 Oct 2026) ──────────────────────────────────────────────────────────
# The daily hunt runs in GitHub Actions and commits these files; the laptop keeps its own copy, which
# Nova's Scout and `resume.apply --list` read. They had drifted apart: on 22 Oct the laptop lacked 25
# of the cloud's 142 runs (among them 21 Oct's Microsoft India interns, 9/10) and held 22 of its own —
# laptop hunts sharing 10–93% of their items with that day's cloud run, so real runs, not stale copies.
# Merging is a union, so nothing either side found is lost.
CLOUD_RAW = "https://raw.githubusercontent.com/Mohith535/opportunity-hunter/main/data/"
ETAG_FILE = config.DATA_DIR / ".cloud_etag"


def _run_sig(run: dict) -> tuple:
    from models import dedup_key_from_dict  # noqa: PLC0415
    return run.get("date") or "", tuple(sorted(d.get("key") or dedup_key_from_dict(d) for d in run.get("items", [])))


def merge_history(mine: dict, theirs: dict) -> dict:
    """Every run from both copies, once each, in date order (the cloud's run first on a shared date)."""
    runs, sigs = [], set()
    for r in (theirs.get("runs") or []) + (mine.get("runs") or []):
        s = _run_sig(r)
        if s not in sigs:
            sigs.add(s)
            runs.append(r)
    runs.sort(key=lambda r: r.get("date") or "")
    return {"runs": runs}


def merge_seen(mine: dict, theirs: dict) -> dict:
    out = {k: dict(v) for k, v in (theirs.get("items") or {}).items()}
    for k, v in (mine.get("items") or {}).items():
        o = out.setdefault(k, dict(v))
        if o is v or o == v:
            continue
        firsts = [x for x in (o.get("first_seen"), v.get("first_seen")) if x]
        lasts = [x for x in (o.get("last_seen"), v.get("last_seen")) if x]
        if firsts:
            o["first_seen"] = min(firsts)
        if lasts:
            o["last_seen"] = max(lasts)
        o["times_seen"] = max(o.get("times_seen", 1), v.get("times_seen", 1))
    return {"items": out}


def merge_in(theirs_history: dict, theirs_seen: dict | None = None) -> tuple[int, int]:
    """Merge another copy into the local files and refresh the feed. Returns (runs before, after)."""
    mine = _load(config.HISTORY_FILE)
    merged = merge_history(mine, theirs_history)
    before = len(mine.get("runs") or [])
    _save(config.HISTORY_FILE, merged)
    if theirs_seen is not None:
        save_seen(merge_seen(load_seen(), theirs_seen))
    write_feed()
    return before, len(merged["runs"])


def pull_cloud() -> str:
    """Merge the cloud's history + seen into the laptop's copies. Downloads only when the cloud's
    history changed (ETag). One line for the log; never raises."""
    import requests  # noqa: PLC0415
    head = {"User-Agent": config.USER_AGENT}
    try:
        etag = ETAG_FILE.read_text(encoding="utf-8").strip() if ETAG_FILE.exists() else ""
        r = requests.get(CLOUD_RAW + "history.json", timeout=60,
                         headers={**head, **({"If-None-Match": etag} if etag else {})})
        if r.status_code == 304:
            return "[data] the cloud's history has not changed"
        r.raise_for_status()
        theirs = r.json()
        s = requests.get(CLOUD_RAW + "seen_items.json", timeout=60, headers=head)
        seen = s.json() if s.status_code == 200 else None
        before, after = merge_in(theirs, seen)
        if r.headers.get("ETag"):
            ETAG_FILE.write_text(r.headers["ETag"], encoding="utf-8")
        return f"[data] merged the cloud's copy: {before} -> {after} runs"
    except (requests.RequestException, ValueError, OSError) as e:
        return f"[data] could not merge the cloud's copy: {type(e).__name__}"


if __name__ == "__main__":
    # py -m store --pull         merge the cloud's copy (also run every 30 min by resume.sync)
    # py -m store --merge DIR    merge a backup (history.json, seen_items.json in DIR), e.g. after
    #                            `git checkout -- data/` + `git pull` — so local-only runs survive a pull
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.argv[1:2] == ["--pull"]:
        print(pull_cloud())
    elif sys.argv[1:2] == ["--merge"] and len(sys.argv) == 3:
        from pathlib import Path  # noqa: PLC0415
        d = Path(sys.argv[2])
        b, a = merge_in(_load(d / "history.json"), _load(d / "seen_items.json") or None)
        print(f"[data] merged {d}: {b} -> {a} runs")
    else:
        print("usage: py -m store --pull | --merge DIR")
