"""
Resume Generator — render a real, ATS-safe resume from your `career_profile.json`.

This was rebuilt after an honest failure: the first version produced a thin, generic resume that was
far worse than the one the user had written by hand. Three root causes, all fixed here:

  1. **Impoverished data.** GitHub descriptions + certificate filenames can't see education, awards,
     programs, or that TaskFlow is "3200+ lines across 8 versions grounded in behavioural research".
     Fixed upstream: `resume/ingest.py` reads your existing résumé into the profile.
  2. **It replaced good content with generic prose.** The model was rewriting rich, specific bullets
     into vague ones. Now: where the profile holds REAL bullets, they are preserved — the model may
     only reorder and mirror the job's language, and is explicitly forbidden from dropping a specific.
  3. **No sense of significance.** It listed practice repos (HelloApp, week-N exercises). Research on
     new-grad resumes is blunt: a tutorial/practice project is rarely persuasive and costs you space.
     Those are now filtered out unless the résumé itself features them.

Grounded in what the evidence actually says about resumes:
  * Recruiters spend ~7.4 seconds on the first pass and fixate on name → title → dates → education,
    and they look LONGER at simple layouts with clear section headings. So: single column, standard
    headings, no tables/columns/graphics.
  * ATS match keywords literally, not by synonym — so the job's own words are mirrored where truthful.
  * Strong bullets follow XYZ / STAR: action verb + what you did + the tech + a measurable result.

Everything stays honest: only real content, no invented metrics, and every section traces to the
profile. Output is Markdown → export to a single-column PDF.
"""

from __future__ import annotations

import re

from filters.llm_scorer import complete
from .profile import facts_drift, load_profile_json, relevant_projects
from .verify import LEXICON, _present, jd_gaps, verify
from .voice import VOICE_RULES, bold_budget, drop_banned, lint

_DISPLAY = {
    "aws": "AWS", "sql": "SQL", "llm": "LLM", "llms": "LLMs", "api": "API", "rest api": "REST APIs",
    "rest apis": "REST APIs", "ui/ux": "UI/UX", "html": "HTML", "css": "CSS", "gcp": "GCP",
    "nlp": "NLP", "ci/cd": "CI/CD", "javascript": "JavaScript", "typescript": "TypeScript",
    "mysql": "MySQL", "postgresql": "PostgreSQL", "github": "GitHub", "github actions": "GitHub Actions",
    "google cloud": "Google Cloud", "generative ai": "Generative AI", "machine learning":
    "Machine Learning", "deep learning": "Deep Learning", "prompt engineering": "Prompt Engineering",
    "data analytics": "Data Analytics", "security copilot": "Security Copilot", "critical thinking":
    "Critical Thinking", "mcp": "MCP", "eda": "EDA", "oop": "OOP", "cli": "CLI", "dns": "DNS",
    "json": "JSON", "ai agents": "AI Agents", "c++": "C++", "c": "C", "java": "Java",
}
# Practice/tutorial repos actively cost you space on a resume (per new-grad resume research).
_PRACTICE = re.compile(r"(practice|week\s*\d|hello[-_ ]?(app|world)|tutorial|demo|sample|assignment"
                       r"|test[-_]?repo|learning|exercise|banner)", re.I)
# Certificate entries that aren't credentials.
_CERT_NOISE = ("interview tip", "snippet", "application", "proof", "confirmation", "screenshot")


_DISPLAY.update({
    "adk": "ADK", "google adk": "Google ADK", "ai": "AI", "ai safety": "AI Safety", "api": "API",
    "cloudflare": "Cloudflare", "cockroachdb": "CockroachDB", "gemini": "Gemini", "ux": "UX",
    "ui": "UI", "hci": "HCI", "rag": "RAG", "iot": "IoT", "gpu": "GPU", "ci": "CI",
    "telegram bot api": "Telegram Bot API", "multi-agent": "Multi-agent",
})


def _pretty(skill: str) -> str:
    """Display form of a skill. A recruiter reads "Cli, Nlp, Mcp, Typescript" as careless.

    Two bugs, both from a live resume: the lookup was case-SENSITIVE, so an already-correct
    "TypeScript" missed the table; and str.capitalize() lowercases everything after the first
    letter, so it then became "Typescript". Now: case-insensitive lookup, and a word that already
    carries internal capitals is left exactly as written."""
    low = skill.lower().strip()
    if low in _DISPLAY:
        return _DISPLAY[low]

    def word(w: str) -> str:
        if w.lower() in _DISPLAY:
            return _DISPLAY[w.lower()]
        if any(c.isupper() for c in w[1:]):      # TypeScript, GitHub, iOS — already deliberate
            return w
        return w[:1].upper() + w[1:]
    return " ".join(word(w) for w in skill.split())


# ─── selection ───────────────────────────────────────────────────────
def _skills_ordered(profile: dict, jd_keywords: list[str], limit: int = 22) -> list[str]:
    names = [s["name"] for s in profile.get("skills", [])]
    if jd_keywords:
        kws = {k.lower().strip() for k in jd_keywords if k.strip()}
        matched = [s for s in names if any(k and (k in s or s in k) for k in kws)]
        names = matched + [s for s in names if s not in matched]
    return [_pretty(s) for s in names[:limit]]


def _pick_projects(profile: dict, jd_keywords: list[str], limit: int = 5) -> list[dict]:
    """Significance first, then job relevance.

    A project the résumé already features (it has real bullets) outranks a bare repo, and practice
    repos are excluded — they dilute the page.
    """
    projects = [p for p in profile.get("projects", [])
                if p.get("highlights") or not _PRACTICE.search(p.get("name") or "")]
    featured = [p for p in projects if p.get("highlights")]
    described = [p for p in projects if not p.get("highlights") and (p.get("description") or "").strip()]

    if jd_keywords:
        relevant = {(p.get("name") or "") for p in relevant_projects(profile, jd_keywords, 12)}
        featured.sort(key=lambda p: (p.get("name") not in relevant,))
        described.sort(key=lambda p: (p.get("name") not in relevant,))
    return (featured + described)[:limit]


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", (s or "").lower()) if len(w) > 2}


def _pick_certs(profile: dict, jd_keywords: list[str], limit: int = 8) -> list[dict]:
    certs = [c for c in profile.get("certificates", [])
             if not any(n in c.get("name", "").lower() for n in _CERT_NOISE)]
    # Résumé-sourced certificates carry issuer + date — richer, so prefer them.
    certs.sort(key=lambda c: (c.get("x_source") != "resume",))
    # Drop folder-derived duplicates of a richer résumé entry ("Google Cloud Best of Next" when
    # "Google Cloud Asia Pacific Best of Next '26 — Google · May 2026" is already present).
    award_toks = [_tokens(a.get("title", "")) for a in profile.get("awards", [])]
    kept: list[dict] = []
    for c in certs:
        toks = _tokens(c.get("name", ""))
        if c.get("x_source") != "resume" and toks:
            # already covered by a richer résumé entry…
            if any(len(toks & _tokens(k.get("name", ""))) >= max(2, len(toks) - 1) for k in kept):
                continue
            # …or it's really a programme already listed under Selections & Programs.
            if any(len(toks & a) >= max(2, len(toks) - 1) for a in award_toks if a):
                continue
        kept.append(c)
    certs = kept
    if jd_keywords:
        kws = {k.lower() for k in jd_keywords}
        certs.sort(key=lambda c: (not any(k in c.get("name", "").lower() for k in kws),))
    return certs[:limit]


# ─── LLM polish (fact-bound) ─────────────────────────────────────────
_PROMPT = """You are an expert technical resume writer. Write two sections for {name}'s resume using
ONLY the real facts below. This resume must survive an interview where every line is questioned.

ABSOLUTE RULES:
- NEVER invent metrics, tools, employers, dates or achievements.
- RESUME VOICE: no pronouns, no third person, never the candidate's own name. Resume convention is
  implied first person — "2nd-year B.Tech CSE student who ships…", never "He is…" or "Mohith is…".
- For each project listed under NEEDS A BULLET, write ONE factual bullet from its description and
  tech. If there is genuinely nothing to say, skip that project entirely.
- Never output bracketed instructions or placeholder text of any kind.

STYLE (what the evidence says works):
- Each bullet: strong action verb + what you built + the tech + a measurable result (XYZ / STAR shape).
  No "responsible for", no "helped with".
- Mirror the job description's exact terms ONLY where they already appear in the FACTS below. A term
  that is in the job ad but not in the FACTS must not appear at all — not even as "familiar with".
  Every skill you write is checked against the FACTS afterwards, and any sentence naming one the
  FACTS do not contain is deleted.
- Student/early-career framing: confident, never inflated.

{voice}

Output EXACTLY these two blocks and nothing else:

SUMMARY:
<3 lines, no pronouns. Open on the problem his work solves, then the strongest proof (a real project
or selection, with one of his real numbers), then the skills from the FACTS that this job also asks
for. Do NOT end with a goal or "seeking" line. Concrete, no adjective soup.>

BULLETS:
<one line per project listed under NEEDS A BULLET, formatted exactly:
"<Project Name> :: <the single bullet>">

--- FACTS ---
Name: {name}
Background: {about}
Selections / programs: {awards}
Top skills: {skills}
Already-written projects (context only — do NOT rewrite these):
{featured}
NEEDS A BULLET (write one each):
{bare}
{jd_block}
"""


def _enhance(profile: dict, featured: list[dict], bare: list[dict],
             jd_text: str | None) -> dict | None:
    """Summary + one bullet per bullet-less project.

    Deliberately narrow: projects that already carry the candidate's own bullets are passed as
    CONTEXT ONLY and never rewritten. A model paraphrasing a good bullet silently destroys specifics
    (a live run turned "blue→amber→red" into "blue-amber-fired"), so those go in verbatim instead.
    """
    basics = profile.get("basics", {})
    declared = profile.get("x_declared", {})
    feat = "\n".join(f"- {p.get('x_resume_name') or p['name']}: "
                     f"{'; '.join((p.get('highlights') or [])[:2])[:220]}" for p in featured)
    bar = "\n".join(f"- {p['name']} (tech: {', '.join((p.get('keywords') or [])[:5]) or 'n/a'}): "
                    f"{p.get('description') or '(no description)'}" for p in bare)
    awards = "; ".join(f"{a.get('title')} ({a.get('awarder','')})" for a in profile.get("awards", [])[:6])

    out = complete(_PROMPT.format(
        voice=VOICE_RULES,
        name=basics.get("name", "Candidate"),
        about=" ".join(x for x in [declared.get("identity", ""), basics.get("summary", "")] if x)[:600],
        awards=awards or "(none)",
        skills=", ".join(_skills_ordered(profile, [], 24)),
        featured=feat or "(none)", bare=bar or "(none)",
        jd_block=(f"\n--- JOB DESCRIPTION (mirror its language where true) ---\n{jd_text[:2500]}"
                  if jd_text else "")), max_tokens=1200, temperature=0.3)
    if not out:
        return None

    bullets: dict[str, str] = {}
    for line in _clean(_block(out, "BULLETS", ("SUMMARY",))).splitlines():
        if "::" in line:
            k, v = line.split("::", 1)
            bullets[k.strip().lstrip("-* ").lower()] = v.strip()
    return {"summary": _block(out, "SUMMARY", ("BULLETS",)), "bullets": bullets}


def _block(text: str, name: str, nexts: tuple[str, ...]) -> str:
    m = re.search(rf"{name}:\s*(.*?)(?=\n(?:{'|'.join(nexts)}):|\Z)", text, re.S | re.I)
    return m.group(1).strip() if m else ""


def _clean(text: str) -> str:
    """Strip any leaked instruction placeholders — a real bug seen in live output."""
    text = re.sub(r"\[\s*(add|insert|write)\s+description[^\]]*\]", "", text, flags=re.I)
    return "\n".join(ln for ln in text.splitlines()
                     if not re.search(r"only the given tech|placeholder|<.*?>", ln, re.I)).strip()


# ─── the 3-second resume ─────────────────────────────────────────────
# Layout decisions below each trace to a finding, so none of them is taste:
#
#  * TheLadders eye-tracking (2018; 30 recruiters): 7.4 s on the first pass, 80% of it on six data
#    points — name, current title/company, previous title/company, their dates, and education. A
#    student has no current title, so that fixation slot gets his own HEADLINE, and the education
#    line with the graduation year goes in the header, where a knockout check can answer it in one
#    glance instead of hunting to the bottom.
#  * Nielsen Norman Group: readers scan in an F / "layer-cake" pattern — headings, bold, and the
#    first words of each line. So every project opens with its name and a one-line tagline, and the
#    most relevant project goes FIRST, where the top bar of the F lands.
#  * NN/g: numerals stop the scanning eye ("23" beats "twenty-three"). His bullets already carry real
#    ones (190 tests, 12 ms vs 250 ms, 17 typed MCP tools); nothing is reworded away from them.
#  * von Restorff (isolation) effect: the one item that differs is the one remembered. At most ONE
#    emphasised phrase per project — bold everything and nothing stands out.
#  * Oppenheimer (2006): plain words are judged MORE intelligent. His own words go in verbatim; the
#    model writes one tailoring sentence and nothing else.
#  * Peak-end rule: an experience is remembered by its peak and its end. The page ends on his own
#    closing line rather than on a certification list.

_TAILOR_LINE = """{voice}

Write ONE sentence (at most 30 words) to end this candidate's resume summary. It connects his real
work below to this specific role. It must use ONLY facts from FACTS. Do not name any skill, tool or
domain that is not in FACTS. Do not claim any experience with the employer or its products. No
"seeking", no "passionate", no "excited", no "I am". Plain words.

Output exactly one line:
LINE: <the sentence>

--- ROLE ---
{role}
{jd}

--- FACTS ---
{facts}
"""


def _jd_low(jd_text: str | None, role: str) -> str:
    return f"{role} {jd_text or ''}".lower()


# Role family -> (words that identify it in a job ad, what a project shows when it fits).
# Exact term overlap alone ranked NitroWatch first for a Data Science & ML role, because none of his
# write-ups literally says "machine learning" — nova-cortex says "benchmarked", "model's accuracy",
# "corpus". The F-pattern means the first project gets the most attention, so it has to be the one
# this job would care about most. Psychology/UX is a family of its own because he asked for it:
# TaskFlow is behavioural science, and for those roles it should lead.
_AFFINITY = {
    "ml": (r"machine learning|\bml\b|data scien|deep learning|\bai\b|artificial intelligence|llm|nlp"
           r"|model",
           ["benchmark", "accuracy", "model", "llm", "evaluation", "corpus", "escalation", "agents"]),
    "backend": (r"backend|back-end|server|api|database|distributed|infrastructure|cloud",
                ["always-on", "lambda", "database", "cockroachdb", "serializable", "server", "delete"]),
    "web": (r"frontend|front-end|full[- ]stack|web|react|typescript|javascript",
            ["typescript", "web app", "browser", "cloudflare", "extension", "live"]),
    "security": (r"secur|governance|safety|trust|compliance|audit|permission",
                 ["permission", "governance", "audit", "risk tier", "prompt-injection", "adversarial"]),
    "psych": (r"ux|user research|hci|human.computer|psycholog|behavio|cognitive|product design",
              ["behavioural", "behavioral", "research", "willpower", "judged", "zeigarnik",
               "self-report", "anxiety"]),
    "data": (r"data analy|analytics|dashboard|sql|statistic|insight",
             ["benchmark", "accuracy", "corpus", "measures", "tests"]),
}


def _relevance(p: dict, jd_low: str) -> int:
    """How much of this project the job asks about. Deterministic: role-family fit counts 4 per
    matching signal, shared lexicon terms 3, other shared long words 1. His own ordering breaks
    ties, since it is his own ranking of significance."""
    text = " ".join([p.get("x_tagline") or "", p.get("x_techline") or "",
                     *(p.get("highlights") or []), *(p.get("keywords") or [])]).lower()
    score = 0
    for pattern, signals in _AFFINITY.values():
        if re.search(pattern, jd_low):
            score += 4 * sum(1 for s in signals if s in text)
    score += 3 * sum(1 for t in LEXICON if _present(t, text) and _present(t, jd_low))
    words = {w for w in re.findall(r"[a-z][a-z+#.-]{4,}", jd_low)} - _STOP
    score += sum(1 for w in words if w in text)
    return score


_STOP = {"about", "their", "there", "which", "would", "should", "could", "these", "those", "other",
         "while", "where", "within", "without", "across", "using", "based", "strong", "ability",
         "including", "working", "experience", "skills", "team", "teams", "years", "role",
         "candidate", "candidates", "company", "opportunity", "please", "apply", "internship",
         "intern", "student", "students", "looking", "join", "help", "build", "work"}


def _tailor_line(profile: dict, x: dict, projects: list[dict], jd_text: str, role: str) -> str:
    facts = "\n".join([x.get("summary_core", ""),
                       *[f"- {p.get('x_resume_name')}: {p.get('x_tagline')} ({p.get('x_techline')})"
                         for p in projects],
                       "Skills: " + "; ".join(f"{g}: {', '.join(v)}"
                                              for g, v in (x.get("skill_groups") or {}).items())])
    out = complete(_TAILOR_LINE.format(voice=VOICE_RULES, role=role or "(not given)",
                                       jd=(jd_text or "")[:1800], facts=facts),
                   max_tokens=160, temperature=0.3)
    m = re.search(r"LINE:\s*(.+)", out or "")
    return m.group(1).strip().strip('"') if m else ""


_ROLE_SECTION = """{voice}

Write at most 3 bullets for a resume section titled "What I would bring to {company}".
Each bullet connects ONE thing this job asks for (in the job's own words) to ONE specific real
project or fact from FACTS, with its real number if it has one. Shape: "<what the job needs> — <the
real project that shows it, and what it did>".
Only facts from FACTS. Never claim a skill, tool or experience that is not in FACTS, even to match the
job. No "passionate", no "excited", no "seeking", no "I am".
Output only the bullets, one per line, each starting with "- ".

--- JOB ---
{role}
{jd}

--- FACTS ---
{facts}
"""


def _role_section(profile: dict, x: dict, projects: list[dict], jd_text: str, role: str,
                  company: str, report: dict) -> list[str]:
    """Up to 3 bullets mapping what THIS job asks for to his real work — his Claude Ambassador resume
    had exactly this ("What I would do as a Claude Campus Ambassador"), and it is the one section that
    says "I want this job" rather than "I want a job".

    It is also the riskiest text a model writes here, so every bullet must pass the verifier and the
    voice linter individually, and the section appears only if at least TWO survive. One lonely
    bullet reads as padding; none is better than that."""
    if len((jd_text or "").strip()) < 300:
        return []                     # a job blurb is not enough to map requirements honestly
    facts = "\n".join(
        [x.get("summary_core", "")] +
        [f"- {p.get('x_resume_name')}: {p.get('x_tagline')}. " + " ".join(p.get("highlights") or [])[:420]
         for p in projects])
    out = complete(_ROLE_SECTION.format(voice=VOICE_RULES, company=company or "this role",
                                        role=role or "", jd=jd_text[:2200], facts=facts),
                   max_tokens=420, temperature=0.3)
    kept = []
    for line in (out or "").splitlines():
        b = line.strip().lstrip("-*• ").strip()
        if len(b) < 25:
            continue
        b, banned = drop_banned(b)
        v = verify(b, profile)
        report["removed"] += v.removed
        report["unverified_terms"] += v.unverified_terms
        report["unverified_numbers"] += v.unverified_numbers
        report["banned"] += banned
        if v.text:
            kept.append(v.text)
    return kept[:3] if len(kept) >= 2 else []


def _names(text: str) -> set[str]:
    """Distinctive named things in a line: acronym-ish or mixed-case tokens ("GSSoC", "SSoC", "NVIDIA",
    "NitroStack"), which is what two bullets about the same thing share. Ordinary capitalised words
    ("Open", "Campus") do not count."""
    toks = re.findall(r"\b[A-Za-z][A-Za-z0-9]*[A-Z][A-Za-z0-9]*\b", re.sub(r"\*", "", text or ""))
    return {t.lower() for t in toks if not t.istitle() or len(t) <= 3}


def _drop_repeats(bullets: list[str], elsewhere: list[str]) -> list[str]:
    """Remove a bullet that only repeats what another section already says.

    His resume listed GSSoC and SSoC twice — once under Campus & Community, once under Programs &
    Selections. A recruiter reads the second one as padding, and on a page he called congested it was
    two lines of pure repetition. A bullet goes when two or more of its distinctive names already
    appear together in one line elsewhere; the Programs line, being the selection itself, is kept."""
    other = [_names(e) for e in elsewhere]
    kept = []
    for b in bullets:
        mine = _names(b)
        if len(mine) >= 2 and any(len(mine & o) >= 2 and len(mine & o) >= len(mine) - 1 for o in other):
            continue
        kept.append(b)
    return kept


def _skills_block(groups: dict, jd_low: str) -> list[str]:
    """His four skill groups, in his order, with the items this job mentions moved to the front
    of each group — the first words of a line are what the F-pattern reader actually sees."""
    lines = []
    for name, items in (groups or {}).items():
        # Whole-word matches only, and never a one-letter item: a plain substring test promoted "C"
        # above "Python (advanced)" because every job ad contains the letter c.
        def asked(i: str) -> bool:
            core = re.sub(r"\s*\(.*\)", "", i).strip().lower()
            if len(core) < 2:
                return False
            return _present(core, jd_low) or any(
                _present(t, jd_low) and _present(t, i.lower()) for t in LEXICON if len(t) > 1)
        hit = [i for i in items if asked(i)]
        rest = [i for i in items if i not in hit]
        lines.append(f"**{name}:** " + " · ".join(hit + rest))
    return lines


def _from_resume_layer(profile: dict, jd_text: str | None, role: str, report: dict,
                       company: str = "") -> str:
    x = profile["x_resume"]
    basics = profile.get("basics", {})
    jd_low = _jd_low(jd_text, role)

    featured = [p for p in profile.get("projects", []) if p.get("x_source") == "resume-2026-09"]
    order = {id(p): n for n, p in enumerate(featured)}
    featured.sort(key=lambda p: (-_relevance(p, jd_low), order[id(p)]))

    # ── the 3-second zone: name, headline, links, the knockout line ──────────────────────
    L = [f"# {basics.get('name') or 'K MOHITH KANNAN'}", f"**{x.get('headline','')}**"]
    L.append(" · ".join(x.get("links") or []))
    srm = next((e for e in profile.get("education", []) if "srm" in (e.get("institution") or "").lower()), None)
    if srm:
        L.append(f"B.Tech CSE (AI & ML) · SRM Institute of Science and Technology · "
                 f"{srm.get('startDate')}–{srm.get('endDate')}")

    # ── summary: his words, plus ONE verified tailoring sentence ─────────────────────────
    summary = x.get("summary_core", "")
    if jd_text or role:
        line = _tailor_line(profile, x, featured, jd_text or "", role)
        if line:
            line, banned = drop_banned(line)
            v = verify(line, profile)
            report["removed"] += v.removed
            report["unverified_terms"] += v.unverified_terms
            report["unverified_numbers"] += v.unverified_numbers
            report["banned"] += banned
            if v.text:
                summary = f"{summary} {v.text}"
                report["tailor_line"] = v.text
    L += ["", "## Summary", summary]

    # ── projects: most relevant first; his bullets verbatim; one emphasis per project ──────
    # Headed "Projects", not his "Selected Work": older parsers classify sections by heading
    # words, and resume.ats flagged the creative label on our own output. Content unchanged.
    L += ["", "## Projects"]
    for p in featured:
        L.append(f"**{p.get('x_resume_name')}** — {p.get('x_tagline','')} · *{p.get('x_when','')}*")
        block = "\n".join(f"- {h}" for h in p.get("highlights") or [])
        L.append(bold_budget(block))
        if p.get("x_techline"):
            link = (p.get("url") or "").replace("https://", "")
            L.append(f"*{p['x_techline']}*" + (f" · {link}" if link and "github" in link else ""))
        L.append("")

    if jd_text:
        role_bullets = _role_section(profile, x, featured, jd_text, role, company, report)
        if role_bullets:
            L += [f"## What I would bring to {company or 'this role'}",
                  *[f"- {b}" for b in role_bullets], ""]
            report["role_section"] = role_bullets

    if x.get("community"):
        community = _drop_repeats(x["community"], x.get("programs") or [])
        L += ["## Campus & Community", *[f"- {c}" for c in community], ""]
    if x.get("programs"):
        L += ["## Programs & Selections", *[f"- {c}" for c in x["programs"]], ""]
    if x.get("certifications_line"):
        L += ["## Certifications — 15+, selected", x["certifications_line"], ""]
    if x.get("skill_groups"):
        L += ["## Technical Skills", *_skills_block(x["skill_groups"], jd_low), ""]

    L += ["## Education"]
    for e in profile.get("education", []):
        when = "–".join(v for v in [e.get("startDate"), e.get("endDate")] if v)
        extra = " · ".join(v for v in [when, e.get("note")] if v)
        # "(SRMIST) — B.Tech — Computer Science…" stacked two dashes; his own resume writes
        # "B.Tech, CSE (…)". One dash separates the school from the degree, nothing else.
        study = re.sub(r"\s+—\s+", ", ", e.get("studyType", "") or "")
        L.append(f"- **{e.get('institution','')}** — {study}" + (f" · {extra}" if extra else ""))

    if x.get("closing"):
        L += ["", f"*{x['closing']}*"]
    return "\n".join(L)


# ─── assemble ────────────────────────────────────────────────────────
def generate_resume(profile: dict, jd_text: str | None = None, role: str = "", company: str = "") -> str:
    """Backwards-compatible: just the Markdown. Use generate_resume_ex() for the report."""
    return generate_resume_ex(profile, jd_text, role, company)[0]


def generate_resume_ex(profile: dict, jd_text: str | None = None, role: str = "",
                       company: str = "") -> tuple[str, dict]:
    """(markdown, report). The report says what the verifier removed, which job skills you do not
    have yet, voice problems, and where facts.yml has moved on from the profile.

    With a transcribed resume layer (x_resume) the resume is built from HIS words, and the model
    writes a single verified sentence. Without one, the older path runs — now also verified."""
    report = {"removed": [], "unverified_terms": [], "unverified_numbers": [], "banned": [],
              "gaps": jd_gaps(f"{role} {jd_text or ''}", profile) if (jd_text or role) else [],
              "drift": facts_drift(profile), "lint": [], "tailor_line": "", "role_section": []}
    if profile.get("x_resume"):
        md = _from_resume_layer(profile, jd_text, role, report, company)
    else:
        md = _legacy_resume(profile, jd_text, report)
    report["lint"] = lint(md)
    for k in ("unverified_terms", "unverified_numbers", "banned"):
        report[k] = sorted(set(report[k]))
    return md, report


def _legacy_resume(profile: dict, jd_text: str | None, report: dict) -> str:
    from .analyzer import extract_jd_keywords  # noqa: PLC0415
    jd_keywords = extract_jd_keywords(jd_text) if jd_text else []

    basics = profile.get("basics", {})
    name = basics.get("name") or "Your Name"
    contact = [basics.get("email"), basics.get("phone")] + \
              [p.get("url") for p in basics.get("profiles", []) if p.get("url")]
    contact = [c for c in contact if c] or ["[add email]"]

    projects = _pick_projects(profile, jd_keywords)
    featured = [p for p in projects if p.get("highlights")]
    bare = [p for p in projects if not p.get("highlights")]
    enh = _enhance(profile, featured, bare, jd_text)

    top_skills = _skills_ordered(profile, jd_keywords)
    summary = ""
    if enh and enh["summary"]:
        # The model's summary is a request, not a fact. Banned phrasing out, then every claim and
        # number checked against the profile; unbacked sentences are dropped and reported.
        cleaned, banned = drop_banned(enh["summary"])
        v = verify(cleaned, profile, jd_keywords)
        report["removed"] += v.removed
        report["unverified_terms"] += v.unverified_terms
        report["unverified_numbers"] += v.unverified_numbers
        report["banned"] += banned
        summary = v.text
    if not summary:
        summary = ((profile.get("x_declared", {}).get("identity", "") or "") +
                   " Core skills: " + ", ".join(top_skills[:8]) + ".").strip()

    # Your own bullets go in VERBATIM — no model paraphrase, so no specific can be corrupted.
    parts = []
    for p in projects:
        parts.append(f"### {p.get('x_resume_name') or p['name']} — "
                     f"{', '.join(_pretty(k) for k in (p.get('keywords') or [])[:5])}")
        if p.get("highlights"):
            parts += [f"- {h}" for h in p["highlights"]]
        else:
            bullet = (enh or {}).get("bullets", {}).get(p["name"].lower())
            if bullet:
                v = verify(drop_banned(bullet)[0], profile, jd_keywords)
                report["removed"] += v.removed
                report["unverified_terms"] += v.unverified_terms
                bullet = v.text
            bullet = bullet or p.get("description")   # the repo's own words beat an unbacked claim
            if bullet:
                parts.append(f"- {bullet}")
    projects_md = "\n".join(parts)

    lines = [f"# {name}", " · ".join(contact), "", "## Summary", summary,
             "", "## Skills", ", ".join(top_skills), "", "## Projects", projects_md]

    awards = profile.get("awards", [])
    if awards:
        lines += ["", "## Selections & Programs"]
        for a in awards:
            meta = " · ".join(x for x in [a.get("awarder"), a.get("date")] if x)
            lines.append(f"- **{a.get('title')}**" + (f" — {meta}" if meta else ""))
            if a.get("summary"):
                lines.append(f"  {a['summary']}")

    work = profile.get("work", [])
    if work:
        lines += ["", "## Experience"]
        for w in work:
            when = " – ".join(x for x in [w.get("startDate") or w.get("start"),
                                          w.get("endDate") or w.get("end")] if x)
            lines.append(f"- **{w.get('position') or w.get('title')}**, "
                         f"{w.get('name') or w.get('company')}" + (f" ({when})" if when else ""))
            for h in w.get("highlights") or ([w["description"]] if w.get("description") else []):
                lines.append(f"  - {h}")

    certs = _pick_certs(profile, jd_keywords)
    if certs:
        lines += ["", "## Certifications"]
        for c in certs:
            meta = " · ".join(x for x in [c.get("issuer"), c.get("date")] if x)
            lines.append(f"- {c['name']}" + (f" — {meta}" if meta else ""))

    edu = profile.get("education", [])
    lines += ["", "## Education"]
    if edu:
        for e in edu:
            when = " – ".join(x for x in [e.get("startDate"), e.get("endDate")] if x)
            deg = " ".join(x for x in [e.get("studyType"), e.get("area")] if x) or "Degree"
            lines.append(f"- **{deg}**, {e.get('institution','')}" + (f" ({when})" if when else ""))
            if e.get("note"):
                lines.append(f"  {e['note']}")
    else:
        lines.append("- **B.Tech, Computer Science (AI & ML)**, [Your University] — [grad year]")

    return "\n".join(lines) + (
        "\n\n---\n*Generated from your verified profile — every line traces to a real project, "
        "credential, or selection. Review, then export to a SINGLE-COLUMN PDF (no tables or columns — "
        "they break ATS parsers).*")


def main() -> int:
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser(
        description="Resume Generator — a clean, ATS-safe resume from your career_profile.json.")
    ap.add_argument("--jd", default="", help="path to a JD file OR inline text — tailors the resume")
    ap.add_argument("--out", default="", help="write the resume to this file (e.g. resume.md)")
    args = ap.parse_args()

    profile = load_profile_json()
    if not profile:
        print("No career_profile.json yet — build it first:\n"
              "   python -m resume.profile --github <you> --include-private --certs <folder> "
              "--resume <your existing resume>")
        return 1

    jd_text = None
    if args.jd:
        p = Path(args.jd)
        jd_text = p.read_text(encoding="utf-8", errors="ignore") if p.exists() else args.jd

    md = generate_resume(profile, jd_text)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"Resume written → {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
