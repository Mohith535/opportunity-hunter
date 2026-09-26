"""Tests for the application pack (resume/apply.py).

The pack is two files per job: everything about the job, and that job's resume. The tests that
matter are the ones guarding against a defect reaching an employer, because a resume is the one
document where a silent error is most expensive.

The corruption guard exists because of a real shipped defect: career_profile.json had been
rebuilt from a PDF, and the extractor mapped the arrow glyph to the "fi" ligature. A generated
resume read "TaskFlow v1.0 fi v8.5" and "blue fi amber fi red". The generator was working
perfectly and faithfully reproducing corrupt input.

Run:  python tests/test_apply.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from resume.apply import _lost_arrow, _slug, _text, corruption_warnings

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

# ── the corruption guard: must CATCH real damage ─────────────────────────────────────────
DAMAGE = [
    ("standalone lost arrow", "Shipped TaskFlow v1.0 fi v8.5 this year"),
    ("repeated lost arrow", "live temporal pressure (bluefiamberfired deadline urgency)"),
    ("spaced lost arrow", "blue fi amber fi red urgency"),
    ("arrow against a digit", "versions v1.0fiv8.5 shipped"),
    ("replacement characters", "decoded � wrongly"),
    ("html entities", "Coinbase&nbsp;internship, R&amp;D"),
    ("html tags", "<div>About the role</div>"),
    ("latin-1 mojibake", "weâ€™re hiring"),
    ("ligature glyph", "certiﬁcation from Google"),
    ("placeholder text", "TODO: write summary"),
]
for name, text in DAMAGE:
    check(f"catches {name}", corruption_warnings(text), repr(text[:40]))

# ── ...and must NOT cry wolf on ordinary resume prose ─────────────────────────────────────
# A guard that fires on "certifications" gets switched off within a day, which is worse than
# no guard at all. Every string below is real text from his own profile or a job description.
CLEAN = [
    "15+ certifications (Google, AWS, Anthropic)",
    "efficient, well-documented algorithmic solutions",
    "B.Tech Computer Science Engineering (Artificial Intelligence & Machine Learning)",
    "Google Cloud Asia Pacific Best of Next '26",
    "local JSON file storage, zero telemetry",
    "My GitHub profile README - builder, systems thinker",
    "positive/negative behavioral classification and score calculation",
    "proficient in Python, Java, AWS",
    "intent-aware earnings research agent, fintech and cybersecurity",
    "identified and verified upstream framework bugs",
    "Unified AI-powered grievance platform",
    "specific, measurable outcomes",
    "analysed financial reports under policy control",
    "first-class honours",
    "configured the deployment",
    "five working systems so far",
    "simplified the pipeline",
    "notifications and opportunities",
    "qualified candidates only",
    "field work in Chennai",
]
for text in CLEAN:
    check(f"clean: {text[:38]}", not corruption_warnings(text), str(corruption_warnings(text)))

# ── the arrow heuristic itself ────────────────────────────────────────────────────────────
check("_lost_arrow: bare 'fi'", _lost_arrow("fi"))
check("_lost_arrow: two 'fi'", _lost_arrow("bluefiamberfired"))
check("_lost_arrow: digit-adjacent", _lost_arrow("v1.0fiv8.5"))
check("_lost_arrow: 'Pacific' is a word", not _lost_arrow("Pacific"))
check("_lost_arrow: 'certifications' is a word", not _lost_arrow("certifications"))
check("_lost_arrow: 'file' is a word", not _lost_arrow("file"))

# ── HTML to readable text ─────────────────────────────────────────────────────────────────
# Greenhouse escapes its markup once and its entities twice, so a single unescape pass leaves
# a literal "&nbsp;" sitting in the middle of the prose. That shipped once.
gh = "&lt;div&gt;&lt;strong&gt;About&lt;/strong&gt;&lt;/div&gt;&lt;ul&gt;&lt;li&gt;Ship code&amp;nbsp;daily&lt;/li&gt;&lt;/ul&gt;"
out = _text(gh)
check("double-escaped HTML is decoded", "<div>" not in out and "&lt;" not in out, out[:60])
check("no literal entities survive", "&nbsp;" not in out and "&amp;" not in out, out[:60])
check("list structure is kept", "- Ship code" in out, out[:60])
check("heading text survives", "About" in out, out[:60])
check("empty input is safe", _text("") == "" and _text(None) == "")

# ── slugs ─────────────────────────────────────────────────────────────────────────────────
check("slug is filesystem-safe",
      _slug("Coinbase", "Software Engineer Intern — Coinbase", "2026-09-26")
      == "coinbase-software-engineer-intern-coinbase-2026-09-26")
check("slug survives empty parts", _slug("", "", "") == "opportunity")
check("slug has no trailing dash", not _slug("Scale AI", "ML Fellow (US) —").endswith("-"))

print("=" * 72)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 72)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
