"""
SYNC SECRETS — give the daily cloud run the two private files the public repo must never hold.

    hunt_target.json          -> secret OH_TARGET_JSON     what you are hunting for (goal, places, pay)
    data/career_profile.json  -> secret OH_CAREER_PROFILE  what every resume is built from

The target also has a copy in the Cloudflare bot, which /target edits from the phone and the cloud
run reads first. This syncs with it before anything else — whichever copy changed last wins.

Both files are gitignored, so without this the 08:00 cloud run hunts with no target and cannot build a
single pack. The profile is sent gzip+base64: raw it is ~43 KB and a GitHub secret is capped at 48 KB
(docs.github.com → Actions → Secrets reference), so one more project would have broken it silently.

Values go to `gh` over stdin — never on a command line, never on screen. Re-run after you edit either
file; the cloud keeps using the old copy until you do.

    py sync_secrets.py            # validate both, then set both
    py sync_secrets.py --check    # validate and show sizes only; send nothing
"""

from __future__ import annotations

import base64
import gzip
import json
import shutil
import subprocess
import sys

import config

SECRET_MAX = 48 * 1024
FILES = [
    ("OH_TARGET_JSON", config.BASE_DIR / "hunt_target.json", False),
    ("OH_CAREER_PROFILE", config.DATA_DIR / "career_profile.json", True),
]


def encode(raw: bytes, packed: bool) -> str:
    """One line either way. GitHub masks a multi-line secret LINE BY LINE, so a pretty-printed JSON
    secret registered "{", "}" and "]" as secrets and every log line lost its brackets ("[push***")."""
    if packed:
        return base64.b64encode(gzip.compress(raw, 9)).decode("ascii")
    return json.dumps(json.loads(raw), ensure_ascii=False, separators=(",", ":"))


def decode(value: str, packed: bool) -> bytes:
    """What the workflow does on the runner — kept here so a test can prove the round trip."""
    return gzip.decompress(base64.b64decode(value)) if packed else value.encode("utf-8")


def prepare() -> list[tuple[str, str, str]]:
    """(secret name, value, note) for every file that exists and is valid JSON."""
    out = []
    for name, path, packed in FILES:
        if not path.exists():
            print(f"  {name:<18} skipped — {path.name} does not exist")
            continue
        raw = path.read_bytes()
        try:
            json.loads(raw)
        except ValueError as e:
            print(f"  {name:<18} REFUSED — {path.name} is not valid JSON ({e.msg}, line {e.lineno})")
            continue
        value = encode(raw, packed)
        if len(value.encode()) > SECRET_MAX:
            print(f"  {name:<18} REFUSED — {len(value):,} bytes is over GitHub's 48 KB secret limit")
            continue
        restored = decode(value, packed)
        assert restored == raw if packed else json.loads(restored) == json.loads(raw)
        note = f"{len(raw):,} bytes" + (f" -> {len(value):,} packed" if packed else "")
        out.append((name, value, note))
    return out


def main() -> int:
    check = "--check" in sys.argv[1:]
    if not check:
        # Phone first: a /target edit made in Telegram must land in this file BEFORE the file is sent
        # anywhere, or a stale laptop copy would overwrite it. Newer laptop edits go to the bot here too.
        from filters import target  # noqa: PLC0415
        synced = target.sync_with_bot()
        if synced:
            print(f"\nTarget and the bot: {synced}")
    print("\nSecrets for the daily cloud run:")
    ready = prepare()
    if check or not ready:
        for name, _, note in ready:
            print(f"  {name:<18} ok ({note})")
        return 0 if ready else 1
    if not shutil.which("gh"):
        print("  gh (GitHub CLI) is not installed — https://cli.github.com, then `gh auth login`.")
        return 1
    failed = 0
    for name, value, note in ready:
        r = subprocess.run(["gh", "secret", "set", name], input=value, text=True,
                           capture_output=True, cwd=config.BASE_DIR)
        if r.returncode == 0:
            print(f"  {name:<18} set ({note})")
        else:
            failed += 1
            print(f"  {name:<18} FAILED — {r.stderr.strip()[:160]}")
    print("\nThe next cloud run uses these. Edit either file again -> run this again.\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
