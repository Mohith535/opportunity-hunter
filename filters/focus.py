"""
FOCUS — "what am I hunting *this week*?"

The hunter was built to answer one fixed question: what matters to Mohith in general. But
interest is seasonal. Some weeks the answer is hackathons; some weeks it is fellowships that
pay, or research, or government startup funding. Without a way to say so, every week is scored
by the same average of all his interests, and the thing he actually wants right now arrives
ranked below three papers and an internship.

This module adds that switch. `kind_of()` labels every item with ONE plain category, and
`apply()` re-ranks the pool around whichever categories are active.

Three modes:
  * "first" (DEFAULT) — what Mohith actually asked for: "if I need interns now, find me more
    interns, but if something else feels more important show it to me AFTER the interns." Focus
    kinds are ranked into their own zone at the top; everything else keeps its own honest score
    and appears in a second zone below. Nothing is boosted into a lie, nothing is hidden.
  * "boost" — one blended list: focus kinds gain, others lose. Use when you want a preference
    rather than a section break.
  * "only" — non-focus kinds are dropped... EXCEPT anything already scoring >= KEEP_ANYWAY.
    A mentor does not hide a once-a-year deadline because you said "hackathons today". The
    escape hatch is the whole reason this is safe to switch on.

Focus is never silent: every re-ranked item gets a `focus:<kind>` or `focus:off-topic` tag so
the brief can say why the order changed. Silent re-ranking is how you stop trusting your own tool.
"""

from __future__ import annotations

import re

import config

# The niches Mohith actually thinks in — his own words: intern, programs, government funding,
# research papers, news, jobs, hackathons, meetups. Deliberately flat: a taxonomy nobody can
# hold in their head is a taxonomy nobody will use.
KINDS = ("hackathon", "research", "internship", "job", "fellowship", "grant",
         "startup", "scholarship", "contest", "ambassador", "meetup", "program",
         "news", "learning")

# In "only" mode, an item this good is shown whatever the focus says.
KEEP_ANYWAY = 9

BOOST = 2     # focus kinds gain this
PENALTY = 2   # off-topic kinds lose this (boost mode only — "first" mode never penalises)

# Source -> kind, where the source alone SETTLES it. Checked before tags and keywords, because
# the source is a fact and a keyword is a guess: an arxiv paper titled "Hackathon Scaling Laws"
# is still a paper.
_AUTHORITATIVE = {
    "arxiv": "research",
    "devpost": "hackathon",
    "devfolio": "hackathon",
    "mlh": "hackathon",
    "clist": "contest",
    "internships": "internship",
}

# Source -> kind used only when tags and keywords found nothing. These sources carry mixed
# content, so the item's own words get first say.
_FALLBACK = {
    "github": "learning",
    "reddit": "news",
    "hackernews": "news",
    "programs": "program",   # a curated entry that is not a fellowship/grant/ambassador
    "ats": "job",            # company career boards (Greenhouse/Ashby/Lever)
}

# Unstop tags its own listings with the category it came from; trust that over a keyword guess.
_BY_TAG = {
    "hackathon": "hackathon", "internship": "internship", "job": "job",
    "scholarship": "scholarship", "competition": "contest", "quiz": "contest",
    "workshop": "meetup", "conference": "meetup",
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
    # Meetups before research: a "Technical Paper Presentation CONFERENCE" is an event to
    # attend, not a paper to read.
    ("meetup",     r"\b(meetup|conference|summit|webinar|workshop|bootcamp|devfest|"
                   r"tech ?talk|symposium|seminar|expo|unconference|barcamp|sprint day)\b"),
    ("research",   r"\b(research (?:intern|assistant|program)|paper|preprint|arxiv|thesis|lab\b)\b"),
    ("internship", r"\b(internship|intern\b|summer (?:analyst|associate)|co-?op)\b"),
    # Full-time roles. Kept AFTER internship so "Software Engineer Internship" stays an
    # internship — the thing he asked to hunt separately.
    ("job",        r"\b(full[- ]?time|new ?grad|graduate (?:trainee|engineer|programme?)|"
                   r"campus hire|fresher role|sde ?[12]?\b|software engineer \w*[12]\b|"
                   r"entry[- ]level|placement drive)\b"),
    ("contest",    r"\b(contest|codeforces|leetcode|icpc|coding (?:round|challenge)|ctf|quiz)\b"),
]
_COMPILED = [(kind, re.compile(pat, re.I)) for kind, pat in _PATTERNS]


def kind_of(item) -> str:
    """The ONE category this opportunity belongs to. Never returns empty.

    Order of authority: explicit source > source-provided tag > keywords > "learning".
    Keywords run over title + description, so the Unstop enrichment (which finally gives us a
    real description) directly improves this classification too."""
    src = (getattr(item, "source", "") or "").lower()

    # An arxiv paper is research even if its title says "hackathon". The source is not a guess.
    if src in _AUTHORITATIVE:
        return _AUTHORITATIVE[src]

    for t in (getattr(item, "tags", None) or []):
        if str(t).lower() in _BY_TAG:
            return _BY_TAG[str(t).lower()]

    text = f"{getattr(item, 'title', '')} {getattr(item, 'description', '')}"
    for kind, pat in _COMPILED:
        if pat.search(text):
            return kind

    return _FALLBACK.get(src, "learning")


def active() -> list[str]:
    """The focus kinds currently switched on. Empty list = hunting everything."""
    raw = getattr(config, "FOCUS", None) or []
    if isinstance(raw, str):
        raw = [p for p in re.split(r"[,\s]+", raw) if p]
    return [k for k in (str(x).strip().lower() for x in raw) if k in KINDS]


def is_on_topic(item) -> bool:
    """True when this item is one of the kinds currently being hunted."""
    return kind_of(item) in set(active())


def apply(items: list) -> list:
    """Re-rank (and in "only" mode, filter) the pool around the active focus.

    Returns the surviving items. Mutates `score` and appends a `focus:*` tag, so both the
    ranking and the brief can see what happened. No focus set -> returns items untouched."""
    focus = active()
    if not focus:
        return items

    mode = str(getattr(config, "FOCUS_MODE", "first")).lower()
    wanted = set(focus)
    kept = []
    for it in items:
        kind = kind_of(it)

        if kind in wanted:
            # "first" keeps the honest score — the zone split already puts these on top, so
            # boosting as well would distort the ranking WITHIN the zone for no benefit.
            if mode != "first":
                it.score = min(10, it.score + BOOST)
            it.tags = list(it.tags or []) + [f"focus:{kind}"]
            kept.append(it)
            continue

        # Off-topic. Only "only" mode drops it, and only when it is not too good to hide.
        if mode == "only" and it.score < KEEP_ANYWAY:
            continue
        if mode == "boost":
            it.score = max(0, it.score - PENALTY)
        it.tags = list(it.tags or []) + ["focus:off-topic"]
        kept.append(it)

    return kept


def split(items: list) -> tuple[list, list]:
    """(on_topic, everything_else) for the brief's two zones, each already sorted by the
    caller's ordering. Returns (items, []) when no focus is set, so callers can render the
    normal single-zone brief without branching twice."""
    if not active():
        return list(items), []
    on, off = [], []
    for it in items:
        (on if is_on_topic(it) else off).append(it)
    return on, off


def describe() -> str:
    """One line for the brief, so a re-ranked list never looks like a broken one."""
    focus = active()
    if not focus:
        return ""
    mode = str(getattr(config, "FOCUS_MODE", "first")).lower()
    verb = {"only": "showing only", "boost": "prioritising"}.get(mode, "hunting")
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
