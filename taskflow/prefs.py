"""
TaskFlow permission gate + offload-aware signals (OPHunter side).

TaskFlow owns the consent settings (a `permissions` block in ~/.taskflow/config.json)
and the behavioural data (~/.taskflow/tasks.json). OPHunter only READS them and
respects them:

  * can_write() — may we create tasks on the board?  (permissions.ophunter_write)
  * can_read()  — may we read behavioural signals?   (permissions.ophunter_read)
  * offload_signals()/apply_downweight() — de-prioritise categories the user
    repeatedly DROPS or OFFLOADS ("stop finding me this kind of thing").

Everything is read LIVE each run (never cached), resolves the data dir the same way
as the rest of the project (config.TASKFLOW_DATA_DIR honours TASKFLOW_DATA_PATH), and
is fail-safe: a missing/corrupt config.json or tasks.json → permissions assumed TRUE
and an empty signal set, never a crash.
"""

import json
import re
from collections import Counter

import config
from util import log


def _config_path():
    return config.TASKFLOW_DATA_DIR / "config.json"


def _tasks_path():
    return config.TASKFLOW_DATA_DIR / "tasks.json"


def _permissions() -> dict:
    """The permissions block, or {} if absent/unreadable (→ permissive defaults)."""
    try:
        cfg = json.loads(_config_path().read_text(encoding="utf-8"))
        perms = cfg.get("permissions")
        return perms if isinstance(perms, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def can_write() -> bool:
    """May OPHunter create tasks in TaskFlow? Missing key → True (permissive)."""
    return bool(_permissions().get("ophunter_write", True))


def can_read() -> bool:
    """May OPHunter read TaskFlow behavioural data? Missing key → True."""
    return bool(_permissions().get("ophunter_read", True))


# ─── offload-aware "not interested" signals ──────────────────────────
# Structural tags that carry no taste meaning — never a down-weight signal.
_STOP_TAGS = {"ophunter", "inbox", "opportunity", "career", "misc", "general", "todo"}
# Generic title words that shouldn't count as a category keyword.
_STOP_WORDS = {
    "apply", "your", "this", "that", "from", "with", "program", "summer", "winter",
    "student", "students", "india", "online", "open", "free", "internship", "intern",
    "national", "level", "using", "build", "have", "will", "into", "about", "2025",
    "2026", "2027", "the", "and", "for",
}


def _is_set_down(task: dict) -> bool:
    """True if the user dropped or offloaded this task (a negative signal)."""
    if task.get("dropped_at") or task.get("offloaded_at"):
        return True
    if task.get("status") in ("dropped", "offloaded"):
        return True
    for e in (task.get("edit_history") or []):
        if e.get("field") == "status" and e.get("new_value") in ("dropped", "offloaded"):
            return True
    return False


def offload_signals(min_count: int = 2) -> dict:
    """Down-weight signals from tasks the user repeatedly set down. Returns
    {"tags": {tag: count}, "keywords": {word: count}} keeping only those seen
    >= min_count times (a REPEATED pattern — one dismissal is noise). {} when
    ophunter_read is off or on any failure."""
    empty = {"tags": {}, "keywords": {}}
    if not can_read():
        return empty
    try:
        data = json.loads(_tasks_path().read_text(encoding="utf-8"))
        tasks = data.get("tasks") if isinstance(data, dict) else data
    except (OSError, json.JSONDecodeError, TypeError):
        return empty

    tag_c, kw_c = Counter(), Counter()
    for t in tasks or []:
        if not isinstance(t, dict) or not _is_set_down(t):
            continue
        for tag in (t.get("tags") or []):
            tl = str(tag).lower().lstrip("#").strip()
            if tl and tl not in _STOP_TAGS:
                tag_c[tl] += 1
        for w in re.findall(r"[a-z][a-z]{3,}", (t.get("title") or "").lower()):
            if w not in _STOP_WORDS:
                kw_c[w] += 1

    return {
        "tags": {t: c for t, c in tag_c.items() if c >= min_count},
        "keywords": {w: c for w, c in kw_c.items() if c >= min_count},
    }


def _downweight_one(item, tags: dict, kws: dict):
    """If an opportunity matches a repeated offload signal, reduce its score and
    return a short note; else None. Mutates the item."""
    item_tags = {str(t).lower().lstrip("#") for t in (item.tags or [])}
    text = item.text
    matched: dict = {}
    for tag, c in tags.items():
        if tag in item_tags or re.search(rf"\b{re.escape(tag)}\b", text):
            matched[f"#{tag}"] = c
    for kw, c in kws.items():
        if re.search(rf"\b{re.escape(kw)}\b", text):
            matched[kw] = c
    if not matched:
        return None

    top = max(matched.values())
    penalty = min(4, max(2, top))          # -2 .. -4, scaled by how repeated it is
    if item.ai_score >= 0:
        item.ai_score = max(0, item.ai_score - penalty)
    else:
        item.score = max(0, item.score - penalty)
    label = sorted(matched, key=lambda k: -matched[k])[0]
    note = f"↓ deprioritized — you've set down similar ({label} ×{matched[label]})"
    item.ai_summary = f"{item.ai_summary}  {note}".strip() if item.ai_summary else note
    item.dimensions = {**(item.dimensions or {}), "downweight": penalty}
    return note


def apply_downweight(items) -> int:
    """De-prioritise fresh opportunities matching the user's repeated offload
    patterns. Respects ophunter_read (empty signals → no change). Returns count."""
    sig = offload_signals()
    tags, kws = sig.get("tags", {}), sig.get("keywords", {})
    if not tags and not kws:
        return 0
    n = 0
    for it in items:
        if _downweight_one(it, tags, kws):
            n += 1
    if n:
        log(f"[prefs] down-weighted {n} item(s) matching your offload patterns "
            f"(tags={list(tags)}, keywords={list(kws)[:5]})")
    return n


if __name__ == "__main__":
    print("can_read :", can_read(), "| can_write:", can_write())
    print("offload signals:", offload_signals())
