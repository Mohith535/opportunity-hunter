"""
How long ago the EMPLOYER posted it (4 Nov 2026).

He asked for "someone always looking", with a loud mark on what was just posted, because an early
application is read first. ("Up to 8x" is a vendor figure nobody could check; the direction is all
this relies on.) A watcher runs every hour (.github/workflows/fresh.yml → `main.py --now --fresh`)
and alerts on roles posted in the last FRESH_HOURS that he can apply to.

"Fresh" uses the board's own timestamp, never "OPH hasn't seen it": items below the daily intake
line are left unseen on purpose, and calling those new would alert him about week-old postings.
No timestamp, no fresh alert; the daily digest still has them.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone

FRESH_HOURS = 48
# Roles the model already turned down for an alert (5 Nov). They are NOT marked seen, so the daily run
# still ranks them, and before this they came back every hour: the same 8 rejects filled all 8 model
# slots from 12:20 to 17:20 IST, and a newer posting ranked under them was never read. Keys and times
# only (this repo is public); kept for FRESH_HOURS, after which the role isn't fresh anyway.
CHECKED_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data",
                            "fresh_checked.json")
_MONTHS = "january february march april may june july august september october november december".split()


def posted_at(item, now: datetime | None = None) -> datetime | None:
    """The posting time from raw["posted"], as UTC, or None. Boards write it five ways:
    ISO (Greenhouse, Ashby, Unstop), epoch seconds or ms (Lever, Microsoft, SimplifyJobs, Himalayas),
    "Posted Today" / "Posted 3 Days Ago" (Workday), "November 3, 2026" (Amazon)."""
    raw = (getattr(item, "raw", None) if not isinstance(item, dict) else item.get("raw")) or {}
    v = raw.get("posted")
    now = now or datetime.now(timezone.utc)
    if v in (None, "", 0):
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip().isdigit()):
        n = float(v)
        try:
            return datetime.fromtimestamp(n / 1000 if n > 1e11 else n, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(v).strip()
    low = s.lower()
    if "today" in low or "just" in low:
        return now
    if "yesterday" in low:
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*days?\s+ago", low)
    if m:
        return now - timedelta(days=int(m.group(1)))
    m = re.fullmatch(r"([a-z]+)\s+(\d{1,2}),\s*(\d{4})", low)
    if m and m.group(1) in _MONTHS:
        return datetime(int(m.group(3)), _MONTHS.index(m.group(1)) + 1, int(m.group(2)), tzinfo=timezone.utc)
    s = re.sub(r"\s*GMT([+-]\d{2})(\d{2})$", r"\1:\2", s)          # Unstop: "2026-11-04 16:22:34 GMT+0530"
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def hours_old(item, now: datetime | None = None) -> float | None:
    now = now or datetime.now(timezone.utc)
    d = posted_at(item, now)
    return None if d is None else max(0.0, (now - d).total_seconds() / 3600)


def badge(item, now: datetime | None = None) -> str:
    """"🆕 posted 3 h ago" while fresh, else "". A day-precision date (Workday, Amazon) reads as a day."""
    h = hours_old(item, now)
    if h is None or h > FRESH_HOURS:
        return ""
    if h < 1:
        return "🆕 posted in the last hour"
    if h < 24:
        return f"🆕 posted {int(h)} h ago"
    return "🆕 posted yesterday"


def is_fresh(item, now: datetime | None = None, max_hours: float = FRESH_HOURS) -> bool:
    h = hours_old(item, now)
    return h is not None and h <= max_hours


def load_checked(path: str = CHECKED_FILE, now: datetime | None = None) -> dict[str, str]:
    """{dedup key: when the model turned it down}, without the ones older than FRESH_HOURS."""
    cut = (now or datetime.now(timezone.utc)) - timedelta(hours=FRESH_HOURS)
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    for k, v in (d.items() if isinstance(d, dict) else ()):
        try:
            if datetime.fromisoformat(str(v).replace("Z", "+00:00")) >= cut:
                out[str(k)] = str(v)
        except ValueError:
            continue
    return out


def remember(checked: dict[str, str], keys, now: datetime | None = None) -> int:
    """Adds the turned-down keys; returns how many are new."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    new = [k for k in keys if k not in checked]
    checked.update({k: stamp for k in new})
    return len(new)


def save_checked(checked: dict[str, str], path: str = CHECKED_FILE) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(checked.items())), f, indent=1)
        f.write("\n")


if __name__ == "__main__":
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    r = lambda v: {"raw": {"posted": v}}  # noqa: E731
    assert badge(r("2026-11-04T09:30:00Z"), now) == "🆕 posted 2 h ago"
    assert badge(r(1793779690), now) == "🆕 posted 3 h ago"                      # Himalayas, 08:08 UTC
    assert posted_at(r("1793779690000"), now) == posted_at(r(1793779690), now)    # ms = s
    assert badge(r(1793779690 - 3 * 86400), now) == ""
    assert badge(r("Posted Today"), now) == "🆕 posted in the last hour" and not is_fresh(r("Posted 30+ Days Ago"), now)
    assert is_fresh(r("2026-11-04 16:22:34 GMT+0530"), now) and not is_fresh(r(None), now)
    print("fresh: ok")
