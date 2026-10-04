"""Tests for the pitch, the screening-question answers and the laptop sync (4 Oct 2026).

Run:  python tests/test_pitch_questions.py
"""
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from filters import outcomes, target
outcomes.reset_cache({"likes": {}, "avoids": {}, "signals": 0})      # never the live bot from a test
from filters.pitch import pitch, _money
from models import Opportunity
from resume import questions as Q
from resume import sync as S

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

fd, tp = tempfile.mkstemp(suffix=".json"); os.close(fd)
Path(tp).write_text(json.dumps({"active": True, "min_pay_per_month": 30000, "focus": ["internship"],
                                "roles": {"tier1": ["software engineer"]}}), encoding="utf-8")
_old = target.TARGET_FILE
target.TARGET_FILE = Path(tp); target.reset_cache()
try:
    ea = Opportunity("Software Engineer Intern", "https://x", "ats", "games", tags=["internship"],
                     deadline=date.today() + timedelta(days=2),
                     raw={"company": "Electronic Arts", "pay_max": 70000, "cities": ["Hyderabad"]})
    pub, mine = pitch(ea), pitch(ea, personal=True)
    check("1. money first, in Indian rupees", pub.startswith("🔥 💰 ₹70,000/month"), pub)
    check("2. the name says what they make", "EA — the studio behind" in pub, pub)
    check("3. urgency counted", "closes in 2 days" in pub, pub)
    check("4. the PUBLIC pitch never mentions his floor or roles (history.json is public)",
          "floor" not in pub and "tier-1" not in pub, pub)
    check("5. the personal pitch does: 2.3× his floor, his tier-1 role",
          "2.3× your floor" in mine and "tier-1 role" in mine, mine)
    news = Opportunity("Nvidia wants to put a watchdog chip next to every GPU", "https://n", "hackernews", "", tags=["news"])
    check("6. a news story about NVIDIA is not an NVIDIA opportunity", "NVIDIA" not in pitch(news), pitch(news))
    hack = Opportunity("Some Hack", "https://h", "unstop", "hackathon | Prize: cash 150000", tags=["hackathon"])
    check("7. hackathon prize in lakh grouping", "₹1,50,000 in prizes" in pitch(hack), pitch(hack))
    check("8. nothing true to say → empty", pitch(Opportunity("Random", "https://r", "reddit", "", tags=["news"])) == "")
    check("9. ₹ grouping", _money(70000) == "₹70,000" and _money(1500000) == "₹15,00,000", _money(1500000))
finally:
    target.TARGET_FILE = _old; target.reset_cache(); os.unlink(tp)

# ── screening questions ──────────────────────────────────────────────────────────────────────
P = {"x_resume": {"links": ["me@x.com", "github.com/Mohith535"], "skill_groups": {"Languages": ["Python (advanced)", "Java"]}},
     "projects": [
         {"x_resume_name": "TaskFlow", "x_source": "resume-2026-09",
          "highlights": ["Its web dashboard runs on a JSON REST API I wrote on Python's standard-library http.server, "
                         "with endpoints such as /api/tasks."]},
         {"x_resume_name": "nova-cortex", "x_source": "resume-2026-09",
          "highlights": ["Runs always-on (AWS Lambda + Bedrock)."]}]}
a = lambda q, **k: Q.answer(q, P, **k)[0]
check("10. Python level from his skills list", a("How comfortable are you with Python?") == "Advanced")
check("11. a dropdown option is picked when there is one",
      a("How comfortable are you with Python?", options=["Beginner", "Intermediate", "Advanced / expert"]) == "Advanced / expert")
check("12. Java listed without a level → Intermediate, never inflated", a("Rate your Java proficiency") == "Intermediate")
b = a(Q.COMMON[1])
check("13. backend API: honest that it was not FastAPI/Flask/Django, then the real project",
      b.startswith("Not with FastAPI") and "http.server" in b, b)
llm = a(Q.COMMON[2])
check("14. 'LLM API' is answered as LLM, not as backend (it contains 'api')", llm.startswith("Yes.") and "Bedrock" in llm, llm)
check("15. links, never the email", a(Q.COMMON[3]) == "github.com/Mohith535")
check("16. start date is his to decide", a(Q.COMMON[4]).startswith("YOU DECIDE"))
check("17. work authorisation is his to answer", a("Are you authorized to work in the United States?").startswith("YOU ANSWER"))
check("18. no evidence → says so, invents nothing", a("Describe your experience with Kubernetes operators.").startswith("YOU ANSWER"))
L = Q.section({"native_id": "unstop-123"}, P, [])
check("19. a site that hides its form gets the common questions, labelled as such",
      any("behind login" in l for l in L) and any("How comfortable are you with Python?" in l for l in L))
check("20. Greenhouse ids only — anything else makes no network call", Q.greenhouse_questions("lever:x:1") == [])

# ── sync ─────────────────────────────────────────────────────────────────────────────────────
check("21. a folder or file name from the bot can never escape applications/",
      S._safe("../../etc/passwd") == "etc-passwd" and "/" not in S._safe("a/b\\c") and S._safe("") == "file")

print("=" * 72)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 72)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
