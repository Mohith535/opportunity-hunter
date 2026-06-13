"""
TaskFlow adapter (CLAUDE.md §7, §16).

Auto-dumps high-scoring opportunities into TaskFlow as tasks. This is the only
module that knows TaskFlow exists; everything else calls dump()/is_available().
That boundary means Phase 2/3 can swap subprocess for a direct import without
touching callers.

Two safety fixes over the spec:
  * shell=False with an argument list — no shell-injection / quoting bugs when a
    title contains quotes, $, &, ; etc.
  * resolves the binary via shutil.which, falling back to `python -m taskflow`
    so a missing PATH entry (common on Windows) doesn't break the dump.
"""

import subprocess
import sys

import config
from util import log

# Resolve once at import.
import shutil

if shutil.which("taskflow"):
    _BASE_CMD = ["taskflow"]
else:
    _BASE_CMD = [sys.executable, "-m", "taskflow"]


def _priority_flag(score: int) -> str:
    if score >= config.CRITICAL_SCORE:
        return "!c"
    if score >= config.HIGH_SCORE:
        return "!h"
    return "!l"


def _tag_for(item) -> str:
    """Pick a TaskFlow tag from the item's source/tags."""
    src = item.source.lower()
    text = item.text
    if any(t in text for t in ("hackathon", "devpost", "devfolio", "mlh")):
        return "#hackathon"
    if src == "arxiv" or "research" in item.tags or "paper" in text:
        return "#research"
    if any(t in text for t in ("intern", "fellowship", "scholarship", "job", "career")):
        return "#career"
    if "github" in src:
        return "#learning"
    return "#opportunity"


def is_available() -> bool:
    """True if the TaskFlow CLI can be invoked."""
    try:
        result = subprocess.run(
            _BASE_CMD + ["version"],
            capture_output=True, timeout=5, text=True,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def build_payload(item, score: int) -> str:
    """The single string passed to `taskflow dump` (one argument, no shell)."""
    title = item.title[:config.TASKFLOW_TITLE_LIMIT]
    tag = _tag_for(item)
    priority = _priority_flag(score)
    url = item.url or ""
    return f"Apply: {title} — {url} {tag} {priority}".strip()


def dump(item, score: int) -> bool:
    """Create a TaskFlow task for this item. Returns True on success.

    Never raises — a dump failure must not crash the run (§12).
    """
    payload = build_payload(item, score)
    try:
        result = subprocess.run(
            _BASE_CMD + ["dump", payload],  # shell=False: payload is one safe arg
            capture_output=True, timeout=15, text=True,
        )
        if result.returncode == 0:
            log(f"[taskflow] dumped: {payload}")
            try:
                with open(config.DUMPS_LOG, "a", encoding="utf-8") as f:
                    f.write(payload + "\n")
            except OSError:
                pass
            return True
        log(f"[taskflow] dump failed (rc={result.returncode}): {result.stderr.strip()}",
            level="WARN")
        return False
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        log(f"[taskflow] dump error: {e}", level="WARN")
        return False


if __name__ == "__main__":
    from models import Opportunity

    print("taskflow available:", is_available())
    demo = Opportunity(
        'Tricky "title" with $ & ; chars',  # would break shell=True
        "https://example.com/x", "devpost",
        "Online hackathon with prize for students.",
    )
    print("payload:", build_payload(demo, 9))
    if is_available():
        print("dump ok:", dump(demo, 9))
    else:
        print("(TaskFlow not installed — payload built safely, dump skipped)")
