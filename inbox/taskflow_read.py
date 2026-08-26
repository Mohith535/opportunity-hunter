"""
Read TaskFlow's task list — READ-ONLY — to surface what's due today or overdue in the phone dashboard.

Why this exists: the honest reason a person stops using their own task app is that the tasks stay
*inside* the app; they never come to you. The phone dashboard you already open does come to you. So we
reach into TaskFlow's shared data file, pull only what's actionable *today*, and show it next to the
inbox. Nothing here writes, edits, completes, or deletes a task — TaskFlow owns its data; we only look.

Data source: ~/.taskflow/tasks.json (a flat list of task objects). Override the folder with the
TASKFLOW_DIR env var. If the file is missing or malformed, we return available=False and the dashboard
simply omits the section — same safe-failure contract Nova uses for our feed.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

# Lower rank = show first. TaskFlow's active tasks are mostly Critical/Strategic; the rest are
# defensive fallbacks so an unexpected label still sorts somewhere sensible instead of crashing.
_PRIORITY_RANK = {
    "critical": 0, "urgent": 0, "high": 1, "important": 1,
    "strategic": 2, "medium": 3, "normal": 3, "low": 4,
}

# The date fields TaskFlow actually populates, best-first. `deadline` is a messy ISO datetime
# (sometimes with 'Z', sometimes microseconds); the others are clean YYYY-MM-DD. We only need the day.
_DATE_FIELDS = ("deadline", "deadline_raw", "date", "end_date")


def _taskflow_file() -> Path:
    root = os.environ.get("TASKFLOW_DIR") or os.path.join(os.path.expanduser("~"), ".taskflow")
    return Path(root) / "tasks.json"


def _parse_date(v) -> datetime.date | None:
    """Pull a calendar date out of any of TaskFlow's date strings, else None."""
    if not v or not isinstance(v, str):
        return None
    day = v.strip().replace("Z", "").split("T")[0].split(" ")[0]  # keep the date part only
    try:
        return datetime.date.fromisoformat(day)
    except ValueError:
        return None


def _task_date(t: dict):
    for f in _DATE_FIELDS:
        d = _parse_date(t.get(f))
        if d:
            return d
    return None


def _is_active(t: dict) -> bool:
    """Open work only: not done, not dropped, not offloaded. `completed` (bool) is the source of truth
    for done-ness — TaskFlow leaves status='todo' on many completed tasks, so status alone lies."""
    if t.get("completed"):
        return False
    if t.get("dropped_at") or t.get("offloaded_at"):
        return False
    if str(t.get("status", "")).lower() in ("completed", "done", "offloaded", "dropped"):
        return False
    return True


def _priority_rank(p) -> int:
    return _PRIORITY_RANK.get(str(p or "").strip().lower(), 3)


def _slim(t: dict, today: datetime.date) -> dict:
    d = _task_date(t)
    return {
        "title": str(t.get("title", "")).strip(),
        "priority": str(t.get("priority", "") or "").strip(),
        "tags": [str(x) for x in (t.get("tags") or []) if x],
        "date": d.isoformat() if d else "",
        "days_over": (today - d).days if d and d < today else 0,
    }


def read_day_tasks(today: datetime.date | None = None, upcoming_days: int = 7) -> dict:
    """Return the day's actionable TaskFlow tasks, READ-ONLY:

        {available, overdue: [...], due_today: [...], upcoming: [...], backlog_count, upcoming_count}

    `overdue`/`due_today` are sorted most-urgent first (priority, then most-overdue). `upcoming` is open
    tasks dated within the next `upcoming_days` (soonest first), for the day plan; `upcoming_count` is
    every open future-dated task; `backlog_count` is open tasks with no date. On any read/parse failure:
    {available: False, ...empty} so callers can just skip the section."""
    empty = {"available": False, "overdue": [], "due_today": [], "upcoming": [],
             "backlog_count": 0, "upcoming_count": 0}
    today = today or datetime.date.today()
    path = _taskflow_file()
    try:
        tasks = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(tasks, list):
        return empty

    overdue, due_today, upcoming, backlog, upcoming_count = [], [], [], 0, 0
    horizon = today + datetime.timedelta(days=upcoming_days)
    for t in tasks:
        if not isinstance(t, dict) or not _is_active(t):
            continue
        d = _task_date(t)
        if d is None:
            backlog += 1
        elif d < today:
            overdue.append(_slim(t, today))
        elif d == today:
            due_today.append(_slim(t, today))
        else:
            upcoming_count += 1
            if d <= horizon:
                upcoming.append(_slim(t, today))

    # Most urgent first: higher priority, then longer overdue.
    overdue.sort(key=lambda x: (_priority_rank(x["priority"]), -x["days_over"]))
    due_today.sort(key=lambda x: _priority_rank(x["priority"]))
    upcoming.sort(key=lambda x: (x["date"], _priority_rank(x["priority"])))
    return {"available": True, "overdue": overdue, "due_today": due_today, "upcoming": upcoming,
            "backlog_count": backlog, "upcoming_count": upcoming_count}
