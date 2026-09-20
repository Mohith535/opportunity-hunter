"""
FOCUS — "what am I hunting *this week*?"

The hunter was built to answer one fixed question: what matters to Mohith in general. But
interest is seasonal. Some weeks the answer is hackathons; some weeks it is fellowships that
pay, or research, or government startup funding. Without a way to say so, every week is scored
by the same average of all his interests, and the thing he actually wants right now arrives
ranked below three papers and an internship.

This module adds that switch. `kind_of()` labels every item with ONE plain category, and
`apply()` re-ranks the pool around whichever categories are active.

Two modes, and the difference matters:
  * "boost" (default) — focus kinds gain, others lose, nothing disappears. Use when you have a
    preference but still want to see the rest.
  * "only" — non-focus kinds are dropped... EXCEPT anything already scoring >= KEEP_ANYWAY.
    A mentor does not hide a once-a-year deadline because you said "hackathons today". The
    escape hatch is the whole reason this is safe to switch on.

Focus is never silent: every re-ranked item gets a `focus:<kind>` or `focus:off-topic` tag so
the brief can say why the order changed. Silent re-ranking is how you stop trusting your own tool.
"""

from __future__ import annotations

import re

import config

# The categories Mohith actually thinks in. Deliberately small — a taxonomy nobody can hold in
# their head is a taxonomy nobody will use.
KINDS = ("hackathon", "research", "internship", "fellowship", "grant",
         "startup", "scholarship", "contest", "ambassador", "learning")

# In "only" mode, an item this good is shown whatever the focus says.
KEEP_ANYWAY = 9

BOOST = 2     # focus kinds gain this
PENALTY = 2   # off-topic kinds lose this

# Source -> kind, where the source alone already settles it. Checked BEFORE keywords, because
# the source is a fact and a keyword is a guess.
_BY_SOURCE = {
    "arxiv": "research",
    "devpost": "hackathon",
    "devfolio": "hackathon",
    "mlh": "hackathon",
    "clist": "contest",
    "internships": "internship",
    "github": "learning",
    "reddit": "learning",
    "hackernews": "learning",
}

# Unstop tags its own listings; trust the tag over our keyword guess.
_BY_TAG = {
    "hackathon": "hackathon", "internship": "internship",
    "scholarship": "scholarship", "competition": "contest",
}

# Keyword patterns, most specific FIRST — "fellowship" must win before "program" is even tried.
_PATTERNS = [
    ("ambassador", r"\b(campus ambassador|student ambassador|ambassador program|campus (?:lead|rep)"
                   r"|community (?:lead|champion)|evangelist|student partner)\b"),
    # "Residency" is ambiguous — Antler Residency is an accelerator, OpenAI Residency is a
    # fellowship. Startup runs first so an explicit accelerator signal settles it; anything
    # calling itself a residency with no startup wording falls through to fellowship.
    ("startup",    r"\b(accelerator|incubat(?:or|ion)|pre-?seed|venture|founders? program|cohort"
                   r"|demo day|y ?combinator|antler|techstars|pitch (?:competition|day))\b"),
    ("fellowship", r"\b(fellowship|fellows? program|\bfellow\b|residency)\b"),
    ("grant",      r"\b(grant|seed fund|funding (?:program|round|opportunity)|micro-?grant|bursary"
                   r"|sponsorship|startup india|birac|nidhi|meity|tide 2\.0|sisfs|prize money pool)\b"),
    ("scholarship", r"\b(scholarship|tuition|financial aid)\b"),
    ("hackathon",  r"\b(hackathon|hack ?fest|build-?athon|code ?fest|datathon|game ?jam|jam\b)\b"),
    ("research",   r"\b(research (?:intern|assistant|program)|paper|preprint|arxiv|thesis|lab\b)\b"),
    ("internship", r"\b(internship|intern\b|summer (?:analyst|associate)|co-?op)\b"),
    ("contest",    r"\b(contest|codeforces|leetcode|icpc|coding (?:round|challenge)|ctf)\b"),
]
_COMPILED = [(kind, re.compile(pat, re.I)) for kind, pat in _PATTERNS]


def kind_of(item) -> str:
    """The ONE category this opportunity belongs to. Never returns empty.

    Order of authority: explicit source > source-provided tag > keywords > "learning".
    Keywords run over title + description, so the Unstop enrichment (which finally gives us a
    real description) directly improves this classification too."""
    src = (getattr(item, "source", "") or "").lower()

    # An arxiv paper is research even if its title says "hackathon". The source is not a guess.
    if src in _BY_SOURCE and src not in ("github", "reddit", "hackernews"):
        return _BY_SOURCE[src]

    for t in (getattr(item, "tags", None) or []):
        if str(t).lower() in _BY_TAG:
            return _BY_TAG[str(t).lower()]

    text = f"{getattr(item, 'title', '')} {getattr(item, 'description', '')}"
    for kind, pat in _COMPILED:
        if pat.search(text):
            return kind

    return _BY_SOURCE.get(src, "learning")


def active() -> list[str]:
    """The focus kinds currently switched on. Empty list = hunting everything."""
    raw = getattr(config, "FOCUS", None) or []
    if isinstance(raw, str):
        raw = [p for p in re.split(r"[,\s]+", raw) if p]
    return [k for k in (str(x).strip().lower() for x in raw) if k in KINDS]


def apply(items: list) -> list:
    """Re-rank (and in "only" mode, filter) the pool around the active focus.

    Returns the surviving items. Mutates `score` and appends a `focus:*` tag, so both the
    ranking and the brief can see what happened. No focus set -> returns items untouched."""
    focus = active()
    if not focus:
        return items

    mode = str(getattr(config, "FOCUS_MODE", "boost")).lower()
    wanted = set(focus)
    kept = []
    for it in items:
        kind = kind_of(it)
        on_topic = kind in wanted

        if on_topic:
            it.score = min(10, it.score + BOOST)
            it.tags = list(it.tags or []) + [f"focus:{kind}"]
            kept.append(it)
            continue

        # Off-topic. In "only" mode it goes, unless it is too good to hide.
        if mode == "only" and it.score < KEEP_ANYWAY:
            continue
        it.score = max(0, it.score - PENALTY)
        it.tags = list(it.tags or []) + ["focus:off-topic"]
        kept.append(it)

    return kept


def describe() -> str:
    """One line for the brief, so a re-ranked list never looks like a broken one."""
    focus = active()
    if not focus:
        return ""
    mode = str(getattr(config, "FOCUS_MODE", "boost")).lower()
    verb = "showing only" if mode == "only" else "prioritising"
    return f"FOCUS: {verb} {', '.join(focus)}"


if __name__ == "__main__":
    from models import Opportunity

    cases = [
        (Opportunity("Some Paper on LLMs", "u", "arxiv", ""), "research"),
        (Opportunity("Claude Campus Ambassador Program", "u", "programs", "$3,600 stipend"), "ambassador"),
        (Opportunity("MLH Fellowship Summer", "u", "programs", "open source fellows"), "fellowship"),
        (Opportunity("Startup India Seed Fund Scheme", "u", "programs", "government funding"), "grant"),
        (Opportunity("Smart India Hackathon", "u", "unstop", "build", tags=["hackathon"]), "hackathon"),
        (Opportunity("Antler Residency India", "u", "programs", "accelerator cohort"), "startup"),
    ]
    for item, expected in cases:
        got = kind_of(item)
        assert got == expected, f"{item.title!r}: expected {expected}, got {got}"
    print(f"kind_of: {len(cases)}/{len(cases)} correct")
