"""
QUESTIONS — the application form's screening questions, drafted from his own evidence (4 Oct 2026).

His ask, with a screenshot of an Unstop form: "they are asking for the skill set and interview
questions too … in job.md, read the questions other than basic information … and generate me that."

Where the questions come from:
  * Greenhouse publishes a job's whole form: `boards-api.greenhouse.io/v1/boards/<b>/jobs/<id>?questions=true`
    (19 questions on an Anthropic posting, checked 4 Oct). Those are answered one by one.
  * Unstop's public API does NOT expose them — only `regnRequirements.screening_round: 1` — they appear
    in the logged-in form alone. There, the pack drafts the questions those forms ask most (the five in
    his 4 Oct screenshot), so the answers are ready before he opens the form.
Basic fields (name, email, phone, resume, demographics, consent) are skipped: he fills those once.

Every drafted answer is built from sentences already in career_profile.json, or says plainly that
only he can answer ("start date", "work authorisation", "expected stipend"). Never invented.
"""

from __future__ import annotations

import re

import requests

import config

BASIC = (r"first name|last name|full name|preferred name|^name\b|e-?mail|phone|mobile|resume|\bcv\b|cover letter|"
         r"linkedin|address|pronoun|gender|\brace\b|ethnic|veteran|disabilit|hispanic|how did you hear|"
         r"referr|privacy|consent|acknowledg|signature|date of birth|^school$|^degree$|^discipline$")

# The questions Unstop-style forms ask most — the five on his 4 Oct screenshot, plus the one every form has.
COMMON = [
    "How comfortable are you with Python?",
    "Have you built a backend API using FastAPI, Flask, Django, or a similar framework? Describe one project briefly.",
    "Have you previously integrated an LLM API such as OpenAI, Gemini, Claude, or Hugging Face into a project?",
    "Share your GitHub profile and/or portfolio link.",
    "If selected, when can you start?",
    "Why are you interested in this role?",
]


def greenhouse_questions(native: str) -> list[dict]:
    """[{q, required, options}] from a Greenhouse job's own form, basics removed. [] on any failure."""
    parts = (native or "").split(":")
    if len(parts) != 3 or parts[0] != "gh":
        return []
    try:
        j = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{parts[1]}/jobs/{parts[2]}?questions=true",
                         headers={"User-Agent": config.USER_AGENT}, timeout=25).json()
    except (requests.RequestException, ValueError):
        return []
    out = []
    for q in j.get("questions") or []:
        label = re.sub(r"<[^>]+>", "", q.get("label") or "").strip()
        if not label or re.search(BASIC, label.lower()):
            continue
        opts = [v.get("label", "") for f in q.get("fields") or [] for v in f.get("values") or [] if v.get("label")]
        out.append({"q": label, "required": bool(q.get("required")), "options": opts[:12]})
    return out


def _first(pool, pattern: str, n: int = 2) -> list[tuple[str, str]]:
    """Up to n sentences from different projects; `pattern` may be a list, tried in order of fit."""
    hits, seen = [], set()
    for pat in (pattern if isinstance(pattern, list) else [pattern]):
        for s, p in pool:
            if len(hits) >= n:
                return hits
            if re.search(pat, s.lower()) and p not in seen:
                hits.append((s, p))
                seen.add(p)
    return hits


def _join(hits) -> str:
    return " ".join(f"{p}: {s}" if p else s for s, p in hits)


def _level(lang: str, profile: dict) -> tuple[str, str]:
    items = [i for v in ((profile.get("x_resume") or {}).get("skill_groups") or {}).values() for i in v]
    it = next((i for i in items if re.match(re.escape(lang) + r"\b", i, re.I)), "")
    if "(advanced)" in it.lower():
        return "Advanced", f"your skills list says “{it}”"
    if it:
        return "Intermediate", f"“{it}” is on your skills list without a level — raise it only if you can defend it"
    return "", "not on your skills list"


def answer(q: str, profile: dict, match_rows: list | None = None, options: list | None = None) -> tuple[str, str]:
    """(drafted answer, why/basis). Answers starting "YOU" are his to give."""
    from .match import best_evidence, capabilities_in, evidence_pool  # noqa: PLC0415
    low = q.lower()
    pool = evidence_pool(profile)
    links = [l for l in (profile.get("x_resume") or {}).get("links") or [] if "@" not in l]

    m = re.search(r"\b(python|java|c\+\+|typescript|javascript|sql|c)\b", low)
    if m and re.search(r"comfortable|proficien|rate|level|experience with|familiar", low):
        lvl, why = _level(m.group(1), profile)
        if options and lvl:
            pick = next((o for o in options if lvl.lower() in o.lower()), "")
            lvl = pick or lvl
        return (lvl or "YOU ANSWER"), why
    if re.search(r"github|portfolio|website|\blink\b|url", low):
        return (" · ".join(links) or "YOU ANSWER"), "the links on your resume"
    # Before the backend rule: "an LLM API such as OpenAI…" contains "api", and was answered with
    # backend evidence until this moved up (4 Oct).
    if re.search(r"\bllm|openai|gemini|claude|hugging ?face|gpt|language model|genai|generative", low):
        hits = _first(pool, [r"bedrock", r"gemini|google adk", r"claude code", r"\bllm\b"], 2)
        if hits:
            return "Yes. " + _join(hits), "your verified project sentences"
    if re.search(r"backend|\bapi\b|fastapi|flask|django|server|endpoint", low):
        hits = _first(pool, [r"http\.server|/api/", r"rest api|get/put"], 2)
        if hits:
            lead = "Not with FastAPI, Flask or Django — " if re.search(r"fastapi|flask|django", low) and \
                not re.search(r"fastapi|flask|django", _join(hits).lower()) else ""
            return lead + _join(hits), "your verified project sentences (honest about which framework)"
    if re.search(r"\bstart\b|join|availab|notice period|earliest", low):
        return "YOU DECIDE — e.g. a date after your semester exams; you are in 2nd year, 3rd semester at SRM.", \
               "only you know your semester calendar"
    if re.search(r"authori[sz]|visa|sponsor|relocat|located|on-?site|in office|in-office|commute|hybrid", low):
        return "YOU ANSWER — you are based in Chennai, India (SRM, 2025–2029).", "a yes/no only you can give"
    if re.search(r"salary|compensation|stipend|expected pay|ctc", low):
        return "YOU DECIDE — your target floor is in hunt_target.json.", "a number only you should give"
    if re.search(r"\bwhy\b|interest|motivat|excite", low) and match_rows:
        asks = [(l, ev, p) for _, l, ev, p in match_rows if ev and not ev.startswith("(skills")][:2]
        if asks:
            what = " and ".join(f"“{l.rstrip('.')}”" for l, _, _ in asks)
            return (f"DRAFT — make it yours: it asks for {what}, which is the work I already do — "
                    + _join([(ev, p) for _, ev, p in asks[:1]])), "the posting's asks your evidence answers"
    for cap in capabilities_in(q):
        hit = best_evidence(cap, pool, set())
        if hit:
            return _join([hit]), f"your verified evidence for “{cap}”"
    return "YOU ANSWER — nothing in your verified profile fits this question.", "no evidence"


def section(item: dict, profile: dict, match_rows: list | None) -> list[str]:
    """job.md lines: the form's questions with drafted answers."""
    real = greenhouse_questions(str(item.get("native_id") or ""))
    qs = real or [{"q": q, "required": True, "options": []} for q in COMMON]
    head = ("These are this employer's own form questions (from its job-board API), basics removed."
            if real else
            "This site keeps its form questions behind login, so these are the ones such forms ask most. "
            "Copy, then edit — answers starting with YOU are yours to give.")
    L = ["## Screening questions — drafted from your evidence", "", f"_{head}_", ""]
    for q in qs[:20]:
        ans, why = answer(q["q"], profile, match_rows, q.get("options"))
        L += [f"**{q['q']}**{' *(required)*' if q.get('required') and real else ''}", "",
              f"> {ans}", "", f"<sub>{why}</sub>", ""]
    return L
