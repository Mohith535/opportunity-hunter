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

# 4 Nov: his one chat. Alerts go through the bot's /tell (EDI when switched over); a refusal falls back to
# OPH's chat; the reply date is marked on the row. The network is faked: .env carries the live bot URL.
import requests  # noqa: E402
from notifiers import telegram as TG  # noqa: E402

class _R:
    def __init__(self, code, body): self.status_code, self.ok, self._b = code, code < 400, body
    def json(self): return self._b
posts, direct = [], []
_post, _send = requests.post, TG.send_telegram
os.environ["OH_WORKER_URL"], os.environ["OH_WORKER_TOKEN"] = "https://bot.example.dev", "t0k"
TG.send_telegram = lambda text, buttons=None, **k: direct.append(text) or True
try:
    requests.post = lambda url, **k: posts.append((url, k.get("json"))) or _R(200, {"ok": True, "via": "edi"})
    ok1 = TG.tell("reply_alert", "hi", [[{"text": "x", "callback_data": "out:interview:k1"}]])
    requests.post = lambda url, **k: posts.append((url, k.get("json"))) or _R(200, {"ok": False, "via": "none"})
    ok2 = TG.tell("digest", "one line", fallback=False)
    requests.post = lambda url, **k: (_ for _ in ()).throw(requests.ConnectionError("down"))
    ok3 = TG.tell("weekly", "picks")
    requests.post = lambda url, **k: posts.append((url, k.get("json"))) or _R(200, {"ok": True})
    seen_ok = RP.seen("k1")
finally:
    requests.post, TG.send_telegram = _post, _send
    os.environ.pop("OH_WORKER_URL", None); os.environ.pop("OH_WORKER_TOKEN", None)
check("5. a reply alert goes through the bot's /tell with its kind and buttons, nothing sent directly",
      ok1 and posts[0][0] == "https://bot.example.dev/tell" and posts[0][1]["kind"] == "reply_alert"
      and posts[0][1]["buttons"][0][0]["callback_data"] == "out:interview:k1" and "hi" not in direct, posts[:1])
check("6. a one-liner with no fallback is not re-sent to OPH's chat when EDI says no",
      ok2 is False and "one line" not in direct)
check("7. the bot unreachable → straight to OPH's chat, so the message is not lost", ok3 and "picks" in direct)
check("8. the reply date is marked on that row, by key only", seen_ok and posts[-1] == ("https://bot.example.dev/reply-seen", {"key": "k1"}))

print("=" * 72)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 72)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
