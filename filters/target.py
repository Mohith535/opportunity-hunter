"""
THE STANDING TARGET — "what am I aiming at, and by when?"

FOCUS answers "what kind of thing am I hunting this week" and is set per run. A target is the
layer above it: a goal that stays true for weeks and that the daily run applies by itself. The
request behind this module was exact — *"I don't want to ask you every time, can you make that
feature?"* — so nothing here needs a flag. You edit `hunt_target.json` once; every hunt after
that is tuned to it.

A target carries these levers, and each one maps to a fact the sources already give us:

  focus      -> the kinds to hunt, so --focus becomes unnecessary
  locations   -> cities you could actually take ("remote" is a valid entry)
  min_pay     -> a floor in rupees per month
  by          -> the date you need it resolved by, which makes a late deadline a MINUS
  roles       -> tier1 / tier2 role words, matched on the title (employment kinds only)
  avoid       -> role words to sink ("sales", "seo"), unless the title also names a tier1/2 role

What this deliberately does NOT do is filter. Every adjustment is a score nudge, so a target
can never hide a once-in-a-year opportunity just because it pays nothing or sits in the wrong
city — the same principle as FOCUS's KEEP_ANYWAY hatch. A target sharpens the ranking; it is
not a gate. `reasons()` reports every nudge it made, because an invisible re-ranking is one you
stop trusting.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime

import config

TARGET_FILE = config.BASE_DIR / "hunt_target.json"

# How hard each lever pulls. Overridable via config.TARGET_WEIGHTS.
_DEFAULT_WEIGHTS = {
    "location_hit": 3,     # in a city you named, or remote when you accept remote
    "location_miss": -3,   # in-office somewhere you did not name — you cannot be there
    "pay_hit": 3,          # states pay at or above your floor
    "pay_below": -2,       # states pay, and it is under your floor
    "pay_unknown": -3,     # says nothing about money, and money is the point (require_pay)
    "too_late": -3,        # deadline falls after the date you need this by
    "role_tier1": 3,       # the title names a role you put in roles.tier1
    "role_tier2": 1,       # ...in roles.tier2 — your study, wider than your first choice
    "role_avoid": -5,      # the title names a role on your avoid list, and nothing from tier1/2
}

# Kinds where "which city" and "how much does it pay" are meaningful questions. A hackathon has
# neither an office nor a salary, so the money and location levers must not touch it.
#
# This is not a refinement, it is a correctness fix found by running the thing: with the levers
# applied to everything, an online hackathon scored +3 for "remote, which you accept" and +2 for
# a near deadline, so a target meaning "paid internship in Mumbai" promoted a dozen unpaid
# hackathons to 10/10 — precisely backwards. There was a second bug in the same output: the old
# `in_window` bonus re-rewarded deadline urgency that filters/scorer.py already scores, so
# everything with a near deadline got the same free +2. It is gone. `too_late` stays, because
# "closes after the date YOU need this by" is information the base scorer genuinely lacks.
EMPLOYMENT_KINDS = {"internship", "job", "fellowship"}

# Money written into free text, for sources with no structured pay field. Rupees only; a
# stipend quoted in dollars is a different conversation and gets no guess.
_PAY_RE = re.compile(
    r"(?:₹|rs\.?|inr)\s?([\d,]{3,})\s*(?:/|per\s*)?\s*(month|mo\b|pm\b|p\.m)?"
    r"|([\d,]{4,})\s*(?:/|per\s*)?\s*month", re.I)

_CACHE: dict | None = None


def load(path=None) -> dict:
    """The active target, or {} when there is none. Missing/malformed file -> {} (never raises)."""
    global _CACHE
    if path is None and _CACHE is not None:
        return _CACHE
    f = path or TARGET_FILE
    out: dict = {}
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and raw.get("active"):
            out = {k: v for k, v in raw.items() if not k.startswith("_")}
    except (OSError, ValueError, AttributeError):
        out = {}
    if path is None:
        _CACHE = out
    return out


def reset_cache() -> None:
    """Drop the memoised target — for tests, and for --no-target."""
    global _CACHE
    _CACHE = None


def active() -> bool:
    return bool(load())


def weights() -> dict:
    return {**_DEFAULT_WEIGHTS, **(getattr(config, "TARGET_WEIGHTS", None) or {})}


def focus_kinds() -> list[str]:
    """Kinds the target wants hunted, so the user never types --focus for a standing goal."""
    t = load()
    return [str(k).strip().lower() for k in (t.get("focus") or []) if str(k).strip()]


def deadline_by():
    t = load()
    try:
        return date.fromisoformat(str(t.get("by")))
    except (ValueError, TypeError):
        return None


def per_month(n: int) -> int:
    """Normalise a pay figure to rupees per month.

    ponytail: a threshold heuristic, because no source states its unit. >= 100000 is read as an
    annual CTC. Idempotent for realistic student pay, so it is safe to apply to a value a source
    already normalised. Known ceiling: a genuine 1,00,000/month salary would be divided — it has
    never appeared in a student listing, and the alternative is trusting an unlabelled number.
    Upgrade path: have each source record its own unit alongside the value."""
    return round(n / 12) if n >= 100_000 else n


def pay_of(item) -> int:
    """Rupees per month this item pays, or 0 when it does not say.

    Prefers the structured value a source handed us (Unstop's jobDetail), then falls back to
    reading money out of the description. Structured first because parsing prose for money is
    how you end up treating a 100000 prize pool as a monthly salary.

    Normalises even the structured value: the function's contract is "per month", and it must
    hold whoever populated `raw` — not only the one source that happens to normalise already."""
    raw = getattr(item, "raw", None) or {}
    for key in ("pay_max", "pay_min"):
        try:
            v = int(raw.get(key) or 0)
        except (TypeError, ValueError):
            v = 0
        if v:
            return per_month(v)

    text = f"{getattr(item, 'title', '')} {getattr(item, 'description', '')}"
    best = 0
    for m in _PAY_RE.finditer(text):
        num = m.group(1) or m.group(3) or ""
        unit = m.group(2)
        try:
            n = int(num.replace(",", ""))
        except ValueError:
            continue
        # Only trust an unlabelled number if it came from the "<n> per month" branch (group 3).
        if not unit and not m.group(3):
            continue
        best = max(best, per_month(n))
    return best


def cities_of(item) -> list[str]:
    raw = getattr(item, "raw", None) or {}
    cities = [str(c).lower() for c in (raw.get("cities") or []) if c]
    if cities:
        return cities
    # ATS keeps its location as a single string; other sources may have none at all.
    loc = str(raw.get("location") or "")
    return [loc.lower()] if loc else []


def is_remote(item) -> bool:
    raw = getattr(item, "raw", None) or {}
    if raw.get("remote"):
        return True
    # A structured office list outranks the prose. Unstop writes "job | online |" into EVERY
    # description — that is how you register, not where you work — so the word "online" made all
    # ten Mumbai jobs in a live sample read "remote, which you accept" and the Mumbai lever, the
    # whole point of this target, never fired for them.
    if raw.get("cities"):
        return False
    text = f"{getattr(item, 'title', '')} {getattr(item, 'description', '')}".lower()
    return any(w in text for w in ("remote", "work from home", "wfh", "online"))


def _phrase(term: str) -> re.Pattern:
    """Whole-word, hyphen-tolerant: "full stack" matches "Full-Stack", "hr" does not match "three"."""
    words = [re.escape(w) for w in re.split(r"[\s\-]+", term.strip().lower()) if w]
    return re.compile(r"\b" + r"[\s\-]+".join(words) + r"\b")


def role_of(item) -> tuple[str, str] | None:
    """("tier1" | "tier2" | "avoid", the matching term) for this item's TITLE, or None.

    Tier 1 wins over tier 2, and either wins over avoid — "Sales Engineer, AI Agents" names a role
    he wants, and the avoid list exists to sink jobs that are ONLY the thing he does not want."""
    t = load()
    title = str(getattr(item, "title", "") or "").lower()
    if not t or not title:
        return None
    roles = t.get("roles") or {}
    for level in ("tier1", "tier2"):
        for term in roles.get(level) or []:
            if str(term).strip() and _phrase(str(term)).search(title):
                return level, str(term)
    for term in t.get("avoid") or []:
        if str(term).strip() and _phrase(str(term)).search(title):
            return "avoid", str(term)
    return None


def reasons(item) -> list[tuple[str, int]]:
    """Every nudge this target makes to this item, as (why, delta). Empty when no target."""
    t = load()
    if not t:
        return []
    w = weights()
    out: list[tuple[str, int]] = []

    from filters import focus
    employment = focus.kind_of(item) in EMPLOYMENT_KINDS

    # ── role ── what the job IS, judged on the title, where the role is named. He asked for this
    # in so many words: "OPH is getting me sales internships, not my track". The scorer's own
    # off-domain list never had SEO, PR or "caller", so an "SEO Internship" reached 10/10 in the
    # list he picks packs from. His own lists, not ours — he edits them in hunt_target.json.
    if employment:
        hit = role_of(item)
        if hit:
            level, term = hit
            out.append({"tier1": (f"a tier-1 role for you ({term})", w["role_tier1"]),
                        "tier2": (f"in your wider field ({term})", w["role_tier2"]),
                        "avoid": (f"on your avoid list ({term})", w["role_avoid"])}[level])

    # ── place ── only where an office is a real concept ───────────────────────────────────
    wanted = [str(c).strip().lower() for c in (t.get("locations") or []) if str(c).strip()]
    if wanted and employment:
        accepts_remote = "remote" in wanted
        named = [c for c in wanted if c != "remote"]
        cities = cities_of(item)
        if accepts_remote and is_remote(item):
            out.append(("remote, which you accept", w["location_hit"]))
        elif cities and any(any(n in c for n in named) for c in cities):
            hit = next(c for c in cities if any(n in c for n in named))
            out.append((f"in {hit.title()}", w["location_hit"]))
        elif cities and named:
            # It states a city, and it is not one of yours. That is a real mismatch, not a gap.
            out.append((f"in {cities[0].title()}, not on your list", w["location_miss"]))

    # ── money ── likewise: a hackathon has no salary to be under your floor ───────────────
    floor = t.get("min_pay_per_month") or 0
    if floor and employment:
        pay = pay_of(item)
        if pay >= floor:
            out.append((f"pays about Rs {pay:,}/month", w["pay_hit"]))
        elif pay:
            out.append((f"pays only Rs {pay:,}/month", w["pay_below"]))
        elif t.get("require_pay"):
            out.append(("does not state any pay", w["pay_unknown"]))

    # ── time ── only the penalty. No bonus: scorer.py already rewards a near deadline, and
    # paying for it twice handed a free +2 to everything with a date on it.
    by = deadline_by()
    dl = getattr(item, "deadline", None)
    if by and isinstance(dl, (date, datetime)):
        dl = dl.date() if isinstance(dl, datetime) else dl
        if dl > by:
            out.append((f"closes {dl}, after your {by} date", w["too_late"]))

    return out


def adjustment(item) -> int:
    return sum(d for _, d in reasons(item))


def apply(items: list) -> int:
    """Nudge every item's score toward the target. Returns how many items moved.

    Scores stay inside 0-10 and nothing is dropped: a target ranks, it does not gate."""
    if not load():
        return 0
    moved = 0
    for it in items:
        delta = adjustment(it)
        if delta:
            it.score = max(0, min(10, it.score + delta))
            moved += 1
    return moved


def note(item) -> str:
    """One line for the brief: why the target moved this item."""
    rs = reasons(item)
    if not rs:
        return ""
    good = [why for why, d in rs if d > 0]
    bad = [why for why, d in rs if d < 0]
    bits = []
    if good:
        bits.append("✓ " + "; ".join(good))
    if bad:
        bits.append("✗ " + "; ".join(bad))
    return " · ".join(bits)


def describe() -> str:
    """One line for the brief header, and for `--target`."""
    t = load()
    if not t:
        return ""
    bits = []
    if t.get("locations"):
        bits.append("/".join(str(c) for c in t["locations"]))
    if t.get("min_pay_per_month"):
        bits.append(f"Rs {int(t['min_pay_per_month']):,}+/mo")
    if t.get("by"):
        by = deadline_by()
        if by:
            left = (by - date.today()).days
            bits.append(f"by {t['by']} ({left}d left)" if left >= 0 else f"by {t['by']} (PASSED)")
    head = str(t.get("goal") or "target active")
    return f"{head}" + (f"  [{' · '.join(bits)}]" if bits else "")
