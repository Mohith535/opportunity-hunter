"""
Application Tracker (Phase C+) — closes the loop from *finding* opportunities to
*winning* them.

Every opportunity you act on gets a status, stored locally in data/tracker.json
(keyed by the same dedup_key the rest of the system uses). The Telegram listener
writes statuses when you tap a button; the weekly Regret Report reads them.

Statuses:
  interested  — surfaced, no action yet (implicit default)
  planned     — you added it to TaskFlow
  applied     — you applied / did it  ✅
  skipped     — not interested, stop nagging  ⏭
  remind      — revisit later (carries a `remind_at` date)  ⏰

This is a LOCAL feature (taps happen via the local listener, TaskFlow is local), so
tracker.json is gitignored — it never goes to the cloud. Every read tolerates a
missing/corrupt file and returns empty, so nothing here can crash a run.
"""

import json
from datetime import date, datetime, timedelta

import config

TRACKER_FILE = config.DATA_DIR / "tracker.json"


def _load() -> dict:
    try:
        return json.loads(TRACKER_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    try:
        TRACKER_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                encoding="utf-8")
    except OSError:
        pass


def _effective_score(item) -> int:
    from filters import policy
    return policy.effective_score(item)


def set_status(key: str, status: str, item=None, remind_days: int = 0) -> None:
    """Record a status for an opportunity. If `item` is given, its metadata is
    captured so reports don't need to re-load history."""
    data = _load()
    entry = data.get(key, {})
    entry["status"] = status
    entry["updated_at"] = date.today().isoformat()
    if item is not None:
        entry.setdefault("title", item.title)
        entry.setdefault("url", item.url)
        entry["score"] = _effective_score(item)
        entry["deadline"] = item.deadline.isoformat() if item.deadline else None
        entry["tags"] = list(item.tags)   # for taste-learning
    if status == "remind":
        days = remind_days or config.TRACKER_REMIND_DAYS
        entry["remind_at"] = (date.today() + timedelta(days=days)).isoformat()
    else:
        entry.pop("remind_at", None)
    data[key] = entry
    _save(data)


def status_of(key: str) -> str:
    return (_load().get(key) or {}).get("status", "")


def due_reminders(today: date | None = None) -> list[tuple[str, dict]]:
    """(key, entry) pairs whose remind_at has arrived."""
    today = today or date.today()
    out = []
    for key, e in _load().items():
        if e.get("status") == "remind" and e.get("remind_at"):
            try:
                if date.fromisoformat(e["remind_at"]) <= today:
                    out.append((key, e))
            except ValueError:
                continue
    return out


def clear_remind(key: str) -> None:
    """A reminder has fired — drop it back to 'interested' so it won't repeat."""
    data = _load()
    if key in data:
        data[key]["status"] = "interested"
        data[key].pop("remind_at", None)
        _save(data)


def _recent(entry: dict, days: int) -> bool:
    try:
        return (date.today() - date.fromisoformat(entry["updated_at"])).days <= days
    except (KeyError, ValueError):
        return False


def build_report(history_items: dict) -> str:
    """The weekly Regret Report (Telegram HTML). `history_items` is {key: Opportunity}
    from the listener, used to find high-value items you haven't acted on yet."""
    import html

    from filters import policy

    data = _load()
    applied = [e for e in data.values() if e.get("status") == "applied" and _recent(e, 7)]
    skipped = [e for e in data.values() if e.get("status") == "skipped" and _recent(e, 7)]
    pending_reminders = [e for e in data.values() if e.get("status") == "remind"]

    # Regret list: high-value, deadline-bearing opportunities you haven't applied to
    # or skipped — soonest first. This is the "you'd regret missing these" nudge.
    acted = {k for k, e in data.items() if e.get("status") in ("applied", "skipped")}
    regret = []
    today = date.today()
    for key, it in history_items.items():
        if key in acted:
            continue
        score = policy.effective_score(it)
        if score < config.HIGH_SCORE or not it.deadline:
            continue
        days = (it.deadline - today).days
        if 0 <= days <= 21:
            regret.append((days, score, it))
    regret.sort(key=lambda x: (x[0], -x[1]))

    lines = ["📊 <b>Weekly Opportunity Report</b>", ""]
    lines.append(f"✅ Applied this week: <b>{len(applied)}</b>")
    for e in applied[:5]:
        lines.append(f"   • {html.escape(e.get('title', '')[:50])}")
    lines.append(f"⏭ Skipped this week: <b>{len(skipped)}</b>")
    lines.append(f"⏰ Reminders pending: <b>{len(pending_reminders)}</b>")
    lines.append("")

    if regret:
        lines.append("⚠️ <b>Closing soon — you haven't acted on these:</b>")
        for days, score, it in regret[:5]:
            when = "today" if days == 0 else ("tomorrow" if days == 1 else f"{days} days")
            lines.append(f"   • [{score}/10] {html.escape(it.title[:46])} — <b>{when}</b>")
    else:
        lines.append("🎉 Nothing high-value slipping through the cracks. Nice.")

    lines.append("\n<i>Reply /report anytime for this summary.</i>")
    return "\n".join(lines)


if __name__ == "__main__":
    print("tracker file:", TRACKER_FILE)
    print("current entries:", len(_load()))
    print("due reminders:", due_reminders())
