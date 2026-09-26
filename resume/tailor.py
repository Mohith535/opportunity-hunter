"""
Resume tailoring (Slice 2) — rewrite the candidate's REAL bullets to a specific job, honestly.

Grounded in two researched facts:
  * How ATS parse: exact keyword matches score highest, so we mirror the job's language.
  * How strong resumes read: Google's XYZ formula (Laszlo Bock) — "Accomplished [X] as measured by
    [Y] by doing [Z]" — a strong action verb, a number, and the technical method.

The inviolable rule, same as the rest of this module: NEVER invent. The model may only reframe the
candidate's real content and weave in skills they've CONFIRMED they genuinely have. Where a bullet
would be stronger with a metric the resume doesn't provide, it inserts an "[add metric]" placeholder
for the candidate to fill — it never fabricates a number. Output is a DRAFT the human edits and
submits; nothing here is auto-applied.
"""

from __future__ import annotations

from filters.llm_scorer import complete

_TAILOR_PROMPT = """You are an expert technical resume writer. Tailor the candidate's REAL resume to
the job below — honestly, without inventing anything.

INVIOLABLE HONESTY RULES:
- Use ONLY experience, projects, and skills that appear in the RESUME below, in the REAL PROJECTS &
  WORK section, OR in this list of skills the candidate has CONFIRMED they genuinely have: {confirmed}
- NEVER invent metrics, tools, employers, dates, or achievements. If a bullet would be stronger with
  a number the resume doesn't give, insert a placeholder exactly like "[add metric: %, count, or
  time]" for the candidate to fill. Do NOT make up a number.
- Only weave in a keyword if it is truly theirs (in the resume or the confirmed list). If it is not,
  leave it out — do not imply experience they don't have.
- You MAY add a bullet for a real project or role listed under REAL PROJECTS & WORK when it strengthens
  the fit — but using ONLY the facts stated there. Never invent a project, a description, or a detail
  beyond what is listed.

STYLE (how strong technical resumes read):
- Mirror the JOB's exact keywords and phrasing wherever it is truthful (exact matches rank highest
  in ATS and in a recruiter's keyword search).
- Write each experience bullet in Google's XYZ shape: strong action verb + what you built/did + the
  tech/method + a quantified result. Example: "Reduced API latency 40% by adding Redis caching."
  Never "responsible for" or "helped with".
- Plain text, single-column friendly, reverse-chronological order preserved.

HIS VOICE — derived from his own resume and repo descriptions, and confirmed by him. This is not
decoration: generic prose is what gets a fresher's resume binned, and specificity is the only thing
that reads as a real person rather than a template.
- Open on the PROBLEM, never on himself. "Connecting an agent to an MCP server is all-or-nothing"
  beats "Passionate about AI safety".
- State the turn flatly, no build-up: "That is not a permission model, it is a light switch."
- Always a measured number. He has real ones — 3200+ lines, 17 typed tools, 190 tests, ~12 ms
  against 250 ms, ~92% accuracy at a quarter of the calls. Use his, never invent one.
- Name what broke, including his own work. A benchmark that refuted his own thesis is a STRENGTH
  here and he has explicitly sanctioned saying so; an honest technical negative result is the
  rarest thing on a student resume.
- Plain first person by implication. No hedging, no "I'm excited to", no "seeking to leverage".
- Em-dash asides are his. No emoji. No exclamation marks. No buzzword stacking.

Output EXACTLY these three sections, plain text, nothing else:

SUMMARY:
<2-3 line professional summary tailored to this job, grounded only in the real profile>

SKILLS:
<one comma-separated line: the real + confirmed skills, front-loading the job's must-haves>

EXPERIENCE:
<the candidate's real bullets, rewritten per the rules; keep [add metric] placeholders where a
number is genuinely missing. You may add a bullet drawn from REAL PROJECTS & WORK when it strengthens
the fit for this job.>

--- REAL PROJECTS & WORK (from the candidate's verified profile — reference truthfully, never invent beyond this) ---
{context}

--- RESUME ---
{resume}

--- JOB DESCRIPTION ---
{jd}
"""


def tailor(resume_text: str, jd_text: str, confirmed_skills: list[str],
           evidence_context: str = "") -> str:
    """A tailored resume DRAFT (Summary + Skills + rewritten Experience), honest and JD-aligned.

    `confirmed_skills` = the JD keywords already in the resume PLUS any the candidate has verified
    they genuinely have. Skills outside this set are never woven in. `evidence_context` (optional) is a
    block of the candidate's REAL projects + work history from their verified profile, so the draft can
    surface genuine experience the resume omits — never invented. Returns '' if the LLM chain is
    unavailable. The candidate reviews and edits — nothing here is applied or submitted automatically.
    """
    confirmed = ", ".join(sorted({s.strip() for s in confirmed_skills if s.strip()})) or "(none)"
    prompt = _TAILOR_PROMPT.format(
        confirmed=confirmed, context=evidence_context or "(none provided)",
        resume=resume_text[:6000], jd=jd_text[:4000])
    return complete(prompt, max_tokens=900, temperature=0.4)


if __name__ == "__main__":
    resume = ("Work Experience\n- Built Opportunity Hunter, an opportunity agent in Python using "
              "REST APIs and an LLM scoring pipeline.\nSkills\nPython, LLMs, REST APIs, Git")
    jd = "Backend intern. Requirements: Python, REST APIs, Docker, PostgreSQL, Git."
    print(tailor(resume, jd, confirmed_skills=["Python", "REST APIs", "Git", "Docker"]) or
          "(LLM unavailable)")
