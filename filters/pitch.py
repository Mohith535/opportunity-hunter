"""
PITCH — two short lines that make him want to open it (4 Oct 2026).

His words: "applying is kinda boring … market it to me … money — ₹70,000, that's huge … how
prestigious the company is, how valuable it is to do this … make me excited to apply."

So every listed opportunity leads with what a person actually feels first: the money, the name, how
well he fits, how soon it closes. Deterministic and true — every word comes from the listing or his
own target, never invented — because hype that turns out false is worse than boring.

Two flavours:
  pitch(item)                  job facts only — safe to store in history.json / feed.json (public repo)
  pitch(item, personal=True)   adds his floor and fit ("2.3× your floor", "a tier-1 role for you") —
                               only for Telegram and other private places, never a public file.
"""

from __future__ import annotations

import re
from datetime import date

# What each name means to a student, in a few words. Products only — no claims about pay or culture.
_BRANDS = [
    (r"electronic arts|\bea mobile\b|^ea\b", "EA — the studio behind EA SPORTS FC, Need for Speed and The Sims"),
    (r"\bgoogle\b|deepmind", "Google"),
    (r"microsoft", "Microsoft"),
    (r"\bamazon\b|\baws\b", "Amazon"),
    (r"nvidia", "NVIDIA — the GPUs every AI model trains on"),
    (r"anthropic", "Anthropic — the company behind Claude"),
    (r"openai", "OpenAI — the company behind ChatGPT"),
    (r"\bmeta\b", "Meta"),
    (r"\bapple\b", "Apple"),
    (r"adobe", "Adobe"),
    (r"\bintel\b", "Intel"),
    (r"\bibm\b", "IBM"),
    (r"github", "GitHub"),
    (r"atlassian", "Atlassian"),
    (r"razorpay", "Razorpay"),
    (r"flipkart", "Flipkart"),
    (r"zomato|swiggy|zepto|phonepe|\bcred\b|meesho", None),     # well known — the name says enough
]


def _get(item, key, default=None):
    return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)


def _opp(item):
    if isinstance(item, dict):
        from resume.apply import _as_opp  # noqa: PLC0415
        return _as_opp(item)
    return item


def _brand(text: str) -> str:
    low = text.lower()
    for pat, label in _BRANDS:
        m = re.search(pat, low)
        if m:
            return label or m.group(0).title()
    return ""


def _money(n: int) -> str:
    s = f"{n:,}"
    if n >= 100_000:              # Indian grouping: 1,50,000
        head, tail = str(n)[:-3], str(n)[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        s = f"{head},{tail}"
    return f"₹{s}"


def _prize(text: str) -> int:
    m = re.search(r"prize:\s*cash\s*(\d{3,})", text.lower())
    return int(m.group(1)) if m else 0


def pitch(item, personal: bool = False) -> str:
    """Up to two lines: money · name, then fit · urgency. '' when there is nothing true to say."""
    from filters import focus, target  # noqa: PLC0415
    o = _opp(item)
    title = _get(o, "title", "") or ""
    desc = _get(o, "description", "") or ""
    raw = _get(o, "raw", {}) or {}
    kind = focus.kind_of(o)
    first, second = [], []

    pay = target.pay_of(o)
    if pay:
        hot = "🔥 " if pay >= 50_000 else ""
        line = f"{hot}💰 {_money(pay)}/month"
        floor = (target.load() or {}).get("min_pay_per_month") if personal else 0
        if floor and pay >= floor:
            line += f" ({pay / floor:.1f}× your floor)" if pay >= 1.5 * floor else " (above your floor)"
        first.append(line)
    prize = _prize(desc)
    if prize and kind in ("hackathon", "contest"):
        first.append(f"🏆 {_money(prize)} in prizes")

    # Only on a real opportunity, and only from its title and company: a NEWS story about NVIDIA is not
    # an NVIDIA opportunity, and the first preview said "🏢 NVIDIA" on one.
    who = _brand(f"{title} {raw.get('company') or ''}") if kind not in ("news", "learning", "research") else ""
    if who:
        first.append(f"🏢 {who}")

    if personal:
        hit = target.role_of(o) if kind in target.EMPLOYMENT_KINDS else None
        if hit and hit[0] == "tier1":
            second.append(f"🎯 a tier-1 role for you ({hit[1]})")
        elif hit and hit[0] == "tier2":
            second.append(f"🎯 in your field ({hit[1]})")
        try:
            from filters import outcomes  # noqa: PLC0415
            likes = [w for w, d in outcomes.reasons(o) if d > 0]
            if likes and not hit:
                second.append("🎯 the kind you keep planning")
        except Exception:  # noqa: BLE001 — a pitch never breaks a run
            pass
    if target.is_remote(o) and kind in target.EMPLOYMENT_KINDS:
        second.append("🏠 remote")
    elif kind in target.EMPLOYMENT_KINDS:
        cities = target.cities_of(o)
        if cities:
            second.append(f"📍 {cities[0].title()}")

    dl = _get(o, "deadline")
    if dl:
        d = dl if isinstance(dl, date) else None
        if d is None:
            try:
                d = date.fromisoformat(str(dl)[:10])
            except ValueError:
                d = None
        if d:
            left = (d - date.today()).days
            if 0 <= left <= 3:
                second.append(f"⏳ closes in {left} day{'s' if left != 1 else ''}" if left else "⏳ closes today")
            elif 0 <= left <= 10:
                second.append(f"⏳ {left} days left")

    lines = [" · ".join(first), " · ".join(second)]
    return "\n".join(l for l in lines if l)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, ".")
    from models import Opportunity
    from datetime import timedelta
    o = Opportunity("Software Engineer Intern", "https://x", "ats", "build games", tags=["internship"],
                    deadline=date.today() + timedelta(days=2),
                    raw={"company": "Electronic Arts", "pay_max": 70000, "cities": ["Hyderabad"]})
    p = pitch(o)
    assert "₹70,000/month" in p and "EA —" in p and "closes in 2 days" in p, p
    assert "your floor" not in p, "the public pitch never mentions his floor"
    assert _money(150000) == "₹1,50,000", _money(150000)
    print(p)
