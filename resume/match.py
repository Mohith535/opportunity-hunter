"""
MATCH — what a posting asks for, mapped to the sentence in his own verified profile that shows it.

Why this exists (4 Oct 2026). Every pack OPH had built was 90–98% the same lines as every other pack,
because the only job-specific text came from a free model — and that model had been returning
nothing (a reasoning model given no room to finish; see filters/llm_scorer.REASONING_HEADROOM). He is
running on free tools on purpose, so tailoring must not depend on any model being up. This module does
the part a careful human tailor does first, deterministically:

  1. read the posting's requirement lines (or EDI's, which are guaranteed word-for-word)
  2. for each, find the capability it names and the sentence in his profile that proves it
  3. hand back bullets that QUOTE the requirement and answer it with his own verified words

Nothing here writes a new claim. Every evidence sentence is already in career_profile.json, so the
claim verifier passes it by construction; the quoted requirement is the employer's own words.
"""

from __future__ import annotations

import re

# capability: (pattern in a REQUIREMENT line, pattern in an EVIDENCE sentence). Order is priority when
# one requirement line names several things.
CAPABILITIES: list[tuple[str, str, str]] = [
    ("agentic", r"agentic|ai[- ]assisted|coding (assistant|harness|agent)|copilot|cursor|claude code|ai coding",
     r"claude code"),
    ("performance", r"performance|load times?|frame rates?|latency|optimi[sz]|faster|speed up|efficien",
     r"\d+\s*s\s*→\s*\d+\s*s|within about \d+ ms|quarter of its calls"),
    ("dsa", r"data structures|algorithms?|problem[- ]solving|leetcode|competitive programming",
     r"leetcode|advent of code"),
    ("games", r"\bgames?\b|gaming|game development|unity|unreal|gameplay", r"pygame|flappy|tic-tac-toe"),
    ("rest", r"\brest(ful)?\b|\bapis?\b|endpoints?|http", r"rest api|get/put|endpoint"),
    ("testing", r"\btest|quality|reliab|debug", r"\d+ tests|test that fails|automated checks|adversarial agent"),
    ("docs", r"documentation|document\b|readme|technical writing", r"readmes?|walkthrough|write-?up"),
    ("review", r"code reviews?|retrospectives?|pull requests?", r"reported upstream|bugs found"),
    ("learning", r"curiosity|targeted learning|learn quickly|self[- ]starter|eager to learn",
     r"benchmarked my own thesis|refuted"),
    ("creative", r"creative|innovat|novel ideas|out of the box", r"not one lets you|instead of deleting|sealed"),
    ("backend", r"backend|back-end|server|distributed|infrastructure|cloud", r"always-on|cloudflare worker|aws lambda"),
    ("ml", r"machine learning|\bml\b|deep learning|\bmodels?\b|\bllms?\b", r"benchmark|accuracy|escalation"),
    ("security", r"secur|privacy|encrypt|governance|compliance", r"sealed|public key|risk tiers|prompt-injection"),
    ("product", r"designers|product managers?|players?\b|user experience|\bux\b|customers?",
     r"mini app|rescue, not punishment|stranger on any device"),
]
# Concrete, checkable skills outrank soft ones on a page a recruiter skims for seconds.
_WEIGHT = {"agentic": 3, "performance": 3, "dsa": 3, "games": 2, "rest": 2, "ml": 2, "backend": 2,
           "security": 2}

# Headings that introduce asks: 0 qualifications, 1 bonus, 2 duties. A qualification is about the
# candidate, so it is answered first; a duty describes the job.
_SECTIONS = [(r"qualifications?|requirements?|what you (need|bring|have)|must have|who you are|you have", 0),
             (r"bonus|nice to have|preferred|plus\b|good to have", 1),
             (r"responsibilit|what you('ll| will) do|you will|day to day|key duties", 2)]
_STOP_SECTION = r"about (us|electronic|the company)|benefits|what this opportunity provides|equal opportunity|perks"
# Headings that start prose ABOUT the company or the role. EA's posting opens with "Description &
# Requirements" and then studio blurb; read as requirements, "Our teams are player-focused" became an ask.
_NEUTRAL = r"description|overview|our team|who we are|general information|about the (role|team)|the studio"


def requirement_lines(jd: str, packet_req: dict | None = None) -> list[tuple[int, str]]:
    """(priority, line) for every requirement-like line. EDI's packet, when there is one, is already
    word-for-word from the posting and wins."""
    if packet_req:
        out = [(0, s) for s in packet_req.get("must") or []]
        out += [(1, s) for s in packet_req.get("bonus") or []]
        out += [(2, s) for s in packet_req.get("responsibilities") or []]
        if out:
            return out
    out, prio = [], None
    for raw in (jd or "").splitlines():
        s = raw.strip().lstrip("-*•·–— ").strip()
        if not s:
            continue
        low = s.lower()
        if len(s) <= 60 and not s.endswith("."):
            if re.search(_STOP_SECTION, low) or re.search(_NEUTRAL, low):
                prio = None
                continue
            hit = next((p for pat, p in _SECTIONS if re.search(pat, low)), None)
            if hit is not None:
                prio = hit
                continue
        if prio is not None and 12 <= len(s) <= 220 and not s.endswith(":"):
            out.append((prio, s))
    return out or _prose_asks(jd)


# Most Unstop and career-board postings are prose with no "Qualifications" heading. There, an ask is a
# sentence addressed to the candidate — "You will…", "Experience with … is a plus" — never the blurb.
_ASK = r"\byou(?:'ll| will| have| are| care|r)?\b|experience (with|in)|knowledge of|familiar|proficien|" \
       r"understanding of|ability to|is a plus|required|preferred|must have"


def _prose_asks(jd: str) -> list[tuple[int, str]]:
    out = []
    for s in re.split(r"(?<=[.!?])\s+|\n+", jd or ""):
        s = s.strip().lstrip("-*•·–— ").strip()
        low = s.lower()
        if 12 <= len(s) <= 220 and re.search(_ASK, low) and not re.search(_STOP_SECTION, low):
            prio = 1 if re.search(r"is a plus|preferred|bonus|nice to have", low) else \
                0 if re.search(r"required|must|you have|experience (with|in)|proficien", low) else 2
            out.append((prio, s))
    return out


def capabilities_in(line: str) -> list[str]:
    low = line.lower()
    return [name for name, req, _ in CAPABILITIES if re.search(req, low)]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9“\"(])", text or "") if s.strip()]


def evidence_pool(profile: dict) -> list[tuple[str, str]]:
    """(sentence, project name or '') from everything he has verified: project highlights, the agentic
    line, community lines. Never from skills lists — a skill name is not evidence of doing anything."""
    pool: list[tuple[str, str]] = []
    x = profile.get("x_resume") or {}
    if x.get("agentic_line"):
        pool.append((re.sub(r"\s*\([^)]*\)\.?$", ".", x["agentic_line"]), ""))
    for p in profile.get("projects", []):
        name = p.get("x_resume_name") or ""
        if not name or not p.get("highlights"):
            continue
        if p.get("x_source") != "resume-2026-09" and not p.get("x_confirmed"):
            continue                       # only projects he has put on a resume or confirmed
        for h in p["highlights"]:
            for s in _sentences(h):
                pool.append((s, name))
    for c in x.get("community") or []:
        c = re.sub(r"^\*\*[^*]+:\*\*\s*", "", c)          # "**Writing and explaining:** …" — the label is ours
        for s in _sentences(c):
            pool.append((s[:1].upper() + s[1:], ""))
    return pool


def _score(sentence: str) -> int:
    """Prefer a sentence with a number in it, then a shorter one."""
    return (0 if re.search(r"\d", sentence) else 1) * 1000 + len(sentence)


def best_evidence(capability: str, pool: list[tuple[str, str]], used: set[str]) -> tuple[str, str] | None:
    """The evidence pattern's alternatives are in order of fit; an earlier one wins, length breaks ties.
    By length alone, "load times and frame rates" was answered with nova-cortex's "a quarter of its
    calls" (a cost saving, not a speed-up) instead of "218 s → 69 s", because it was shorter."""
    ev = next(e for n, _, e in CAPABILITIES if n == capability)
    for alt in ev.split("|"):
        hits = [(s, p) for s, p in pool if s not in used and re.search(alt, s.lower())]
        if hits:
            return min(hits, key=lambda sp: _score(sp[0]))
    return None


def _quote(line: str, limit: int = 95) -> str:
    """The requirement in the employer's words — a verbatim piece of it, never a paraphrase."""
    q = re.sub(r"^(you will|you'll|have an?|have|be able to|you have|demonstrated)\s+", "", line.strip(),
               flags=re.I).rstrip(".")
    if len(q) > limit:
        cut = q[:limit].rsplit(",", 1)[0] if "," in q[:limit] else q[:limit].rsplit(" ", 1)[0]
        q = cut.rstrip(" ,;")
    return q[:1].upper() + q[1:]


def _skill_cover(line: str, profile: dict) -> str:
    """A language or tool the requirement names that his skills list has. Weaker than a sentence of
    evidence, and shown as such ("skills: Java"), never turned into a bullet."""
    low = line.lower()
    items = [i for v in ((profile.get("x_resume") or {}).get("skill_groups") or {}).values() for i in v]
    hits = []
    for i in items:
        core = re.sub(r"\s*\(.*\)", "", i).strip().lower()
        if len(core) > 1 and re.search(r"(?<![a-z+#])" + re.escape(core) + r"(?![a-z+#])", low):
            hits.append(re.sub(r"\s*\(.*\)", "", i).strip())
    return ", ".join(hits)


def match(jd: str, profile: dict, packet_req: dict | None = None, limit: int = 4) -> dict:
    """{"bullets": [...], "rows": [(priority, requirement, evidence, project)], "caps": set}.
    Every requirement gets a row (the job.md table); the resume gets the `limit` strongest bullets —
    concrete skills first, weighted up when the posting keeps saying it (EA says "games" ~10 times)."""
    pool = evidence_pool(profile)
    jd_low = (jd or "").lower()
    used: set[str] = set()
    rows, cands, caps_done = [], [], set()
    for prio, line in sorted(requirement_lines(jd, packet_req), key=lambda r: r[0]):
        found, cap = None, ""
        for c in capabilities_in(line):
            if c in caps_done:
                continue
            found = best_evidence(c, pool, used)
            if found:
                cap = c
                caps_done.add(c)
                break
        if not found:
            cover = _skill_cover(line, profile)
            rows.append((prio, line, f"(skills: {cover})" if cover else "", ""))
            continue
        sentence, project = found
        used.add(sentence)
        rows.append((prio, line, sentence, project))
        lead = f"{project}: " if project and project.lower() not in sentence.lower()[:40] else ""
        req_pat = next(r for n, r, _ in CAPABILITIES if n == cap)
        weight = _WEIGHT.get(cap, 1) + min(2, len(re.findall(req_pat, jd_low)) // 3)
        cands.append((-weight, prio, len(cands), f"**“{_quote(line)}.”** {lead}{sentence}"))
    bullets = [b for *_, b in sorted(cands)[:limit]]
    return {"bullets": bullets, "rows": rows, "caps": caps_done}


def order_highlights(highlights: list[str], caps: set[str], jd_low: str) -> list[str]:
    """Within one project, the bullet that answers what this posting asks for goes first."""
    def weight(h: str) -> int:
        low = h.lower()
        w = sum(3 for n, _, ev in CAPABILITIES if n in caps and re.search(ev, low))
        w += sum(1 for word in set(re.findall(r"[a-z][a-z+#-]{5,}", low)) if word in jd_low)
        return w
    return sorted(highlights, key=lambda h: -weight(h))


def changed_lines(md: str, base_md: str) -> tuple[int, int]:
    """(lines in md that are not in the base resume, non-blank lines in md) — "Changed for this job"."""
    lines = [l.strip() for l in (md or "").splitlines() if l.strip() and not l.strip().startswith("<!--")]
    base = {l.strip() for l in (base_md or "").splitlines() if l.strip()}
    return sum(1 for l in lines if l not in base), len(lines)


if __name__ == "__main__":
    jd = """Description & Requirements
Our teams are player-focused and motivated to deliver quality.
Qualifications
Have a solid foundation of data structures and algorithms
Be able to use modern Agentic AI coding harnesses
Bonus:
Demonstrated understanding of RESTful API
About Electronic Arts
We make games for everyone."""
    req = requirement_lines(jd)
    assert [p for p, _ in req] == [0, 0, 1], req
    assert not any("player-focused" in l or "We make games" in l for _, l in req), "blurb is not an ask"
    assert capabilities_in("Be able to use modern Agentic AI coding harnesses") == ["agentic"]
    assert _quote("You will improve code for performance, focusing on reducing load times and improving "
                  "frame rates.").startswith("Improve code for performance")
    print("match.py self-check ok")
