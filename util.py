"""
Shared utilities — logging + safe source execution.

Embodies the error-handling philosophy (CLAUDE.md §12): never die silently,
never let one source crash the whole run.
"""

from datetime import datetime

import config


def log(message: str, level: str = "INFO") -> None:
    """Append a timestamped line to logs/runs.log and echo to stdout."""
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} [{level}] {message}"
    try:
        with open(config.RUNS_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass  # logging must never crash the run
    print(line)


def safe_fetch(source_name: str, fetch_fn) -> list:
    """Run a source's fetch(), returning [] (not raising) on any failure."""
    try:
        results = fetch_fn()
        log(f"[OK] {source_name}: {len(results)} items")
        return results
    except Exception as e:  # noqa: BLE001 — intentional catch-all per §12
        log(f"[ERROR] {source_name}: {e}", level="ERROR")
        return []
