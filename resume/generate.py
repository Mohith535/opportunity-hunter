"""
Resume Generator (capstone) — turn your `career_profile.json` into a clean, ATS-safe resume.

This is where the whole engine pays off: Slices 1-5 built the intelligence (analyse, tailor, harvest,
simulate, unified profile); this renders an actual resume from your single source of truth — your real
skills (with evidence), your real projects (incl. private repos), your certificates, and — when your
LinkedIn export lands — your work history and education.

Two design choices keep it honest AND high quality:
  * The STRUCTURE is deterministic — standard single-column headings (Summary / Skills / Projects /
    Certifications / Education / Experience), reverse-chronological, plain text. That's exactly what
    ATS parse best (per the analyzer's own rules), and it means the resume renders even with no LLM.
  * The PROSE is LLM-polished but fact-bound — the summary, the project bullets (Google XYZ shape),
    and the selection of resume-worthy certificates come from the model, but ONLY from the real facts
    in your profile. Never invents; missing numbers become "[add metric]"; placeholders like
    "[add email]" mark what only you can fill.

Optional `--jd` tailors it to a specific job (front-loads matching skills, orders projects by
relevance, tailors the summary). Output is Markdown — readable, and it converts cleanly to a
single-column PDF/DOCX (don't pour it into a fancy multi-column template — that's what breaks parsers).
It's a DRAFT you review, complete the placeholders, and submit. Nothing is auto-applied.
"""

from __future__ import annotations

import re

from filters.llm_scorer import complete
from .profile import load_profile_json, relevant_projects

# Pretty display for skills stored lowercase in the profile. Fallback = word-capitalise.
_DISPLAY = {
    "aws": "AWS", "sql": "SQL", "llm": "LLM", "llms": "LLMs", "api": "API", "rest api": "REST APIs",
    "rest apis": "REST APIs", "ui/ux": "UI/UX", "html": "HTML", "css": "CSS", "gcp": "GCP",
    "nlp": "NLP", "ci/cd": "CI/CD", "javascript": "JavaScript", "typescript": "TypeScript",
    "mysql": "MySQL", "postgresql": "PostgreSQL", "github": "GitHub", "github actions": "GitHub Actions",
    "google cloud": "Google Cloud", "generative ai": "Generative AI", "machine learning":
    "Machine Learning", "deep learning": "Deep Learning", "prompt engineering": "Prompt Engineering",
    "data analytics": "Data Analytics", "security copilot": "Security Copilot", "critical thinking":
    "Critical Thinking",
}
# Cert-folder entries that aren't real credentials (screenshots, tips, proofs) — dropped in the
# no-LLM fallback (the LLM does finer selection when available).
_CERT_NOISE = ("interview tip", "resume", "snippet", "application", "proof", "confirmation",
               "screenshot", "camp")


def _pretty(skill: str) -> str:
    if skill in _DISPLAY:
        return _DISPLAY[skill]
    return " ".join(_DISPLAY.get(w, w.capitalize()) for w in skill.split())


# ─── selection (deterministic, honest) ───────────────────────────────
def _skills_ordered(profile: dict, jd_keywords: list[str], limit: int = 20) -> list[str]:
    names = [s["name"] for s in profile.get("skills", [])]  # already sorted by evidence
    if jd_keywords:
        kws = {k.lower().strip() for k in jd_keywords if k.strip()}
        matched = [s for s in names if any(k and (k in s or s in k) for k in kws)]
        names = matched + [s for s in names if s not in matched]
    return [_pretty(s) for s in names[:limit]]


def _pick_projects(profile: dict, jd_keywords: list[str], limit: int = 6) -> list[dict]:
    if jd_keywords:
        picks = relevant_projects(profile, jd_keywords, limit)
        if picks:
            return picks
    described = [p for p in profile.get("projects", []) if p.get("description")]
    return (described or profile.get("projects", []))[:limit]


def _clean_certs(profile: dict, limit: int = 12) -> list[str]:
    out = []
    for c in profile.get("certificates", []):
        name = c["name"]
        if any(n in name.lower() for n in _CERT_NOISE):
            continue
        out.append(name)
    return out[:limit]


# ─── LLM enhancement (fact-bound) ────────────────────────────────────
_ENHANCE_PROMPT = """You are an expert technical resume writer. Using ONLY the real facts below, write
three sections for {name}'s resume. NEVER invent — no fake metrics, tools, employers, or details.
Where a number would strengthen a bullet but isn't given, write "[add metric]".{jd_line}

Return EXACTLY these three blocks, plain text, nothing else:

SUMMARY:
<2-3 line professional summary, grounded only in these facts{jd_tailor}>

PROJECTS:
<for each project below, ONE line formatted "- **Exact Project Name** — <bullet>": strong action verb
+ what it does + the tech + a result or [add metric]. Use ONLY that project's stated description/tech;
keep its real name. Do not add projects.>

CERTIFICATIONS:
<from the certificate entries below, select ONLY the ones that are genuine, resume-worthy credentials
(DROP screenshots, "interview tips", "resume snippets", application proofs). Format each as a clean
"- Title". At most 10.>

--- FACTS ---
Name: {name}
Background: {about}
Skills: {skills}
Projects:
{projects}
Certificate entries (select the real credentials):
{certs}{jd_block}
"""


def _enhance(profile: dict, projects: list[dict], certs: list[str], jd_text: str | None) -> dict | None:
    name = profile.get("basics", {}).get("name", "Candidate")
    declared = profile.get("x_declared", {})
    about = " ".join(x for x in [declared.get("identity", ""), declared.get("longTermGoal", "")]
                     if x) or "(not specified)"
    proj_lines = "\n".join(
        f"- {p.get('name')} (tech: {', '.join(p.get('keywords') or []) or 'n/a'}): "
        f"{p.get('description') or '(no description)'}" for p in projects)
    prompt = _ENHANCE_PROMPT.format(
        name=name,
        about=about,
        skills=", ".join(_skills_ordered(profile, [], 25)),
        projects=proj_lines or "(none)",
        certs="\n".join(f"- {c}" for c in certs) or "(none)",
        jd_line=(" Tailor the summary and bullet emphasis toward the JOB DESCRIPTION at the end."
                 if jd_text else ""),
        jd_tailor=", tailored to the job" if jd_text else "",
        jd_block=(f"\n\n--- JOB DESCRIPTION (tailor toward this) ---\n{jd_text[:2500]}"
                  if jd_text else ""))
    out = complete(prompt, max_tokens=1000, temperature=0.4)
    if not out:
        return None
    return {
        "summary": _block(out, "SUMMARY", ("PROJECTS", "CERTIFICATIONS")),
        "projects": _block(out, "PROJECTS", ("CERTIFICATIONS", "SUMMARY")),
        "certifications": _block(out, "CERTIFICATIONS", ("SUMMARY", "PROJECTS")),
    }


def _block(text: str, name: str, nexts: tuple[str, ...]) -> str:
    m = re.search(rf"{name}:\s*(.*?)(?=\n(?:{'|'.join(nexts)}):|\Z)", text, re.S | re.I)
    return m.group(1).strip() if m else ""


# ─── assemble ────────────────────────────────────────────────────────
def generate_resume(profile: dict, jd_text: str | None = None) -> str:
    from .analyzer import extract_jd_keywords  # noqa: PLC0415
    jd_keywords = extract_jd_keywords(jd_text) if jd_text else []

    basics = profile.get("basics", {})
    name = basics.get("name", "Your Name")
    gh = next((p.get("url") for p in basics.get("profiles", []) if p.get("network") == "GitHub"), "")

    projects = _pick_projects(profile, jd_keywords)
    certs = _clean_certs(profile)
    enh = _enhance(profile, projects, certs, jd_text)

    # Summary (LLM, else deterministic from declared identity + top skills).
    top_skills = _skills_ordered(profile, jd_keywords, 20)
    if enh and enh["summary"]:
        summary = enh["summary"]
    else:
        identity = profile.get("x_declared", {}).get("identity", "")
        summary = (identity + " Core skills: " + ", ".join(top_skills[:6]) + ".").strip()

    # Projects (LLM bullets, else deterministic name — description).
    if enh and enh["projects"]:
        projects_md = enh["projects"]
    else:
        projects_md = "\n".join(
            f"- **{p.get('name')}** — {p.get('description') or 'project'} "
            f"({', '.join(_pretty(k) for k in (p.get('keywords') or [])[:4])})" for p in projects)

    certs_md = (enh["certifications"] if enh and enh["certifications"]
                else "\n".join(f"- {c}" for c in certs))

    # Education (LinkedIn if present, else a fill-in grounded in the declared identity).
    edu = profile.get("education", [])
    if edu:
        education_md = "\n".join(
            f"- **{e.get('studyType') or 'Degree'}**, {e.get('institution') or ''}"
            f"{' (' + e.get('endDate') + ')' if e.get('endDate') else ''}" for e in edu)
    else:
        education_md = "- **B.Tech, Computer Science (AI & ML)**, [Your University], India — [grad year]"

    lines = [
        f"# {name}",
        " · ".join(x for x in [gh, "[add email]", "[add phone]", "[add location]"] if x),
        "", "## Summary", summary,
        "", "## Skills", ", ".join(top_skills),
        "", "## Projects", projects_md,
        "", "## Certifications", certs_md,
        "", "## Education", education_md,
    ]

    work = profile.get("work", [])
    if work:
        lines += ["", "## Experience"]
        for w in work:
            when = " – ".join(x for x in [w.get("start"), w.get("end")] if x)
            lines.append(f"- **{w.get('title')}**, {w.get('company')}" + (f" ({when})" if when else ""))
            if w.get("description"):
                lines.append(f"  {w['description']}")

    footer = ("\n---\n*Draft generated from your verified profile. Fill the [bracketed] placeholders, "
              "review every line, then export to a single-column PDF. Nothing here is invented or "
              "auto-submitted.*")
    if not work:
        footer = ("\n---\n*Draft from your verified profile — projects-first (a strong shape for a "
                  "student). Your Work Experience + Education fill in automatically once you add your "
                  "LinkedIn export. Fill [placeholders], review, export to a single-column PDF.*")
    return "\n".join(lines) + footer


# ─── CLI ─────────────────────────────────────────────────────────────
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
              "   python -m resume.profile --github <you> --include-private --certs <folder>")
        return 1

    jd_text = None
    if args.jd:
        p = Path(args.jd)
        jd_text = p.read_text(encoding="utf-8", errors="ignore") if p.exists() else args.jd

    resume_md = generate_resume(profile, jd_text)
    if args.out:
        Path(args.out).write_text(resume_md, encoding="utf-8")
        print(f"Resume written → {args.out}")
    else:
        print(resume_md)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
