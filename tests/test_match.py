"""Tests for resume/match.py and the tailoring it drives (4 Oct 2026).

Before this, every pack was 90–98% the same lines as every other pack: the only job-specific text came
from a free model that was returning nothing, and the summary and headline were his Claude Ambassador
ones on every job, a game studio's included. These pin the replacement: asks read from the posting,
answered with sentences already in his profile, no model needed.

Run:  python tests/test_match.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from resume import generate as GEN
from resume import match as M
from resume.apply import tailoring_status

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

EA = """General Information
Studio/Department
EA Mobile - Slingshot Games (India)
Description & Requirements
Our teams are player-focused and motivated to deliver quality.
Responsibilities
You will participate in building new game features.
You will improve code for performance, focusing on reducing load times and improving frame rates.
You will write good documentation and follow coding standards.
Qualifications
Have a solid foundation of data structures and algorithms
Solid programming skills
Be able to use modern Agentic AI coding harnesses
Bonus:
Experience making and playing games
Demonstrated proficiency in C++/C#/ Java or PHP
Demonstrated proficiency in 3D Mathematics used in games.
Demonstrated understanding of RESTful API
What this opportunity provides:
Exposure to all aspects of game development
About Electronic Arts
We make games."""

PROFILE = {
    "basics": {"name": "K MOHITH KANNAN"},
    "education": [{"institution": "SRM Institute of Science and Technology", "studyType": "B.Tech",
                   "startDate": "2025", "endDate": "2029"}],
    "projects": [
        {"x_resume_name": "OPHunter", "x_source": "resume-2026-09", "x_tagline": "a daily agent", "x_when": "2026",
         "highlights": ["Scans 12 sources every morning on GitHub Actions.",
                        "A 10 s timeout was not stopping two downloads. I put each download under its own "
                        "wall-clock deadline: **218 s → 69 s**.",
                        "The bot and my laptop share one setting through a token-protected GET/PUT REST API."]},
        {"x_resume_name": "nova-cortex", "x_source": "resume-2026-09", "x_tagline": "an agent memory", "x_when": "2026",
         "highlights": ["I benchmarked my own thesis and it was refuted — the LLM out-governed my rules. "
                        "Roughly 92% of the model's accuracy at a quarter of its calls."]},
        {"x_resume_name": "Flappy Bird clone", "x_confirmed": "2026-10-04",
         "highlights": ["A Flappy Bird clone in Python with pygame: game loop, sprite animation, sound."]},
        {"x_resume_name": "LeetCode solutions", "x_confirmed": "2026-10-04",
         "highlights": ["34 LeetCode problems solved in C, #1 to #35."]},
        {"x_resume_name": "Unconfirmed", "highlights": ["A pygame game nobody confirmed."]},
    ],
    "x_resume": {
        "headline": "AMBASSADOR HEADLINE | MCP servers and clients",
        "summary_core": "AMBASSADOR SUMMARY: builds with Claude every day.",
        "headline_variants": {"default": "DEFAULT HEADLINE | Python · Java · C"},
        "summary_variants": {"default": "DEFAULT SUMMARY: builds software that keeps running."},
        "closing": "AMBASSADOR CLOSING.", "closing_variants": {"default": "Advent of Code 2025."},
        "agentic_line": "258 commits co-authored with Claude Code across six of my own repositories since June 2026 (x 1).",
        "links": ["a@b.c", "github.com/x"],
        "community": ["**Writing and explaining:** public repositories written with real READMEs."],
        "skill_groups": {"Languages": ["Python (advanced)", "Java", "C", "C++"]},
    },
}

# ── reading the posting ──────────────────────────────────────────────────────────────────────
req = M.requirement_lines(EA)
lines = [l for _, l in req]
check("1. studio blurb after 'Description & Requirements' is not an ask",
      not any("player-focused" in l for l in lines), lines[:3])
check("2. 'What this opportunity provides' and 'About' are not asks",
      not any("Exposure to all aspects" in l or "We make games" in l for l in lines))
check("3. qualifications, bonus and duties are all read",
      {p for p, _ in req} == {0, 1, 2} and "Experience making and playing games" in lines)
check("4. prose postings (no headings) still yield asks — but not the blurb",
      [l for _, l in M.requirement_lines("We build tools for agents. You will improve latency. "
                                         "Experience with MCP is a plus.")]
      == ["You will improve latency.", "Experience with MCP is a plus."])

# ── answering it ─────────────────────────────────────────────────────────────────────────────
m = M.match(EA, PROFILE)
rows = {l: (ev, proj) for _, l, ev, proj in m["rows"]}
check("5. games bonus ← the Flappy Bird he confirmed", rows["Experience making and playing games"][1] == "Flappy Bird clone")
check("6. performance ← the measured 218 s → 69 s", "218 s → 69 s" in rows[
    "You will improve code for performance, focusing on reducing load times and improving frame rates."][0])
check("7. agentic coding ← the commit count, without the per-repo parenthesis",
      rows["Be able to use modern Agentic AI coding harnesses"][0].startswith("258 commits")
      and "(x 1)" not in rows["Be able to use modern Agentic AI coding harnesses"][0])
check("8. 3D mathematics is a GAP, never a claim", rows["Demonstrated proficiency in 3D Mathematics used in games."] == ("", ""))
check("9. Java is 'covered by skills', not turned into a bullet",
      "skills: Java" in rows["Demonstrated proficiency in C++/C#/ Java or PHP"][0])
check("10. an unconfirmed project is never evidence", "nobody confirmed" not in str(m["rows"]))
check("11. the resume gets at most 4 bullets, each quoting the posting", 2 <= len(m["bullets"]) <= 4
      and all(b.startswith("**“") for b in m["bullets"]), m["bullets"])
check("12. the concrete asks win the 4 slots (games, performance, DSA, agentic)",
      all(any(k in b for b in m["bullets"]) for k in ("Flappy", "218 s", "LeetCode", "Claude Code")), m["bullets"])

# ── the resume it drives ─────────────────────────────────────────────────────────────────────
GEN.complete = lambda *a, **k: "LINE: Delivered production-grade game features."    # must never be asked
md, rep = GEN.generate_resume_ex(PROFILE, EA, "Software Engineer Intern", "Electronic Arts")
base, _ = GEN.generate_resume_ex(PROFILE, None)
check("13. a game studio gets the DEFAULT summary and headline, not the Ambassador ones",
      "DEFAULT SUMMARY" in md and "DEFAULT HEADLINE" in md and "AMBASSADOR" not in md)
check("14. his base resume (no job) is still his Ambassador one", "AMBASSADOR SUMMARY" in base)
check("15. AI coding tools asked for → the agentic line joins the summary", "I build with Claude Code every day" in md)
check("16. with 2+ matches the model is not asked at all", rep["tailor_line"] == "" and "Delivered" not in md)
check("17. an AI-titled role gets the AI family", GEN._family("We build agents.", "AI Engineer Intern") == "ai")
check("18. one 'AI' in a game posting is a tool, not the job", GEN._family(EA, "Software Engineer Intern") == "default")
ch, tot = M.changed_lines(md, base)
check("19. changed-vs-base is measured", 0 < ch <= tot, (ch, tot))
check("20. the role section sits right under the summary",
      md.index("## What I would bring") < md.index("## Projects") and md.index("## Summary") < md.index("## What I would bring"))

# ── honest status ────────────────────────────────────────────────────────────────────────────
check("21. status: evidence-matched", tailoring_status({"role_section": ["x"]}, "jd") == "evidence")
check("22. status: model only", tailoring_status({"tailor_line": "x"}, "jd") == "model")
check("23. status: FAILED says so", tailoring_status({}, "jd") == "failed")
check("24. status: no job", tailoring_status({}, "") == "none")

print("=" * 72)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 72)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
