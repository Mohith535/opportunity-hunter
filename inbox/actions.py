"""
Apply the actions you tapped on your phone — the local half of the phone→local bridge.

Your phone can't reach your computer directly, so a tap on the dashboard (✓ done / ⏰ snooze) is queued
on the Cloudflare worker. This module runs on your machine (as part of a sync), drains that queue, and
applies each action through TaskFlow's OWN CLI — `taskflow complete <id>` / `taskflow schedule <id>
<date>`. That's the honest boundary: we use TaskFlow's public interface, never editing its files or its
code, and TaskFlow keeps its behavioural state correct.

Never raises. If the worker isn't configured or TaskFlow isn't installed, it just reports that and the
run continues.
"""

from __future__ import annotations

import datetime
import os
import shutil
import subprocess

_TASKFLOW = shutil.which("taskflow") or "taskflow"


def _taskflow_available() -> bool:
    try:
        return subprocess.run([_TASKFLOW, "version"], capture_output=True, timeout=5,
                              stdin=subprocess.DEVNULL).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _run(cmd: list) -> bool:
    try:
        r = subprocess.run([_TASKFLOW] + cmd, capture_output=True, timeout=15, text=True,
                           stdin=subprocess.DEVNULL)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _drain(url: str, secret: str) -> list:
    """Pull and clear the queued phone actions from the worker. [] on any failure."""
    import requests  # noqa: PLC0415
    r = requests.post(f"{url}/{secret}/drain", timeout=15)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


def apply_pending() -> dict:
    """Drain queued phone taps and apply them via the TaskFlow CLI.

    Returns {ok, done, snoozed, failed, message}. `ok` is False only when the bridge isn't set up (no
    worker env) — a normal 'nothing queued' run is ok=True with zero counts."""
    url = (os.environ.get("INBOX_WORKER_URL") or "").rstrip("/")
    secret = os.environ.get("INBOX_SECRET") or ""
    if not url or not secret:
        return {"ok": False, "done": 0, "snoozed": 0, "failed": 0,
                "message": "phone actions not set up (no INBOX_WORKER_URL / INBOX_SECRET)"}

    try:
        actions = _drain(url, secret)
    except Exception as e:  # noqa: BLE001
        return {"ok": True, "done": 0, "snoozed": 0, "failed": 0,
                "message": f"couldn't reach the action queue: {str(e)[:80]}"}

    if not actions:
        return {"ok": True, "done": 0, "snoozed": 0, "failed": 0, "message": "no phone actions queued"}

    if not _taskflow_available():
        return {"ok": True, "done": 0, "snoozed": 0, "failed": len(actions),
                "message": f"{len(actions)} phone action(s) queued but the taskflow CLI isn't on PATH"}

    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    done = snoozed = failed = 0
    for a in actions:
        tid = str(a.get("id", "")).strip()
        if not tid:
            continue
        if a.get("act") == "snooze":
            ok = _run(["schedule", tid, tomorrow])
            snoozed += ok
            failed += (not ok)
        else:  # done
            ok = _run(["complete", tid])
            done += ok
            failed += (not ok)

    bits = []
    if done:
        bits.append(f"{done} completed")
    if snoozed:
        bits.append(f"{snoozed} snoozed")
    if failed:
        bits.append(f"{failed} failed")
    return {"ok": True, "done": done, "snoozed": snoozed, "failed": failed,
            "message": "applied " + (", ".join(bits) if bits else "nothing")}
