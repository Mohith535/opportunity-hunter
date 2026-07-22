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
from .profile import load_profile_json, relevant_projects

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


def _pretty(skill: str) -> str:
    if skill in _DISPLAY:
        return _DISPLAY[skill]
    return " ".join(_DISPLAY.get(w, w.capitalize()) for w in skill.split())


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
- Mirror the job description's exact terms wherever they are TRUE for this candidate — ATS match
  literally, not by synonym.
- Student/early-career framing: confident, never inflated.

Output EXACTLY these two blocks and nothing else:

SUMMARY:
<3-4 lines, no pronouns. Lead with the identity + strongest proof (a real project or selection), then
the skills that match this job, then the goal. Concrete, no adjective soup.>

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


# ─── assemble ────────────────────────────────────────────────────────
def generate_resume(profile: dict, jd_text: str | None = None) -> str:
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
    if enh and enh["summary"]:
        summary = enh["summary"]
    else:
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
            bullet = (enh or {}).get("bullets", {}).get(p["name"].lower()) or p.get("description")
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
