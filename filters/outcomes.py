"""
OUTCOMES — what his own taps teach the ranking (Phase 6).

Every ✅ Applied / ➕ Plan / ⏭ Skip he taps in Telegram lands in the Cloudflare bot's tracker. The old
learner (taste.py, and relearnTaste in the Worker) learned from TAGS — "internship", "unstop" — which
sit on what he plans and what he skips alike, so they cancel: 56 signals produced 6 likes and ZERO
avoids, and his 13 skips taught it nothing. The role is named in the TITLE, so that is what this
learns from. On his real 51 taps (30 Jun – 15 Sep 2026) it found, unprompted, exactly what he had
said out loud: skipped — marketing, designer, business, sales, growth, graphic; planned — engineer,
research, llm, agents, machine learning.

Rules, each from something measured:
  * a like needs >= 3 taps: at 2, words from research papers he planned ("tesla", "intel", "phd")
    leaked in, and "phd" would have pushed up roles he is not eligible for
  * an avoid needs >= 2 skips and more skips than plans: skips are rarer and clearer
  * words his target already names (roles, avoid) are left to the target — nothing counts twice
  * small nudges (+1 a like, cap +2; -2 a skip, cap -4). Taps teach; the target decides.
  * internships, jobs and fellowships only — "growth" in a skipped role is not "career growth" in a talk
  * it PROPOSES: the app shows what it learned with one-tap "+ Avoid" / "+ Tier 1", so a pattern
    becomes a rule only when he says so

Privacy: the tracker is what he applied to. It is read from the bot, kept in memory, and never
written to data/ (committed to a public repo) or printed in a public log — only counts.
"""

from __future__ import annotations

import re
from collections import Counter

import config

POSITIVE = {"applied", "planned"}
NEGATIVE = {"skipped"}
MIN_LIKE, MIN_AVOID = 3, 2
LIKE_STEP, LIKE_CAP = 1, 2
AVOID_STEP, AVOID_CAP = -2, -4

# Words that name the kind of listing or its packaging, not what the work is.
_STOP = set("""the and for with from your you our are this that into over via per its his her
2024 2025 2026 2027 2028 intern internship internships trainee program programme opportunity opportunities
apply role roles hiring india remote online hybrid new day days week weeks month months hackathon
challenge competition summit conference event events national level international global open
student students fellowship paid unpaid based team""".split())

_CACHE: dict | None = None


def words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z+#\-]{2,}", (title or "").lower()) if w not in _STOP}


def learn(tracker: dict) -> dict:
    """{likes: {word: [plans, skips]}, avoids: {...}, signals: n} from the bot's tracker."""
    pos, neg = Counter(), Counter()
    n = 0
    for e in (tracker or {}).values():
        if not isinstance(e, dict):
            continue
        st = e.get("status")
        if st in POSITIVE:
            pos.update(words(e.get("title", ""))); n += 1
        elif st in NEGATIVE:
            neg.update(words(e.get("title", ""))); n += 1
    likes = {w: [pos[w], neg[w]] for w in pos if pos[w] - neg[w] >= MIN_LIKE}
    avoids = {w: [pos[w], neg[w]] for w in neg if neg[w] >= MIN_AVOID and neg[w] > pos[w]}
    return {"likes": likes, "avoids": avoids, "signals": n}


def fetch_tracker() -> dict | None:
    """The bot's tracker, or None (no bot configured / unreachable). Never raises."""
    import requests  # noqa: PLC0415
    from filters.target import _bot  # noqa: PLC0415
    url, tok = _bot()
    if not url:
        return None
    try:
        r = requests.get(f"{url}/tracker", headers={"Authorization": f"Bearer {tok}",
                                                  "User-Agent": config.USER_AGENT}, timeout=config.REQUEST_TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def learned() -> dict:
    """Learned once per process (the tracker changes on his taps, not mid-run)."""
    global _CACHE
    if _CACHE is None:
        tr = fetch_tracker()
        _CACHE = learn(tr) if tr else {"likes": {}, "avoids": {}, "signals": 0}
    return _CACHE


def reset_cache(value: dict | None = None) -> None:
    global _CACHE
    _CACHE = value


def _covered() -> set[str]:
    """Words the target already names — its roles and avoid list."""
    from filters import target  # noqa: PLC0415
    t = target.load()
    terms = list(t.get("avoid") or []) + [x for v in (t.get("roles") or {}).values() for x in (v or [])]
    return {w for term in terms for w in re.findall(r"[a-z][a-z+#\-]{2,}", str(term).lower())}


def reasons(item, data: dict | None = None) -> list[tuple[str, int]]:
    d = data if data is not None else learned()
    if not d.get("likes") and not d.get("avoids"):
        return []
    # Roles only. He learned "growth" by skipping "Business Growth Internship"; on its first live run
    # it also docked two software-career TALKS whose titles say "career growth". Same scope as the
    # target's role and pay levers.
    from filters import focus, target  # noqa: PLC0415
    if focus.kind_of(item) not in target.EMPLOYMENT_KINDS:
        return []
    ws = words(getattr(item, "title", ""))
    skip = _covered()
    liked = sorted(w for w in ws if w in d["likes"] and w not in skip)
    avoided = sorted(w for w in ws if w in d["avoids"] and w not in skip)
    out = []
    if liked:
        out.append((f"you often plan '{liked[0]}' roles", min(LIKE_CAP, LIKE_STEP * len(liked))))
    if avoided:
        out.append((f"you usually skip '{avoided[0]}' roles", max(AVOID_CAP, AVOID_STEP * len(avoided))))
    return out


def adjustment(item, data: dict | None = None) -> int:
    return sum(dv for _, dv in reasons(item, data))


def note(item) -> str:
    rs = reasons(item)
    return " · ".join(("✓ " if dv > 0 else "✗ ") + why for why, dv in rs)


def apply(items: list) -> int:
    """Nudge scores by what his taps taught. Returns how many items moved. Nothing is dropped."""
    moved = 0
    for it in items:
        dv = adjustment(it)
        if dv:
            it.score = max(0, min(10, it.score + dv))
            moved += 1
    return moved


def publish(data: dict) -> bool:
    """Hand the learned words to the bot, so the app can show them and offer '+ Avoid' / '+ Tier 1'."""
    import requests  # noqa: PLC0415
    from filters.target import _bot  # noqa: PLC0415
    url, tok = _bot()
    if not url:
        return False
    try:
        r = requests.put(f"{url}/learned", headers={"Authorization": f"Bearer {tok}", "User-Agent": config.USER_AGENT},
                         json=data, timeout=config.REQUEST_TIMEOUT)
        return r.ok
    except requests.RequestException:
        return False
