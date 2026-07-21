"""
Cover-letter generator — the last piece between "found a job" and "applied to it".

Same engine, same rule as everywhere else: it writes only what's true. It reads your
`career_profile.json` (real skills with evidence, real projects incl. private repos, real
credentials) plus the job description, and drafts a short, human first-person letter.

One honesty problem is specific to cover letters and worth naming: **"why this company"** is exactly
where an AI writes a fluent lie — "I've long admired your work on X". This module refuses to do that.
That reason either comes from YOU (`--why "..."`) or it stays an explicit placeholder for you to fill.
An invented enthusiasm is the fastest way to be caught out in an interview.

Craft rules baked into the prompt (how strong cover letters actually read):
  * 3 short paragraphs, under ~300 words — recruiters skim.
  * Open with something CONCRETE (a real project that maps to the job), never "I am writing to apply".
  * Evidence over adjectives — prove it with a project instead of calling yourself "passionate".
  * Mirror the job's language where it's truthful; confident close, no groveling.
  * Student/early-career framing that's confident but not inflated.

Renders without an LLM too (a plain honest template). Output is a DRAFT you edit and send — nothing
is auto-submitted.
"""

from __future__ import annotations

from filters.llm_scorer import complete
from .generate import _clean_certs, _skills_ordered
from .profile import load_profile_json, relevant_projects

_NO_REASON = "[add: your genuine reason for this company — one specific thing about their work]"

_COVER_PROMPT = """You are helping a candidate write an HONEST cover letter. Use ONLY the real facts
below — this letter must survive an interview where every claim gets questioned.

INVIOLABLE RULES:
- Use ONLY the projects, skills, and credentials listed. NEVER invent experience, employers, metrics,
  or achievements.
- {reason_rule}
- If a number would strengthen a claim but isn't given, write "[add metric]". Never make one up.
- Do NOT overstate seniority — this candidate is a student / early-career. Confident, not inflated.

STYLE:
- Exactly 3 short paragraphs, under 300 words total. Recruiters skim.
- Open with something CONCRETE — a real project that maps to this job. Never "I am writing to apply".
- Show evidence, not adjectives: prove capability with a real project instead of claiming to be
  "passionate" or "hardworking".
- Do NOT enumerate skills — the resume already lists them. Name only the two or three that matter for
  this job, and show them THROUGH a project ("built X in Python"), never as a comma-separated list.
- Mirror the job's own language wherever it is truthful.
- Close with a clear, confident ask for a conversation. No groveling, no clichés.
- First person, natural human voice.

Output ONLY the letter: greeting, the three paragraphs, sign-off. No preamble, no notes, no subject.

--- REAL FACTS ---
Name: {name}
Background: {about}
Top skills: {skills}
Real projects (pick the 1-2 that fit this job best):
{projects}
Credentials: {certs}
Company: {company}
Role: {role}
Genuine reason for this company (from the candidate): {why}

--- JOB DESCRIPTION ---
{jd}
"""


def generate_cover_letter(profile: dict, jd_text: str, company: str = "", role: str = "",
                          why: str = "") -> str:
    """An honest, JD-grounded cover letter drafted from the candidate's verified profile.

    `why` is the candidate's OWN genuine reason for wanting this company — the one thing the model is
    forbidden to invent. Left empty, the letter carries a visible placeholder instead of a fabrication.
    """
    from .analyzer import extract_jd_keywords  # noqa: PLC0415
    jd_keywords = extract_jd_keywords(jd_text) if jd_text else []

    basics = profile.get("basics", {})
    name = basics.get("name", "Your Name")
    declared = profile.get("x_declared", {})
    about = " ".join(x for x in [declared.get("identity", ""), declared.get("longTermGoal", "")] if x)

    projects = relevant_projects(profile, jd_keywords, 3) or profile.get("projects", [])[:3]
    proj_lines = "\n".join(
        f"- {p.get('name')}{' [private]' if p.get('private') else ''} "
        f"(tech: {', '.join(p.get('keywords') or []) or 'n/a'}): "
        f"{p.get('description') or '(no description)'}" for p in projects)

    # The one rule that must flex: mentioning the placeholder when a real reason EXISTS makes the
    # model emit both. So the instruction differs depending on whether the candidate supplied one.
    reason_rule = (
        "NEVER invent a personal connection to the company. The candidate HAS supplied their genuine "
        'reason (see "Genuine reason" below) — weave that, and only that, naturally into the closing '
        "paragraph. Do NOT add any placeholder text."
        if why.strip() else
        'NEVER invent a personal connection to the company. No "I have long admired...", no fabricated '
        "enthusiasm. The candidate did NOT supply a reason, so output this placeholder EXACTLY ONCE in "
        f'the closing paragraph, and nothing else in its place: "{_NO_REASON}"')

    body = complete(_COVER_PROMPT.format(
        reason_rule=reason_rule, name=name, about=about or "(not specified)",
        skills=", ".join(_skills_ordered(profile, jd_keywords, 12)),
        projects=proj_lines or "(none)",
        certs=", ".join(_clean_certs(profile, 6)) or "(none)",
        company=company or "(not specified — use a neutral greeting)",
        role=role or "(infer from the job description)",
        why=why or "(NOT SUPPLIED — use the placeholder exactly as instructed)",
        jd=jd_text[:3000]), max_tokens=700, temperature=0.5)

    if not body:
        body = _fallback(name, about, company, role, projects, why)

    gh = next((p.get("url") for p in basics.get("profiles", []) if p.get("network") == "GitHub"), "")
    header = f"{name}\n" + " · ".join(x for x in [gh, "[add email]", "[add phone]"] if x)
    footer = ("\n\n---\n*Draft from your verified profile — every claim traces to a real project or "
              "credential. Fill any [bracketed] parts (especially your genuine reason for this "
              "company), read it once in your own voice, then send it yourself.*")
    return f"{header}\n\n{body.strip()}{footer}"


def _fallback(name: str, about: str, company: str, role: str, projects: list[dict], why: str) -> str:
    """Plain honest letter when no LLM is available — real facts, no invention."""
    greeting = f"Dear Hiring Team at {company}," if company else "Dear Hiring Team,"
    lead = projects[0] if projects else None
    p1 = (f"I'm applying for the {role} role. " if role else "I'm writing about the open role. ")
    if lead:
        p1 += (f"Most relevant: I built {lead.get('name')} — {lead.get('description') or 'a project'}"
               f" ({', '.join((lead.get('keywords') or [])[:3])}).")
    p2 = about or ""
    if len(projects) > 1:
        p2 += (" I've also built " +
               ", ".join(f"{p.get('name')}" for p in projects[1:3]) + ".")
    p3 = (why or _NO_REASON) + " I'd welcome a conversation about how I could contribute."
    return f"{greeting}\n\n{p1}\n\n{p2.strip()}\n\n{p3}\n\nSincerely,\n{name}"


# ─── CLI ─────────────────────────────────────────────────────────────
def main() -> int:
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser(
        description="Cover-letter generator — honest, grounded in your career_profile.json.")
    ap.add_argument("--jd", required=True, help="path to a JD file OR inline job-description text")
    ap.add_argument("--company", default="", help="company name (for the greeting)")
    ap.add_argument("--role", default="", help="role title (else inferred from the JD)")
    ap.add_argument("--why", default="",
                    help="YOUR genuine reason for wanting this company — the one thing this tool "
                         "will never invent for you. Omit it and you get a placeholder to fill.")
    ap.add_argument("--out", default="", help="write the letter to this file (e.g. cover.md)")
    args = ap.parse_args()

    profile = load_profile_json()
    if not profile:
        print("No career_profile.json yet — build it first:\n"
              "   python -m resume.profile --github <you> --include-private --certs <folder>")
        return 1

    p = Path(args.jd)
    jd_text = p.read_text(encoding="utf-8", errors="ignore") if p.exists() else args.jd

    letter = generate_cover_letter(profile, jd_text, args.company, args.role, args.why)
    if args.out:
        Path(args.out).write_text(letter, encoding="utf-8")
        print(f"Cover letter written → {args.out}")
    else:
        print(letter)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
