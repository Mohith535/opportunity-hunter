"""
TaskFlow adapter (CLAUDE.md §7, §16).

Turns an opportunity into a *well-formed* TaskFlow task. This is the only module
that knows TaskFlow exists; everything else calls dump()/is_available().

What lands in TaskFlow now (Phase C polish):
  * Clean TITLE — an action verb + the opportunity name. No URL, no markers.
  * LINK in the link section  (--link / --link-title), not jammed into the title.
  * NOTE = why it matters + the action plan + source  (--note).
  * DEADLINE in the deadline field when known (--deadline, --hard).
  * TAGS = "#<type> #OPHunter"  (e.g. #hackathon #OPHunter) so everything from the
    hunter is filterable by #OPHunter, and grouped by type.
  * DEDUP GUARD — we remember what we've already dumped (data/dumped.json) and skip
    re-creating it, so the same opportunity never piles up as duplicate tasks.

Safety: shell=False with an argument list (no injection/quoting bugs), binary
resolved via shutil.which with a `python -m taskflow` fallback, and every failure
is logged — never raised (§12).
"""

import json
import shutil
import subprocess

import config
from util import log

# Resolve the real TaskFlow CLI via its console script. We deliberately do NOT
# fall back to `python -m taskflow`: this project has its own package named
# `taskflow` (this adapter), so `-m taskflow` would run US, not the real CLI. If
# the console script isn't found we still try the bare name (subprocess fails
# cleanly -> is_available() is False), never our own package.
_TASKFLOW = shutil.which("taskflow")
_BASE_CMD = [_TASKFLOW] if _TASKFLOW else ["taskflow"]

DUMPED_FILE = config.DATA_DIR / "dumped.json"


# ─── type classification → tags + action verb ────────────────────────
# Order matters: the first rule whose keyword appears (in the item's tags, text,
# or source) wins, so more specific/actionable types beat generic ones.
_TYPE_RULES = [
    (("internship", "intern"), "internship"),
    (("fellowship",), "fellowship"),
    (("scholarship", "grant"), "scholarship"),
    (("residency",), "residency"),
    (("ambassador",), "ambassador"),
    (("hackathon", "hack2skill"), "hackathon"),
    (("conference", "webinar", "summit", "meetup", "workshop", "expo", "symposium"), "event"),
    (("competition", "contest", "challenge", "kaggle", "codeforces", "leetcode",
      "codechef", "atcoder"), "competition"),
    (("certification", "certificate", "credential", "course", "nanodegree"), "certification"),
    (("research", "paper", "arxiv", "preprint"), "research"),
]
_SOURCE_FALLBACK = {
    "programs": "program", "github": "learning",
    "reddit": "news", "hackernews": "news", "arxiv": "research",
}
_EVENT_TYPES = {"event"}
_ACTION_VERB = {
    "internship": "Apply:", "fellowship": "Apply:", "scholarship": "Apply:",
    "residency": "Apply:", "ambassador": "Apply:", "program": "Apply:",
    "hackathon": "Register:", "competition": "Register:",
    "event": "Attend:", "research": "Read:", "certification": "Start:",
    "learning": "Explore:", "news": "Read:", "opportunity": "Check:",
}


def classify_type(item) -> str:
    """The single primary type of an opportunity (drives tag + verb)."""
    hay = f"{item.text} {' '.join(item.tags)} {item.source}".lower()
    for keys, tag in _TYPE_RULES:
        if any(k in hay for k in keys):
            return tag
    return _SOURCE_FALLBACK.get(item.source, "opportunity")


def is_event(item) -> bool:
    return classify_type(item) in _EVENT_TYPES


def _priority_flag(score: int) -> str:
    # Full words so TaskFlow's parser maps them unambiguously (it matches
    # 'critical|high|low', not a bare '!c').
    if score >= config.CRITICAL_SCORE:
        return "!critical"
    if score >= config.HIGH_SCORE:
        return "!high"
    return "!low"


def _build_note(item) -> str:
    """The description that lands in the task's notes: why it matters + the plan."""
    parts = []
    if item.ai_summary:
        parts.append(f"Why this matters: {item.ai_summary}")
    if item.action_plan:
        steps = "  ".join(f"{i}. {s}" for i, s in enumerate(item.action_plan, 1))
        parts.append(f"Plan: {steps}")
    org = (item.raw or {}).get("org")
    parts.append(f"Source: {item.source}" + (f" ({org})" if org else "") + " · via OP Hunter")
    return "\n".join(parts)


def build_payload(item, score: int) -> str:
    """The TaskFlow `dump` text argument: verb + clean title + #tags + !priority.
    TaskFlow strips the #tags/!priority into real fields, leaving a clean title."""
    t = classify_type(item)
    verb = _ACTION_VERB.get(t, "Check:")
    title = item.title[:config.TASKFLOW_TITLE_LIMIT]
    return f"{verb} {title} #{t} #OPHunter {_priority_flag(score)}".strip()


# ─── dedup guard ─────────────────────────────────────────────────────
def _load_dumped() -> set:
    try:
        return set(json.loads(DUMPED_FILE.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return set()


def already_dumped(item) -> bool:
    """True if this exact opportunity was already pushed to TaskFlow."""
    return item.dedup_key() in _load_dumped()


def _record_dumped(item) -> None:
    keys = _load_dumped()
    keys.add(item.dedup_key())
    try:
        DUMPED_FILE.write_text(json.dumps(sorted(keys)), encoding="utf-8")
    except OSError:
        pass


def is_available() -> bool:
    """True if the TaskFlow CLI can be invoked."""
    try:
        result = subprocess.run(
            _BASE_CMD + ["version"], capture_output=True, timeout=5, text=True,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def dump(item, score: int) -> bool:
    """Create a well-formed TaskFlow task for this item. Returns True on success
    (or if it was already dumped). Never raises (§12)."""
    if already_dumped(item):
        log(f"[taskflow] already dumped, skipping duplicate: {item.title[:50]}")
        return True

    cmd = _BASE_CMD + ["dump", build_payload(item, score)]
    if item.url:
        cmd += ["--link", item.url, "--link-title", item.title[:60]]
    note = _build_note(item)
    if note:
        cmd += ["--note", note]
    if item.deadline:
        # Real opportunity deadlines are hard — feed TaskFlow's urgency system.
        cmd += ["--deadline", item.deadline.isoformat(), "--hard"]
    # stdin is closed so the CLI can never block on a prompt.

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=15, text=True,
                                stdin=subprocess.DEVNULL)
        if result.returncode == 0:
            _record_dumped(item)
            log(f"[taskflow] dumped: {item.title[:60]} "
                f"[#{classify_type(item)} #OPHunter]")
            try:
                with open(config.DUMPS_LOG, "a", encoding="utf-8") as f:
                    f.write(f"{item.dedup_key()}  {item.title}\n")
            except OSError:
                pass
            return True
        log(f"[taskflow] dump failed (rc={result.returncode}): {result.stderr.strip()}",
            level="WARN")
        return False
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        log(f"[taskflow] dump error: {e}", level="WARN")
        return False


def plan(item, score: int) -> bool:
    """Route a "plan this" action: use the local TaskFlow CLI when it's available,
    otherwise queue into the cloud-sync inbox (for cloud/remote runs where there is
    no local TaskFlow). Returns True on success. Never raises."""
    if is_available():
        return dump(item, score)
    from taskflow import cloud_sync
    return cloud_sync.add_to_inbox(item, score)


if __name__ == "__main__":
    from datetime import date, timedelta

    from models import Opportunity

    print("taskflow available:", is_available())
    demo = Opportunity(
        "Google Summer of Code 2026", "https://summerofcode.withgoogle.com/",
        "programs", "Remote open-source internship with stipend.",
        deadline=date.today() + timedelta(days=20), tags=["program", "internship"],
    )
    demo.ai_summary = "Elite Google open-source credential, remote, stipend."
    demo.action_plan = ["Pick an org (1h)", "Make a first PR (1d)", "Draft proposal (3h)"]
    print("type :", classify_type(demo))
    print("title:", build_payload(demo, 9))
    print("note :", _build_note(demo).replace("\n", " | "))
