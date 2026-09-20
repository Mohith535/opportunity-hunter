"""
Scorer — rule-based 1-10 relevance/urgency score (CLAUDE.md §6.2).

Phase 2 will add `ai_score_item()` (LLM scoring). The stub is here now so the
upgrade is "fill in the function", not "refactor everything". The *decision* of
what to do with a score lives in policy.py, not here.
"""

import re
from datetime import date

import config
from filters import focus

_INTEREST_RE = [re.compile(r"\b" + re.escape(k.lower()) + r"\b") for k in config.INTERESTS]
_COMPANY_RE = [re.compile(r"\b" + re.escape(k.lower()) + r"\b") for k in config.KNOWN_COMPANIES]
_REMOTE_RE = [re.compile(r"\b" + re.escape(k) + r"\b") for k in ("remote", "online")]
_STUDENT_RE = [re.compile(r"\b" + re.escape(k) + r"\b") for k in ("student", "intern", "internship")]
_MONEY_WORDS = [re.compile(r"\b" + re.escape(k) + r"\b") for k in ("prize", "stipend", "scholarship", "funded", "grant")]
_MONEY_SYMBOLS = ("$", "₹", "€", "£")

# config.INTERESTS mixes three different things: a DOMAIN ("machine learning"), an OPPORTUNITY
# TYPE ("internship", "hackathon") and a BRAND ("google"). That was fine while we only fetched
# ~8 items per source, but once intake widened it became the whole problem: "IT Sales
# Internship" earned the same +3 as "LLM Research Internship", because both contain the word
# "internship". Every non-technical role scored 5 and flooded the intake budget.
#
# So domain fit is scored SEPARATELY here. This does not touch config.INTERESTS, which the
# relevance gate and the LLM profile still use as-is.
_DOMAIN_RE = re.compile(
    r"\b(a\.?i\.?|ml\b|artificial intelligence|machine learning|deep learning|neural|computer vision|"
    r"nlp|natural language|llm|large language|generative|data scien|data analy|python|java|c\+\+|"
    r"software|developer|engineer(?:ing)?|programming|backend|back-end|frontend|front-end|"
    r"full[- ]stack|web dev|app dev|android|ios\b|cloud|devops|cyber ?security|blockchain|"
    r"robotics|iot\b|embedded|algorithm|open source|kaggle|competitive programming|"
    r"react|node|django|flask|sql|quantum|ctf|bug bounty|red team)\b",
    re.I)
# NOTE: "engineering" and "technical" are deliberately NOT domain terms. Unstop puts the
# eligibility blob ("courses: btech, engineering") into every description, so matching them
# marked a Digital Marketing internship as in-domain and it scored 10. Domain fit is now
# judged on the TITLE, where the role actually lives.

# Roles that are real jobs but not HIS field. Penalised only when nothing technical appears
# anywhere in the item, so "AI for Sales Hackathon" and "Marketing Analytics with Python"
# are untouched.
# Every alternative spells out its own endings. An earlier version used bare prefixes
# ("video edit", "content writ") inside a group closed by \b, which can never match
# "Video Editor" or "Content Writing" — so a Video Editor internship scored 10.
_OFF_DOMAIN_RE = re.compile(
    r"\b(sales|marketing|business development|bd executive|telesales|telemarketing|"
    r"tele ?call(?:er|ing)?|human resources|hr\b|recruit(?:er|ment|ing)?|talent acquisition|"
    r"content writ(?:er|ing)?|copywrit(?:er|ing)?|social media|graphic design(?:er|ing)?|"
    r"video edit(?:or|ing)?|photograph(?:er|y)?|account(?:s|ing|ant)|finance executive|"
    r"customer (?:support|service|success)|insurance|real estate|hospitality|"
    r"fashion|interior design(?:er)?)\b",
    re.I)
# Big enough to sink a non-technical role that has banked every generic bonus (deadline,
# remote, student, stipend). At 4 a Video Editor internship still outranked a real hackathon.
OFF_DOMAIN_PENALTY = 6

# Kinds that count as a genuine opportunity for a CSE/AI student. Ranking BETWEEN them is
# FOCUS's job, not this list's — all this does is stop a kind being punished for its naming.
OPPORTUNITY_KINDS = {"hackathon", "fellowship", "grant", "ambassador",
                     "scholarship", "startup", "contest", "internship", "research"}


def _any(patterns, text: str) -> bool:
    return any(p.search(text) for p in patterns)


def score_item(item) -> int:
    """Return an additive score capped at 10. Higher = more important."""
    score = 0
    title = item.title.lower()
    desc = item.description.lower()
    text = item.text

    if _any(_INTEREST_RE, title):
        score += 3
    if _any(_INTEREST_RE, desc):
        score += 2

    # Deadline urgency (only sources that actually carry a deadline benefit).
    if item.deadline:
        days_left = (item.deadline - date.today()).days
        if 0 <= days_left <= 7:
            score += 3
        elif days_left <= 30:
            score += 1

    if _any(_REMOTE_RE, text):
        score += 2
    if _any(_STUDENT_RE, text):
        score += 1
    if _any(_COMPANY_RE, text):
        score += 2
    if _any(_MONEY_WORDS, text) or any(sym in text for sym in _MONEY_SYMBOLS):
        score += 1

    # Level the naming asymmetry. "Internship" is itself one of config.INTERESTS, and an
    # internship is nearly always literally called "<Something> Internship" — so it banks +3
    # for the title and +2 for the description before anything relevant has been judged. A
    # hackathon is called "YODHA 2.0" or "NASA Space Apps Challenge" and earns none of it.
    # Measured on live Unstop data that gap alone put a Video Editor internship above the NASA
    # Space Apps Challenge, which is exactly the drift Mohith noticed. The kind comes from the
    # source's own tag, so this credits what the thing IS rather than what it is called.
    if not _any(_INTEREST_RE, title) and focus.kind_of(item) in OPPORTUNITY_KINDS:
        score += 3

    # Domain fit — the difference between an opportunity and an opportunity FOR HIM.
    # Both judgements are made on the TITLE: it is where the role is named, and it is the one
    # field no source pads with boilerplate.
    title_domain = bool(_DOMAIN_RE.search(title))
    if title_domain:
        score += 3
    elif _DOMAIN_RE.search(desc):
        score += 1   # domain only in the body: weaker evidence, smaller credit
    if _OFF_DOMAIN_RE.search(title) and not title_domain:
        score -= OFF_DOMAIN_PENALTY

    return max(0, min(score, 10))


# ─── PHASE 2 — LLM scoring ───────────────────────────────────────────
def ai_score_item(item) -> int:
    """Intelligently (re)score a single item via Gemini, in place.

    Returns the new ai_score, or -1 if LLM scoring was unavailable (no key,
    quota, SDK missing) — in which case policy.effective_score() keeps using the
    rule-based score. For batch scoring (the efficient path the pipeline uses)
    call filters.llm_scorer.score_items() directly.
    """
    from filters import llm_scorer
    from user_profile import load_profile

    llm_scorer.score_items([item], load_profile())
    return item.ai_score


if __name__ == "__main__":
    from datetime import timedelta

    from models import Opportunity

    samples = [
        Opportunity("Google Summer of Code 2026", "u", "devpost",
                    "Open source internship, remote, stipend provided for students.",
                    deadline=date.today() + timedelta(days=5)),
        Opportunity("Deep Learning paper on transformers", "u", "arxiv",
                    "A study of attention in machine learning."),
        Opportunity("Random local news", "u", "news", "nothing relevant here"),
    ]
    for s in samples:
        print(f"score={score_item(s):>2}  | {s.title}")
