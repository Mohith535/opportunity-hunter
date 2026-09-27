"""
PHASE 5A — the day's best applications, on your phone, with the laptop off.

After the daily cloud hunt, this picks the best NEW internships and jobs from that run, builds the
same pack `py -m resume.apply <n>` builds, and sends it to Telegram:

    the resume PDF   with the card as its caption — verdict, fit, place, pay, deadline, why — and
                     the buttons the Cloudflare bot already handles: ✅ Applied · ⏭ Skip · ⏰ Remind
    the DOCX         for Workday / Taleo / iCIMS, sent silently as a reply
    job.md           the full posting and the checklist, sent silently as a reply

One loud message per pack, so three packs is three notifications, not nine.

Which jobs get a pack:
    - only this run's items (history's latest run, dated today) — each item is new exactly once, so
      nothing is sent twice and no "already sent" state has to live in the public repo
    - internships, jobs and fellowships only; a hackathon does not need a resume
    - today's score at least --min-score (default 7), with your target applied
    - never ⛔, and the verdict is checked AGAIN against the full listing before anything is built —
      the stored line can say ❔ where the full listing says "open to MBA only"

Privacy: the cloud run's log is public (public repo), so under config.PUBLIC_LOGS nothing from your
profile, your target or the packs is printed — only counts, page numbers and font names. The packs
exist only on the runner, which is thrown away when the job ends; they are never workflow artifacts.

    py -m resume.push                    # today's run, up to 3 packs, sent
    py -m resume.push --dry              # build them, send nothing
    py -m resume.push --n 1 --any-day    # use the latest run even if it is not today's (testing)
    py -m resume.push --key 1a2b3c4d5e6f # one pack for one item — what a 📦 tap / `/pack 3` runs
"""

from __future__ import annotations

import contextlib
import html
import io
import json
import re
import sys
from datetime import date
from pathlib import Path

import requests

import config
from util import log

DEFAULT_N = 3
DEFAULT_MIN_SCORE = 7
_CAPTION_MAX = 1024          # Telegram: "Document caption, 0-1024 characters after entities parsing"
_SEND_TIMEOUT = 60


# ─── choosing ─────────────────────────────────────────────────────────────────────────────
def latest_run(any_day: bool = False, today: date | None = None) -> list[dict]:
    """The items of history's newest run — only if that run is today's, unless any_day. main.py does
    not record empty runs, so on a day with nothing new the newest run is yesterday's, and yesterday's
    items were already sent yesterday."""
    try:
        data = json.loads(config.HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    runs = data.get("runs") if isinstance(data, dict) else None
    if not runs:
        return []
    run = runs[-1]
    if not any_day and str(run.get("date")) != (today or date.today()).isoformat():
        return []
    return list(run.get("items") or [])


def pick(rows: list[tuple], min_score: int = DEFAULT_MIN_SCORE) -> list[tuple]:
    """From ranked_items() rows, the ones worth a pack, best first. A row is
    (number, item, score, verdict, off_focus)."""
    from filters import focus, target  # noqa: PLC0415
    from .apply import _as_opp  # noqa: PLC0415
    out = []
    for row in rows:
        _, item, score, verdict, off = row
        if off or verdict.level == "NO" or score < min_score:
            continue
        if focus.kind_of(_as_opp(item)) not in target.EMPLOYMENT_KINDS:
            continue
        out.append(row)
    return out


# ─── the card ─────────────────────────────────────────────────────────────────────────────
def _visible_len(s: str) -> int:
    return len(html.unescape(re.sub(r"<[^>]+>", "", s)))


def card(item: dict, score: int, verdict, pack: dict, fit_rows: list, note: str = "") -> str:
    """The caption on the PDF: everything needed to decide in five seconds whether to open it."""
    from .fit import BUILT, LEARNED  # noqa: PLC0415
    e = html.escape
    full = pack.get("full") or {}
    facts = item.get("facts") or {}
    where = full.get("location") or facts.get("location") or ", ".join(facts.get("cities") or [])
    pay = full.get("pay_note") or ""
    who = " · ".join(x for x in [pack.get("company") or "", where, pay] if x)

    lines = [f"📄 <b>{e((item.get('title') or 'Untitled')[:110])}</b>"]
    if who:
        lines.append(e(who[:140]))
    head = f"{verdict.icon} <b>{e(verdict.label)}</b> · {score}/10"
    warn = next((w for lvl, w in verdict.reasons if lvl in ("NO", "CHECK")), "")
    lines.append(head + (f" — {e(warn[:120])}" if warn else ""))
    if fit_rows:
        b = sum(1 for r in fit_rows if r[1] == BUILT)
        s = sum(1 for r in fit_rows if r[1] == LEARNED)
        gaps = [r[0] for r in fit_rows if r[1] not in (BUILT, LEARNED)]
        fit = f"Fit: {b + s} of {len(fit_rows)} skills backed ({b} built, {s} studied)"
        if gaps:
            fit += f" · gap: {', '.join(gaps[:3])}"
        lines.append(e(fit[:200]))
    if note:
        lines.append(e(note[:200]))
    dl = str(item.get("deadline") or full.get("closes") or "")[:10]
    if dl:
        try:
            left = (date.fromisoformat(dl) - date.today()).days
            lines.append(f"⏳ closes {e(dl)} ({left} day{'s' if left != 1 else ''})")
        except ValueError:
            lines.append(f"⏳ closes {e(dl)}")
    lines.append("<i>Resume PDF + DOCX + job.md attached. Read job.md's checklist, then apply by hand.</i>")

    text = "\n".join(lines)
    while _visible_len(text) > _CAPTION_MAX and len(lines) > 3:     # drop the least important lines
        lines.pop(-2)
        text = "\n".join(lines)
    return text


def buttons(item: dict, pack: dict) -> list:
    """The listing link, plus the three taps the Cloudflare bot already handles for the digest —
    so Applied / Skip / Remind on a pack land in the same tracker, with no Worker change."""
    from models import dedup_key_from_dict  # noqa: PLC0415
    rows = []
    url = (pack.get("full") or {}).get("apply_url") or item.get("url") or ""
    if url.startswith(("http://", "https://")):
        rows.append([{"text": "🔗 Open the listing", "url": url}])
    key = item.get("key") or dedup_key_from_dict(item)
    rows.append([{"text": "✅ Applied", "callback_data": f"applied:{key}"},
                 {"text": "⏭ Skip", "callback_data": f"skip:{key}"},
                 {"text": "⏰ Remind", "callback_data": f"remind:{key}"}])
    return rows


# ─── sending ──────────────────────────────────────────────────────────────────────────────
def _send_document(path: Path, name: str, caption: str = "", keyboard: list | None = None,
                   reply_to: int | None = None, silent: bool = False) -> int | None:
    """sendDocument; returns the message id, or None. Errors are logged by type and Telegram's own
    description only — a requests exception's text contains the URL, and the URL contains the token."""
    data = {"chat_id": config.TELEGRAM_CHAT_ID, "disable_notification": "true" if silent else "false"}
    if caption:
        data.update(caption=caption, parse_mode="HTML")
    if keyboard:
        data["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
    if reply_to:
        data["reply_parameters"] = json.dumps({"message_id": reply_to, "allow_sending_without_reply": True})
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        with open(path, "rb") as fh:
            r = requests.post(url, data=data, files={"document": (name, fh)}, timeout=_SEND_TIMEOUT)
    except (OSError, requests.RequestException) as e:
        log(f"[push] sendDocument failed: {type(e).__name__}", level="WARN")
        return None
    try:
        body = r.json()
    except ValueError:
        body = {}
    if not body.get("ok"):
        log(f"[push] Telegram refused a file: HTTP {r.status_code} {str(body.get('description', ''))[:120]}",
            level="WARN")
        return None
    return (body.get("result") or {}).get("message_id")


def _send_text(text: str) -> None:
    try:
        requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                      json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text,
                            "disable_notification": True}, timeout=config.REQUEST_TIMEOUT)
    except requests.RequestException as e:
        log(f"[push] sendMessage failed: {type(e).__name__}", level="WARN")


def _fonts(pdf: Path | None) -> str:
    """Font families embedded in the PDF ("Carlito, Liberation Serif") — safe to log, and the only way
    to see from a public log whether the cloud runner rendered with the right faces."""
    if not pdf:
        return ""
    try:
        import fitz  # noqa: PLC0415
        with fitz.open(pdf) as d:
            names = {f[3].split("+")[-1].split("-")[0] for p in d for f in p.get_fonts()}
        return ", ".join(sorted(n for n in names if n))
    except Exception:  # noqa: BLE001 — diagnostics only
        return ""


# ─── the run ──────────────────────────────────────────────────────────────────────────────

def pack_one(item: dict, score: int, profile: dict, dry: bool = False, requested: bool = False) -> str:
    """Build one pack and (unless dry) send it. Returns "sent", "built", "skipped" or "failed".
    `requested` is a pack he asked for by tapping 📦 — it is built even when the full listing says ⛔,
    because he asked; the card says so."""
    from filters import target  # noqa: PLC0415
    from .apply import _as_opp, build_pack, eligibility_of, fetch_full_jd  # noqa: PLC0415
    from .fit import skill_evidence  # noqa: PLC0415
    say = print
    label = "" if config.PUBLIC_LOGS else f" {item.get('title', '')[:60]}"
    full = fetch_full_jd(item)
    verdict = eligibility_of(item, full)
    if verdict.level == "NO" and not requested:
        say(f"[push] skipped{label}: the full listing rules you out")
        return "skipped"
    try:
        with contextlib.redirect_stdout(io.StringIO()):    # build_resume prints profile-derived notes
            pack = build_pack(item, full)
    except Exception as e:  # noqa: BLE001 — one broken pack must not stop the others
        say(f"[push] build failed{label}: {type(e).__name__}")
        return "failed"
    if pack["missing"]:
        say(f"[push] renderer not installed ({pack['missing']}) — pip install -r requirements-resume.txt")
    pdf = pack["pdf"]
    status = (f"{pack['pages']}-page PDF, fonts: {_fonts(pdf) or '?'}" if pdf
              else "no PDF (read-back gate: " + "; ".join(pack["problems"][:2]) + ")" if not pack["missing"]
              else "no PDF")
    if dry:
        say(f"[push] built{label}: {status}")
        return "built"

    caption = card(item, score, verdict, pack,
                   skill_evidence(full.get("description") or item.get("description", ""), profile),
                   target.note(_as_opp(item)))
    slug = pack["out"].name
    files = [(p, p.name) for p in (pdf, pack["docx"]) if p]
    files.append((pack["out"] / "job.md", f"{slug}-job.md"))
    if not pdf and not pack["docx"]:
        files.append((pack["out"] / "resume.md", f"{slug}-resume.md"))
    first = _send_document(files[0][0], files[0][1], caption, buttons(item, pack))
    if first is None:
        say(f"[push] could not send pack{label}")
        return "failed"
    for path, name in files[1:]:
        _send_document(path, name, reply_to=first, silent=True)
    say(f"[push] sent{label}: {status}")
    return "sent"


def find_by_key(key: str) -> dict | None:
    """The newest history item with this dedup key. The bot's /top and digest buttons come from
    feed.json — the last 12 runs — so a key can be older than the top-150 that resolve() ranks."""
    from models import dedup_key_from_dict  # noqa: PLC0415
    try:
        data = json.loads(config.HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for run in reversed((data.get("runs") if isinstance(data, dict) else None) or []):
        for d in run.get("items") or []:
            if (d.get("key") or dedup_key_from_dict(d)) == key:
                return d
    return None


def run_key(key: str, dry: bool = False) -> int:
    """One pack for one item, by its dedup key — what a 📦 tap or `/pack 3` asks the cloud for."""
    from .apply import _profile, rescore, resolve  # noqa: PLC0415
    if not re.fullmatch(r"[0-9a-f]{12}", key or ""):
        print("[push] --key must be a 12-character item key")
        return 0
    profile = _profile()
    if not profile.get("basics"):
        print("[push] no career_profile.json here — set OH_CAREER_PROFILE (py sync_secrets.py).")
        return 0
    if not dry and not config.telegram_configured():
        print("[push] Telegram is not configured — nothing sent.")
        return 0
    item = find_by_key(key) or resolve(key)
    if not item:
        print("[push] that item is not in recent history")
        if not dry:
            _send_text("📦 Couldn't build that pack: the item is no longer in recent history.")
        return 0
    return 1 if pack_one(item, rescore(item), profile, dry, requested=True) in ("sent", "built") else 0

def run(n: int = DEFAULT_N, min_score: int = DEFAULT_MIN_SCORE, dry: bool = False,
        any_day: bool = False) -> int:
    """Build and send up to n packs. Returns how many were sent (built, when dry)."""
    from .apply import _profile, ranked_items  # noqa: PLC0415

    say = print
    if n <= 0:
        say("[push] packs are switched off (OH_PACKS=0)")
        return 0
    profile = _profile()
    if not profile.get("basics"):
        say("[push] no career_profile.json here — nothing to build a resume from. In the cloud, set the "
            "OH_CAREER_PROFILE secret (see .github/workflows/daily.yml).")
        return 0
    if not dry and not config.telegram_configured():
        say("[push] Telegram is not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID) — nothing sent.")
        return 0

    items = latest_run(any_day=any_day)
    if not items:
        say("[push] no new items from today's run — nothing to pack.")
        return 0
    chosen = pick(ranked_items(items=items), min_score)
    say(f"[push] {len(items)} new item(s) today, {len(chosen)} eligible internship/job(s) at {min_score}+")

    done = 0
    for _, item, score, _, _ in chosen[: n * 3]:          # a few spares, for listings that fail the recheck
        if done >= n:
            break
        if pack_one(item, score, profile, dry) in ("sent", "built"):
            done += 1
    if not dry and not done:
        _send_text(f"📦 No application pack today: none of today's {len(items)} new item(s) was an "
                   f"internship or job you are eligible for at {min_score}/10 or more.")
    say(f"[push] {'built' if dry else 'sent'} {done} pack(s)")
    return done


def _arg(args: list[str], flag: str, default: int) -> int:
    try:
        return int(args[args.index(flag) + 1])
    except (ValueError, IndexError):
        return default


def main() -> int:
    import os  # noqa: PLC0415
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__)
        return 0
    if "--key" in args:
        i = args.index("--key")
        run_key(args[i + 1] if i + 1 < len(args) else "", dry="--dry" in args)
        return 0
    n = _arg(args, "--n", int(os.environ.get("OH_PACKS", DEFAULT_N) or DEFAULT_N))
    run(n=n, min_score=_arg(args, "--min-score", DEFAULT_MIN_SCORE), dry="--dry" in args,
        any_day="--any-day" in args)
    return 0          # never fail the workflow: the hunt and the digest already succeeded


if __name__ == "__main__":
    raise SystemExit(main())
