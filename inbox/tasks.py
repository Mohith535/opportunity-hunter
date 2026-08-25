"""
Turn deadline / action emails into TaskFlow tasks — kept SEPARATE from Opportunity Hunter.

It calls your local TaskFlow directly (the `taskflow` command), and tags tasks `#mail` — not
`#OPHunter` — so your email tasks and your opportunity tasks stay clearly apart. It de-duplicates, so
running the assistant twice never creates the same task twice. If TaskFlow isn't installed, it simply
shows what it *would* create and tells you how to turn it on — it never fails the run.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

_DONE = Path(__file__).resolve().parent.parent / "data" / "inbox_tasks_done.json"


def _key(it: dict) -> str:
    return hashlib.md5(f"{it.get('from', '')}|{it.get('subject', '')}".encode()).hexdigest()[:12]


def _load_done() -> set:
    try:
        return set(json.loads(_DONE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_done(keys: set) -> None:
    _DONE.parent.mkdir(exist_ok=True)
    _DONE.write_text(json.dumps(sorted(keys)), encoding="utf-8")


def _taskflow_available() -> bool:
    try:
        return subprocess.run(["taskflow", "version"], capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


def to_taskflow(summary: dict, min_importance: int = 5) -> dict:
    """Create TaskFlow tasks for important deadline/action emails.

    Returns {created, planned, available}. `planned` lists what would be (or was) turned into a task.
    """
    items = [it for it in summary.get("shown", [])
             if (it["category"] in ("DEADLINE", "ACTION") or it.get("deadline"))
             and it["importance"] >= min_importance]
    available = _taskflow_available()
    done = _load_done()
    created, planned = 0, []

    for it in items:
        planned.append(it["subject"][:60])
        k = _key(it)
        if k in done:
            continue
        pri = "!critical" if it["importance"] >= 8 else "!high" if it["importance"] >= 6 else "!low"
        title = f"Handle: {it['subject'][:60]} #mail {pri}"
        if available:
            cmd = ["taskflow", "dump", title, "--note", it["summary"][:200]]
            if it.get("deadline"):
                cmd += ["--deadline", it["deadline"]]
            try:
                if subprocess.run(cmd, capture_output=True, timeout=15, text=True).returncode == 0:
                    done.add(k)
                    created += 1
            except Exception:
                pass

    if created:
        _save_done(done)
    return {"created": created, "planned": planned, "available": available}
