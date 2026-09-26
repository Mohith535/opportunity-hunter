"""Tests for his voice (resume/voice.py) and the resume generator's use of it.

Two guarantees matter:
  1. The phrases recruiters flag as AI-written never survive in model-written text.
  2. HIS OWN writing passes clean — including the em-dashes, "not X, it is Y" turns and bold he
     uses on purpose. A linter that flags the person's real voice is a linter that gets ignored.

Also covers the generator end to end on a fixture profile, with the LLM stubbed: a lying model, a
clean model, a model using banned phrasing, and a DEAD model (the chain was down during the first
live run, and the resume has to be complete anyway).

Run:  python tests/test_voice.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import resume.generate  # noqa: F401  (registers the module so it can be stubbed)
from resume.profile import carry_over, facts_drift
from resume.voice import bold_budget, drop_banned, emphasis_bold, lint

GEN = sys.modules["resume.generate"]

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

# His real bullets — the voice these rules exist to protect.
HIS = [
    "Connect an agent to an MCP server today and it is all-or-nothing: every tool, or none. "
    "NitroWatch sits in front of any MCP server, sorts each tool into three risk tiers — reads run "
    "instantly, reversible actions need approval, irreversible ones always do — lets safe tools earn "
    "autonomy through a clean track record, and writes a permanent audit trail.",
    "I benchmarked my own thesis on a frozen, hash-locked corpus and it was refuted — the LLM "
    "out-governed my hand-written rules. I published that rather than bury it.",
    "Competing loopers overshoot the end point by up to 250 ms; mine measures its own timing error "
    "every lap and lands within about 12 ms. 108 commits, 214 tests, live and in use.",
]

# ── banned phrasing ──────────────────────────────────────────────────────────────────────
t, hits = drop_banned("Built NitroWatch in a day. Seeking an SEO internship to apply my skills. "
                      "Proven ability to design production-grade systems.")
check("1. 'Seeking an…' and 'Proven ability…' sentences are dropped",
      t == "Built NitroWatch in a day." and {"seeking an", "proven ability"} <= set(hits), f"{t!r} {hits}")

for phrase in ("I delve into data.", "Passionate about AI.", "A results-driven engineer.",
               "Showcasing strong skills.", "In today's fast-paced world, I build.", "I am excited to join."):
    check(f"2. drops: {phrase}", drop_banned(phrase)[0] == "", drop_banned(phrase)[0])

check("3. his real bullets survive drop_banned untouched",
      all(drop_banned(h)[0] == h for h in HIS))
check("4. his real bullets have no AI-tell findings",
      not any("AI-tell" in f for h in HIS for f in lint(h)), str([lint(h) for h in HIS]))

# ── placeholders, meta, punctuation ──────────────────────────────────────────────────────
check("5. template placeholders are flagged", any("placeholder" in f for f in lint("Worked at [Company] as [Role].")))
check("6. OUR honest [add metric] placeholder is allowed",
      not any("placeholder" in f for f in lint("Cut latency by [add metric: ms] with caching.")))
check("7. exclamation marks are flagged", any("exclamation" in f for f in lint("Shipped it!")))
check("8. soft words are reported, not removed",
      drop_banned("A robust parser.")[0] == "A robust parser." and any("robust" in f for f in lint("A robust parser.")))

# ── bold: labels vs emphasis (von Restorff) ──────────────────────────────────────────────
doc = ("**Languages:** Python · TypeScript\n"
       "- **Four hackathons in 2026:** NitroStack, Aaruush\n"
       "**NitroWatch** — a permission system\n"
       "- shipped with **two of them in the framework itself, reported upstream**.")
check("9. line-opening bold is a label, not emphasis", emphasis_bold(doc) == ["two of them in the framework itself, reported upstream"],
      str(emphasis_bold(doc)))
check("10. bold budget keeps only the first emphasis in a block",
      bold_budget("- **a** and **b** and **c**") == "- **a** and b and c", bold_budget("- **a** and **b** and **c**"))
many = "\n".join(f"- line {i} with **emph{i}** inside" for i in range(9))
check("11. more than 7 emphasised phrases is flagged", any("emphasised" in f for f in lint(many)))

# ── dashes: his density passes, a dash-in-everything model does not ──────────────────────
check("12. his dash density passes", not any("em-dash" in f for f in lint(" ".join(HIS))))
spam = " ".join(f"Sentence number {i} is here — with an aside — and more text to pass length." for i in range(8))
check("13. a dash in every sentence is flagged", any("em-dash" in f for f in lint(spam)))

# ── the generator, with a stubbed model ──────────────────────────────────────────────────
PROFILE = {
    "basics": {"name": "K MOHITH KANNAN", "email": "promohith535@gmail.com"},
    "skills": [{"name": "python"}, {"name": "typescript"}, {"name": "mcp"}],
    "education": [{"institution": "SRM Institute of Science and Technology", "studyType": "B.Tech",
                   "startDate": "2024", "endDate": "2028"},
                  {"institution": "Sainik School Amaravathinagar", "studyType": "Senior Secondary",
                   "note": "Ranked 2nd in class"}],
    "projects": [
        {"name": "NitroWatch", "x_resume_name": "NitroWatch", "x_source": "resume-2026-09",
         "x_tagline": "a permission system for AI agents", "x_when": "Aug 2026",
         "x_techline": "TypeScript · MCP · policy engines · audit logging",
         "highlights": [HIS[0], "Shipped with **two bugs reported upstream** and **more bold**."]},
        {"name": "nova-cortex", "x_resume_name": "nova-cortex", "x_source": "resume-2026-09",
         "x_tagline": "an agent memory that is allowed to say no", "x_when": "Jul 2026",
         "x_techline": "Python · MCP · AWS Bedrock/Lambda · benchmarking", "highlights": [HIS[1] +
         " Roughly 92% of the model's accuracy at a quarter of its calls. 190 tests."]},
        {"name": "TaskFlow", "x_resume_name": "TaskFlow", "x_source": "resume-2026-09",
         "x_tagline": "a task manager built on behavioural science", "x_when": "Dec 2025 – present",
         "x_techline": "Python · CLI", "highlights": [
             "One rule I hold every screen to — rescue, not punishment. Every feature traces to "
             "published research (the Zeigarnik effect, Yerkes–Dodson)."]},
    ],
    "x_resume": {"headline": "B.Tech CSE (AI & ML) @ SRM Chennai | MCP servers and clients",
                 "summary_core": "Second-year CSE (AI & ML) student who ships what he builds.",
                 "closing": "The thing I am proudest of is a memory that knows how to refuse.",
                 "links": ["promohith535@gmail.com", "looplab.page"],
                 "skill_groups": {"Languages": ["Python", "TypeScript"], "AI & agents": ["MCP"]}},
}
REAL_COMPLETE = GEN.complete


def gen(model_reply, role="Software Engineer Intern", jd="Python, MCP, agents."):
    GEN.complete = lambda *a, **k: model_reply
    try:
        return GEN.generate_resume_ex(PROFILE, jd, role)
    finally:
        GEN.complete = REAL_COMPLETE


md, rep = gen("LINE: Skilled in SEO and content creation, I built NitroWatch.")
check("14. a lying tailor line is removed and reported",
      "SEO" not in md.split("## Selected Work")[0] and rep["removed"] and "seo" in rep["unverified_terms"],
      str(rep["removed"]))

md, rep = gen("LINE: The same question — can an agent be trusted with real permissions — is what this role is about.")
check("15. a clean tailor line is kept", rep["tailor_line"] and "trusted with real permissions" in md,
      rep["tailor_line"] or str(rep["removed"]))

md, rep = gen("LINE: Passionate about building trustworthy agents in Python.")
check("16. a banned-phrase tailor line is dropped", not rep["tailor_line"] and "passionate" in rep["banned"])

md, rep = gen("")                                  # the chain is DOWN
check("17. with the model down the resume is still complete",
      all(s in md for s in ("## Summary", "## Selected Work", "## Technical Skills", "## Education"))
      and "Second-year CSE" in md and not rep["tailor_line"])

check("18. the 3-second zone: headline and graduation year sit above the summary",
      md.index("MCP servers and clients") < md.index("## Summary") and md.index("2024–2028") < md.index("## Summary"))
check("19. class rank stays on the resume", "Ranked 2nd in class" in md)
check("20. the page ends on his closing line (peak-end)", md.rstrip().endswith("how to refuse.*"))
check("21. one emphasis per project block (von Restorff)", "**more bold**" not in md and "**two bugs reported upstream**" in md)

def first_project(role, jd):
    m, _ = gen("", role, jd)
    return next(l.split("**")[1] for l in m.splitlines() if l.startswith("**") and " — " in l)

check("22. ML role leads with nova-cortex", first_project("ML Intern", "machine learning models, evaluation") == "nova-cortex")
check("23. UX/psychology role leads with TaskFlow", first_project("UX Research Intern", "user research, behavioural psychology") == "TaskFlow")
check("24. security role leads with NitroWatch", first_project("Security Intern", "permissions, governance, audit") == "NitroWatch")

check("25. acronyms render correctly",
      [GEN._pretty(s) for s in ("TypeScript", "cli", "nlp", "mcp", "google adk", "GitHub")]
      == ["TypeScript", "CLI", "NLP", "MCP", "Google ADK", "GitHub"])

# ── safe rebuild + facts drift ───────────────────────────────────────────────────────────
fresh = {"basics": {"name": "K"}, "projects": [{"name": "opportunity-hunter"}],
         "education": [{"institution": "Sainik School Amaravathinagar"}], "awards": []}
merged, kept = carry_over({**PROFILE, "awards": [{"title": "GSSoC 2026"}]}, fresh)
names = [p.get("x_resume_name") or p.get("name") for p in merged["projects"]]
check("26. a rebuild keeps curated projects, awards, email and rank",
      {"NitroWatch", "nova-cortex", "TaskFlow"} <= set(names) and merged["awards"]
      and merged["basics"]["email"] == "promohith535@gmail.com"
      and merged["education"][0].get("note") == "Ranked 2nd in class", str(kept))

d = tempfile.mkdtemp()
fy = Path(d) / "facts.yml"
fy.write_text("project_detail:\n  - name: TaskFlow\n    text: Dec 2025 - present, v9.1.0.\n"
              "  - name: LoopLab\n    text: 214 tests.\n", encoding="utf-8")
drift = facts_drift(PROFILE, fy)
check("27. facts.yml drift catches a newer version", any("v9.1.0" in x for x in drift), str(drift))
check("28. facts.yml drift catches a missing project", any("LoopLab" in x for x in drift), str(drift))
check("29. no facts.yml (the cloud run) is not an error", facts_drift(PROFILE, Path(d) / "nope.yml") == [])

print("=" * 76)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 76)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
