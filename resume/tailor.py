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
- Use ONLY experience, projects, and skills that appear in the RESUME below, OR in this list of
  skills the candidate has CONFIRMED they genuinely have: {confirmed}
- NEVER invent metrics, tools, employers, dates, or achievements. If a bullet would be stronger with
  a number the resume doesn't give, insert a placeholder exactly like "[add metric: %, count, or
  time]" for the candidate to fill. Do NOT make up a number.
- Only weave in a keyword if it is truly theirs (in the resume or the confirmed list). If it is not,
  leave it out — do not imply experience they don't have.

STYLE (how strong technical resumes read):
- Mirror the JOB's exact keywords and phrasing wherever it is truthful (exact matches rank highest
  in ATS and in a recruiter's keyword search).
- Write each experience bullet in Google's XYZ shape: strong action verb + what you built/did + the
  tech/method + a quantified result. Example: "Reduced API latency 40% by adding Redis caching."
  Never "responsible for" or "helped with".
- Plain text, single-column friendly, reverse-chronological order preserved.

Output EXACTLY these three sections, plain text, nothing else:

SUMMARY:
<2-3 line professional summary tailored to this job, grounded only in the real profile>

SKILLS:
<one comma-separated line: the real + confirmed skills, front-loading the job's must-haves>

EXPERIENCE:
<the candidate's real bullets, rewritten per the rules; keep [add metric] placeholders where a
number is genuinely missing>

--- RESUME ---
{resume}

--- JOB DESCRIPTION ---
{jd}
"""


def tailor(resume_text: str, jd_text: str, confirmed_skills: list[str]) -> str:
    """A tailored resume DRAFT (Summary + Skills + rewritten Experience), honest and JD-aligned.

    `confirmed_skills` = the JD keywords already in the resume PLUS any the candidate has verified
    they genuinely have. Skills outside this set are never woven in. Returns '' if the LLM chain is
    unavailable. The candidate reviews and edits — nothing here is applied or submitted automatically.
    """
    confirmed = ", ".join(sorted({s.strip() for s in confirmed_skills if s.strip()})) or "(none)"
    prompt = _TAILOR_PROMPT.format(
        confirmed=confirmed, resume=resume_text[:6000], jd=jd_text[:4000])
    return complete(prompt, max_tokens=900, temperature=0.4)


if __name__ == "__main__":
    resume = ("Work Experience\n- Built Opportunity Hunter, an opportunity agent in Python using "
              "REST APIs and an LLM scoring pipeline.\nSkills\nPython, LLMs, REST APIs, Git")
    jd = "Backend intern. Requirements: Python, REST APIs, Docker, PostgreSQL, Git."
    print(tailor(resume, jd, confirmed_skills=["Python", "REST APIs", "Git", "Docker"]) or
          "(LLM unavailable)")
