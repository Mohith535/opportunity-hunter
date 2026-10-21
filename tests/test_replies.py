"""Tests for spotting replies about his applications in Gmail (22 Oct 2026).

Run:  python tests/test_replies.py
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from inbox import replies as RP

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

TODAY = date(2026, 10, 22)
tracker = {
    "k1": {"status": "applied", "title": "Full Stack Developer Internship - Backend Focus", "applied_at": "2026-10-05"},
    "k2": {"status": "applied", "title": "AI Engineer Internship - GenAI & ML", "updated_at": "2026-10-06"},
    "k3": {"status": "applied", "title": "Data Analyst Internship", "applied_at": "2026-10-05", "outcome": "interview"},
    "k4": {"status": "skipped", "title": "Video Editor Internship", "updated_at": "2026-10-01"},
    "k5": {"status": "applied", "title": "Internship", "applied_at": "2026-10-05"},
}
emails = [
    {"id": "e1", "from": "Unstop <noreply@unstop.com>",
     "subject": "You have been shortlisted for Full Stack Developer Internship - Backend Focus", "summary": "Next round: assessment"},
    {"id": "e2", "from": "Hiring Team <jobs@acme.ai>", "subject": "Update on your application",
     "summary": "Thank you for applying to AI Engineer Internship - GenAI & ML. Unfortunately we have decided to move forward with other candidates."},
    {"id": "e3", "from": "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
     "subject": "AI Engineer Internship - GenAI & ML at Daice Labs and 9 more", "summary": "Apply now: application closes soon"},
    {"id": "e4", "from": "Unstop <noreply@unstop.com>", "subject": "Data Analyst Internship: your application was viewed",
     "summary": "status update"},
    {"id": "e5", "from": "Someone <a@b.c>", "subject": "Internship application received", "summary": "Thanks for your application"},
]
hits = {h["email_id"]: h for h in RP.matches(emails, tracker, TODAY)}
check("1. a shortlist email about an application is spotted, guessed as good news",
      "e1" in hits and hits["e1"]["key"] == "k1" and hits["e1"]["guess"] == "interview", hits.get("e1"))
check("2. a rejection is spotted and guessed as a no", "e2" in hits and hits["e2"]["guess"] == "rejected", hits.get("e2"))
check("3. a job ALERT carrying the same title is not a reply (LinkedIn, 21 Oct)", "e3" not in hits)
check("4. an application that already has an outcome is not asked about again", "e4" not in hits)
check("5. a title too generic to match ('Internship') never matches", "e5" not in hits)
text, kb = RP.message(hits["e1"])
cbs = [b["callback_data"] for r in kb for b in r]
check("6. he confirms with the bot's existing outcome buttons — nothing is recorded on a guess",
      cbs == ["out:interview:k1", "out:rejected:k1"] and all(len(c.encode()) <= 64 for c in cbs))
check("7. the message is HTML-escaped (an email subject is not trusted markup)",
      "&lt;b&gt;" in RP.message({**hits["e1"], "subject": "a <b> c"})[0])
check("8. an old application (over 60 days) is not matched",
      not RP.matches(emails[:1], {"k1": {**tracker["k1"], "applied_at": "2026-07-01"}}, TODAY))

print("=" * 72)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 72)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
