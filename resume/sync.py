"""
SYNC — every pack the cloud sent to Telegram, in applications/ on this laptop (4 Oct 2026).

His words: "I got everything in Telegram, and when I went back to the application folders to apply,
there is no resume for the one I got a message for … better if everything is in one folder."

How: each time the cloud sends a pack it records the Telegram file ids in the bot (PUT /packs). This
pulls that list (GET /packs, bearer token) and downloads every file this laptop does not have yet,
through Telegram's own getFile, into applications/<slug>/. A phone button cannot reach a laptop that
is asleep, so the laptop pulls instead: the 30-minute scheduled task (inbox_refresh.cmd) runs this.

    py -m resume.sync          # pull everything new
"""

from __future__ import annotations

import re
import sys

import requests

import config
from util import log

APPS = config.BASE_DIR / "applications"


def packs() -> list[dict]:
    from filters.target import _bot  # noqa: PLC0415
    url, tok = _bot()
    if not url:
        return []
    try:
        r = requests.get(f"{url}/packs", headers={"Authorization": f"Bearer {tok}", "User-Agent": config.USER_AGENT},
                         timeout=config.REQUEST_TIMEOUT)
        return r.json() if r.status_code == 200 else []
    except (requests.RequestException, ValueError):
        return []


def _safe(name: str) -> str:
    """A file or folder name from the bot is never trusted as a path."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name or "").strip(".-")[:120] or "file"


def download(file_id: str, dest) -> bool:
    """Telegram getFile → the file's bytes → dest. Errors by type only: the URL carries the bot token."""
    base = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"
    try:
        info = requests.get(f"{base}/getFile", params={"file_id": file_id}, timeout=config.REQUEST_TIMEOUT).json()
        path = (info.get("result") or {}).get("file_path")
        if not path:
            return False
        r = requests.get(f"https://api.telegram.org/file/bot{config.TELEGRAM_BOT_TOKEN}/{path}", timeout=60)
        if r.status_code != 200:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        return True
    except (requests.RequestException, ValueError, OSError) as e:
        log(f"[sync] download failed: {type(e).__name__}", level="WARN")
        return False


def run() -> tuple[int, int]:
    """(files downloaded, packs touched)."""
    if not config.TELEGRAM_BOT_TOKEN:
        print("[sync] TELEGRAM_BOT_TOKEN is not set in .env — nothing to download with.")
        return 0, 0
    got, touched = 0, set()
    for p in packs():
        folder = APPS / _safe(p.get("slug", ""))
        for f in p.get("files") or []:
            name = _safe(f.get("name", ""))
            # Telegram gets "<slug>-job.md" so the chat shows which job it is; on disk it is job.md, like
            # every pack built here — unless this laptop already has its own job.md for that pack.
            if name.endswith("-job.md") and not (folder / "job.md").exists():
                name = "job.md"
            elif name.endswith("-job.md"):
                continue
            dest = folder / name
            if dest.exists() or not f.get("file_id"):
                continue
            if download(f["file_id"], dest):
                got += 1
                touched.add(folder.name)
    return got, len(touched)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    got, n = run()
    print(f"[sync] {got} new file(s) in {n} pack folder(s) under applications/" if got
          else "[sync] applications/ is up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
