"""
TaskFlow cloud-sync bridge (OPHunter side).

Writes chosen opportunities into the private taskflow-sync repo's inbox.json,
following TaskFlow's inbox contract (its task_manager/sync.py). TaskFlow's
`taskflow sync pull` then ingests each item via its dump_task pipeline (id +
validation + dedup) and clears the inbox. This is what lets OPHunter add tasks to
TaskFlow from the CLOUD — no local PC, no local TaskFlow needed.

Contract per item (TaskFlow ignores unknown keys):
  inbox_id (uuid, idempotency key) · source ("ophunter" -> #tag) · external_ref ·
  title (supports inline #tag) · priority · deadline (ISO) · deadline_type ·
  notes · links [{url, title}]

Idempotent: each opportunity keeps a stable external_ref (OPH-<dedup_key>); we skip
re-queuing one that's already in the inbox. Best-effort: failures are logged, never
raised — same philosophy as the local TaskFlow adapter.
"""

import base64
import json
import uuid
from datetime import datetime

import requests

import config
from util import log

_API = "https://api.github.com"
_INBOX = "inbox.json"


def is_configured() -> bool:
    return bool(config.TASKFLOW_SYNC_REPO and config.TASKFLOW_SYNC_TOKEN)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.TASKFLOW_SYNC_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": config.USER_AGENT,
    }


def _inbox_url() -> str:
    return f"{_API}/repos/{config.TASKFLOW_SYNC_REPO}/contents/{_INBOX}"


def _get_inbox():
    """Returns (items, sha). ([], None) when the file doesn't exist yet."""
    r = requests.get(_inbox_url(), headers=_headers(), timeout=config.REQUEST_TIMEOUT)
    if r.status_code == 404:
        return [], None
    r.raise_for_status()
    data = r.json()
    raw = base64.b64decode(data["content"].replace("\n", "")).decode("utf-8")
    try:
        items = json.loads(raw) if raw.strip() else []
    except json.JSONDecodeError:
        items = []
    return (items if isinstance(items, list) else []), data["sha"]


def _put_inbox(items, sha, message) -> None:
    body = {
        "message": message,
        "content": base64.b64encode(
            json.dumps(items, indent=2, ensure_ascii=False).encode("utf-8")
        ).decode("ascii"),
    }
    if sha:
        body["sha"] = sha
    r = requests.put(_inbox_url(), headers=_headers(), json=body,
                     timeout=config.REQUEST_TIMEOUT)
    r.raise_for_status()


def _priority_word(score: int) -> str:
    if score >= config.CRITICAL_SCORE:
        return "critical"
    if score >= config.HIGH_SCORE:
        return "high"
    return "low"


def _to_inbox_item(item, score: int) -> dict:
    """An Opportunity -> a TaskFlow inbox item (mirrors the local dump formatting:
    clean verb+title, #type tag, why+plan note, link, hard deadline)."""
    from taskflow import integration
    out = {
        "inbox_id": str(uuid.uuid4()),
        "source": "ophunter",                       # TaskFlow turns this into a #tag
        "external_ref": f"OPH-{item.dedup_key()}",
        # Same formatter as the local dump: "<verb> <title> #<type> #OPHunter !<pri>".
        # TaskFlow's dump_task reads the priority from the title's !flag, so this makes
        # cloud-queued tasks identical to locally-dumped ones (incl. priority).
        "title": integration.build_payload(item, score),
        "priority": _priority_word(score),          # also provided as an explicit field
        "notes": integration._build_note(item),
        "links": ([{"url": item.url, "title": item.title[:60]}] if item.url else []),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if item.deadline:
        out["deadline"] = item.deadline.isoformat()
        out["deadline_type"] = "hard"
    return out


def add_to_inbox(item, score: int) -> bool:
    """Queue an opportunity into TaskFlow's cloud inbox. True on success (or if it's
    already queued). Never raises."""
    if not is_configured():
        log("[cloud-sync] TASKFLOW_SYNC_REPO/TOKEN not set — inbox path disabled.")
        return False
    ref = f"OPH-{item.dedup_key()}"
    try:
        items, sha = _get_inbox()
        if any(x.get("external_ref") == ref for x in items):
            log(f"[cloud-sync] already queued: {item.title[:50]}")
            return True
        items.append(_to_inbox_item(item, score))
        _put_inbox(items, sha, f"ophunter: queue {item.title[:48]} [skip ci]")
        log(f"[cloud-sync] queued to TaskFlow inbox: {item.title[:50]}")
        return True
    except Exception as e:
        log(f"[cloud-sync] inbox write failed: {e}", level="WARN")
        return False


if __name__ == "__main__":
    print("configured:", is_configured(),
          "| repo:", config.TASKFLOW_SYNC_REPO or "(unset)")
