"""Tests for the claim verifier (resume/verify.py).

The regression that created this module: a generated resume for an SEO internship said "Skilled in
HTML, meta tags, content creation, and SEO fundamentals". Three of those appear nowhere in the
profile. The prompt forbade it; the model did it anyway. These tests hold the deterministic guard
in place — and, just as importantly, prove it does not delete TRUE sentences, because a verifier
that cries wolf gets switched off.

Self-contained: uses a fixture profile, never the gitignored career_profile.json.
Run:  python tests/test_verify.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from resume.verify import evidence_text, jd_gaps, verify

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

# A fixture shaped like his real profile, with his real numbers.
PROFILE = {
    "basics": {"name": "K MOHITH KANNAN", "email": "promohith535@gmail.com"},
    "skills": [{"name": "python"}, {"name": "html"}, {"name": "typescript"}, {"name": "data analytics"},
               {"name": "postgresql"}, {"name": "mcp"}, {"name": "generative ai"}],
    "projects": [
        {"name": "nova-cortex", "highlights": [
            "I benchmarked my own thesis and it was refuted, then built selective escalation: roughly "
            "92% of the model's accuracy at a quarter of its calls. 190 tests; seven prompt-injection "
            "attacks resisted.",
            "Runs always-on (AWS Lambda + Bedrock, CockroachDB under serializable isolation)."]},
        {"name": "LoopLab", "highlights": [
            "Competing loopers overshoot by up to 250 ms; mine lands within about 12 ms. 108 commits, "
            "214 tests."]},
        {"name": "Nova", "highlights": ["Ten specialist agents reaching my data through 17 typed MCP tools."]},
    ],
    "education": [{"institution": "SRM Institute of Science and Technology", "startDate": "2024",
                   "endDate": "2028"},
                  {"institution": "Sainik School", "note": "Ranked 2nd in class"}],
    "x_resume": {"summary_core": "Second-year CSE (AI & ML) student. Five working systems so far."},
    "meta": {"known_stale_input": "claims SEO expert"},   # meta must NOT count as evidence
}

# ── 1. the exact regression ──────────────────────────────────────────────────────────────
seo = ("Second-year CSE (AI & ML) student. Skilled in HTML, meta tags, content creation, and SEO "
       "fundamentals. Built LoopLab in TypeScript.")
v = verify(seo, PROFILE)
check("1. the SEO sentence is removed", "SEO" not in v.text and "meta tags" not in v.text, v.text)
check("2. the invented terms are named exactly",
      set(v.unverified_terms) == {"seo", "meta tags", "content creation"}, str(v.unverified_terms))
check("3. true sentences around it survive",
      "Second-year CSE" in v.text and "LoopLab in TypeScript" in v.text, v.text)
check("4. a removed sentence is reported, not silent", len(v.removed) == 1 and not v.clean)

# ── 2. evidence it must NOT reject ───────────────────────────────────────────────────────
TRUE = [
    "Proficient in Python and TypeScript, with HTML on the side.",
    "Reached roughly 92% of the model's accuracy at a quarter of its calls.",
    "LoopLab lands within about 12 ms where competitors overshoot by 250 ms.",
    "Ten agents reach real data through 17 typed MCP tools.",
    "190 tests and 214 tests across two projects.",
    "Built an MCP server on AWS Lambda with CockroachDB.",
    "Experience with data analysis and PostgreSQL.",              # alias: analysis -> analytics
    "Experienced in Postgres-backed services.",                   # alias: postgres -> postgresql
    "Ranked 2nd in class at Sainik School.",
    "B.Tech at SRM, 2024 to 2028.",
    "Five working systems so far; 5 of them shipped.",            # number word backs a digit
]
for s in TRUE:
    r = verify(s, PROFILE)
    check(f"keeps true: {s[:44]}", r.clean, f"removed={r.removed} terms={r.unverified_terms} nums={r.unverified_numbers}")

# ── 3. other invention shapes ────────────────────────────────────────────────────────────
r = verify("Increased team productivity by 312% using Python.", PROFILE)
check("5. an invented number is removed", not r.text and "312" in r.unverified_numbers, str(r.unverified_numbers))

r = verify("Proficient in Zorblax and Python.", PROFILE)
check("6. an unknown invented skill in a claim list is caught (no lexicon entry needed)",
      not r.text and "zorblax" in r.unverified_terms, str(r.unverified_terms))

r = verify("Hands-on with Kubernetes and Docker in production.", PROFILE)
check("7. lexicon claims outside a trigger phrase are caught",
      not r.text and {"kubernetes", "docker"} <= set(r.unverified_terms), str(r.unverified_terms))

r = verify("Deployed with React.", PROFILE, jd_keywords=["React"])
check("8. a job keyword the profile lacks is caught", not r.text)

check("9. provenance notes in `meta` are not evidence",
      "seo" not in evidence_text(PROFILE).split("known_stale_input")[0] and
      not verify("An SEO expert.", PROFILE).clean)

check("10. empty text is safe", verify("", PROFILE).clean and verify("", PROFILE).text == "")

# ── 4. gaps for job.md ───────────────────────────────────────────────────────────────────
gaps = jd_gaps("We need SEO, meta tags, content marketing, HTML, Python and data analysis.", PROFILE)
check("11. gaps list what the job wants and the profile lacks",
      {"seo", "meta tags", "content marketing"} <= set(gaps), str(gaps))
check("12. gaps never list what he HAS (html, python, data analysis)",
      not ({"html", "python", "data analytics", "data analysis"} & set(gaps)), str(gaps))

print("=" * 76)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 76)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
