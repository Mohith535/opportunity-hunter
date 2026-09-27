"""Tests for Phase 5A — packs to Telegram from the daily cloud run (resume/push.py), and the
public-log redaction that has to be true before his target is allowed into the cloud.

Two failure classes matter most. Sending the wrong thing (a ⛔ job, a hackathon, yesterday's items
again) wastes the one notification a day he actually reads. Printing the wrong thing is worse: the
repo is public, so the Action log is public, and a target's goal is personal by design.

Run:  python tests/test_push.py
"""
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
import resume.push as P
from resume.eligibility import CHECK, NO, YES, Verdict


# Never reach the live bot from a test: .env carries OH_WORKER_URL on his laptop.
from filters import outcomes as _outcomes
_outcomes.reset_cache({"likes": {}, "avoids": {}, "signals": 0})

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

# ── 1. only today's run, so nothing is sent twice ────────────────────────────────────────────
fd, hp = tempfile.mkstemp(suffix=".json"); os.close(fd)
_old_hist = config.HISTORY_FILE
config.HISTORY_FILE = Path(hp)
today = date.today()
Path(hp).write_text(json.dumps({"runs": [{"date": (today - timedelta(days=1)).isoformat(), "items": [{"title": "old"}]}]}),
                    encoding="utf-8")
check("1a. yesterday's run is not today's", P.latest_run() == [])
check("1b. --any-day takes it anyway (testing)", [i["title"] for i in P.latest_run(any_day=True)] == ["old"])
Path(hp).write_text(json.dumps({"runs": [{"date": today.isoformat(), "items": [{"title": "new"}]}]}), encoding="utf-8")
check("1c. today's run is used", [i["title"] for i in P.latest_run()] == ["new"])
Path(hp).write_text("not json", encoding="utf-8")
check("1d. a broken history is an empty day, not a crash", P.latest_run() == [])
config.HISTORY_FILE = _old_hist
os.unlink(hp)

# ── 2. which rows get a pack ─────────────────────────────────────────────────────────────────
def row(n, title, tags, score, level, off=False):
    return (n, {"title": title, "url": f"https://x/{n}", "source": "unstop", "tags": tags,
                "description": "internship"}, score, Verdict(level, []), off)

rows = [row(1, "Backend Developer Internship", ["internship"], 9, YES),
        row(2, "Senior .Net Developer", ["job"], 10, NO),
        row(3, "AI Hackathon", ["hackathon"], 10, YES),
        row(4, "Data Analyst Internship", ["internship"], 6, YES),
        row(5, "ML Engineer Intern", ["internship"], 8, CHECK),
        row(6, "Marketing Internship", ["internship"], 9, YES, off=True)]
got = [r[1]["title"] for r in P.pick(rows, 7)]
check("2a. a ⛔ job never gets a pack", "Senior .Net Developer" not in got, got)
check("2b. a hackathon does not need a resume", "AI Hackathon" not in got, got)
check("2c. below the bar is left out", "Data Analyst Internship" not in got, got)
check("2d. ⚠ CHECK still gets a pack (the card says what to check)", "ML Engineer Intern" in got, got)
check("2e. off-focus is left out", "Marketing Internship" not in got, got)
check("2f. order is kept", got == ["Backend Developer Internship", "ML Engineer Intern"], got)

# ── 3. the card ──────────────────────────────────────────────────────────────────────────────
item = {"title": "R&D <Intern> — AI & Agents", "url": "https://unstop.com/x", "source": "unstop",
        "tags": ["internship"], "deadline": (today + timedelta(days=5)).isoformat(), "key": "abc123def456"}
pack = {"company": "Acme & Co", "full": {"location": "Mumbai", "pay_note": "Rs 30,000/month",
                                         "apply_url": "https://acme.example/apply"}}
v = Verdict(CHECK, [(CHECK, "courses listed: mba1 — B.Tech not named"), (YES, "passout 2029 accepted")])
fit = [("python", "BUILT", "x"), ("docker", "LEARNED", "y"), ("php", "GAP", "")]
c = P.card(item, 8, v, pack, fit, "✓ a tier-1 role for you (ai agents)")
check("3a. HTML is escaped (R&D <Intern> cannot break the caption)",
      "R&amp;D &lt;Intern&gt;" in c and "Acme &amp; Co" in c, c[:120])
check("3b. the warning is on the card", "B.Tech not named" in c, c)
check("3c. fit counts and gaps", "2 of 3 skills backed (1 built, 1 studied)" in c and "gap: php" in c, c)
check("3d. days left are counted", "(5 days)" in c, c)
check("3e. why it ranks here", "tier-1 role" in c, c)
huge = dict(item, title="T" * 500)
big = P.card(huge, 8, Verdict(YES, []), dict(pack, company="C" * 900), fit, "N" * 900)
check("3f. never over Telegram's 1024-character caption limit", P._visible_len(big) <= 1024, P._visible_len(big))

# ── 4. buttons reuse the Worker's existing actions ───────────────────────────────────────────
kb = P.buttons(item, pack)
cbs = [b["callback_data"] for r in kb for b in r if "callback_data" in b]
check("4a. Applied / Skip / Remind, keyed like the digest",
      cbs == ["applied:abc123def456", "skip:abc123def456", "remind:abc123def456"], cbs)
check("4b. callback_data within Telegram's 64 bytes", all(len(x.encode()) <= 64 for x in cbs))
check("4c. the apply link comes from the full listing", kb[0][0]["url"] == "https://acme.example/apply")
kb2 = P.buttons(dict(item, url="javascript:alert(1)", key=""), {"full": {}})
check("4d. a non-http link gets no button; a missing key is derived",
      all("url" not in b for r in kb2 for b in r) and all(":" in b["callback_data"] and len(b["callback_data"]) > 8
                                                        for b in kb2[-1]))

# ── 5. it never sends when it should not ─────────────────────────────────────────────────────
import requests
calls = []
_old_post = requests.post
requests.post = lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("network"))
_old_tok, _old_chat = config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID
import resume.apply as A
_old_profile = A._profile
try:
    check("5a. OH_PACKS=0 switches it off", P.run(n=0) == 0 and not calls)
    A._profile = lambda: {}
    check("5b. no career profile, no pack", P.run(n=3) == 0 and not calls)
    A._profile = lambda: {"basics": {"name": "x"}}
    config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID = "", ""
    check("5c. Telegram not configured → nothing sent", P.run(n=3) == 0 and not calls)
finally:
    A._profile = _old_profile
    config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID = _old_tok, _old_chat
    requests.post = _old_post

# ── 6. an error log never carries the bot token ──────────────────────────────────────────────
logged = []
_old_log = P.log
P.log = lambda msg, level="INFO": logged.append(msg)
config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID = "123456:SECRET-TOKEN-VALUE", "42"
def boom(url, **k):
    raise requests.ConnectionError(f"Max retries exceeded with url: {url}")
requests.post = boom
fd, fp = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
try:
    mid = P._send_document(Path(fp), "r.pdf", "cap")
    check("6a. a failed send returns None", mid is None)
    check("6b. the log names the error but not the token",
          logged and all("SECRET-TOKEN" not in m for m in logged), logged)
finally:
    requests.post = _old_post
    P.log = _old_log
    config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID = _old_tok, _old_chat
    os.unlink(fp)

# ── 7. public logs: the target stays private ─────────────────────────────────────────────────
from filters import target
import daily_brief
from models import Opportunity
fd, tp = tempfile.mkstemp(suffix=".json"); os.close(fd)
Path(tp).write_text(json.dumps({"active": True, "goal": "PRIVATE-REASON-XYZ internship in Pune",
                                "locations": ["pune"], "min_pay_per_month": 27000, "focus": ["internship"]}),
                    encoding="utf-8")
_old_tf, _old_pl = target.TARGET_FILE, config.PUBLIC_LOGS
target.TARGET_FILE = Path(tp); target.reset_cache()
it = Opportunity("Backend Intern", "https://x/b", "unstop", "internship", tags=["internship"],
                 raw={"cities": ["Pune"], "pay_max": 35000})
try:
    config.PUBLIC_LOGS = False
    check("7a. locally the goal is shown", "PRIVATE-REASON-XYZ" in target.describe())
    check("7b. locally the brief explains the target nudge", "in Pune" in daily_brief._render_item(it, False).plain)
    config.PUBLIC_LOGS = True
    d = target.describe()
    check("7c. in public logs the goal is not", "PRIVATE-REASON" not in d and "Pune" not in d.title() and "27" not in d, d)
    txt = daily_brief._render_item(it, False).plain
    check("7d. in public logs the brief drops the per-item target note",
          "in Pune" not in txt and "35,000" not in txt, txt)
finally:
    target.TARGET_FILE, config.PUBLIC_LOGS = _old_tf, _old_pl
    target.reset_cache()
    os.unlink(tp)

# ── 8. the secret the cloud decodes is the file you have ─────────────────────────────────────
import sync_secrets as S
raw = json.dumps({"basics": {"name": "Ωmega é"}, "projects": [{"x": "y" * 400}] * 60}).encode("utf-8")
packed = S.encode(raw, True)
check("8a. gzip+base64 round-trips byte for byte", S.decode(packed, True) == raw)
check("8b. packing shrinks a profile-shaped file", len(packed) < len(raw) / 2, f"{len(packed)} vs {len(raw)}")
pretty = json.dumps({"goal": "x", "roles": {"tier1": ["a", "b"]}}, indent=2).encode()
one = S.encode(pretty, False)
check("8c. the target goes as ONE line (GitHub masks multi-line secrets line by line)",
      "\n" not in one and json.loads(one) == json.loads(pretty), one)

# ── 9. the target: laptop and phone, whichever changed last wins ─────────────────────────────
import time as _time
class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body, self.ok = status, body, 200 <= status < 300
    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body

fd, tf = tempfile.mkstemp(suffix=".json"); os.close(fd)
local = {"active": True, "goal": "laptop", "locations": ["mumbai"]}
Path(tf).write_text(json.dumps(local), encoding="utf-8")
now = _time.time()
os.utime(tf, (now - 3600, now - 3600))                       # the laptop file is an hour old
os.environ["OH_WORKER_URL"], os.environ["OH_WORKER_TOKEN"] = "https://bot.example.dev", "t0k"
put_calls = []
_old_get, _old_put = requests.get, requests.put
try:
    from datetime import datetime as _dt, timezone as _tz
    phone_ts = _dt.fromtimestamp(now - 60, _tz.utc).isoformat()
    requests.get = lambda url, **k: _Resp(200, {"target": {"active": True, "goal": "phone", "locations": ["pune"]},
                                                "updated_at": phone_ts, "source": "phone"})
    requests.put = lambda url, **k: put_calls.append(k.get("json")) or _Resp(200, {"ok": True})
    msg = target.sync_with_bot(Path(tf))
    got = json.loads(Path(tf).read_text(encoding="utf-8"))
    check("9a. a newer phone edit is pulled into the laptop file",
          got["goal"] == "phone" and "phone" in msg and not put_calls, (msg, got))
    check("9b. the pulled file carries the phone's time, so the next sync is a no-op",
          abs(os.path.getmtime(tf) - (now - 60)) < 2 and target.sync_with_bot(Path(tf)) == "in sync with the bot")

    Path(tf).write_text(json.dumps(local), encoding="utf-8")      # edited on the laptop just now
    msg = target.sync_with_bot(Path(tf))
    check("9c. a newer laptop edit is sent to the bot",
          msg == "sent to the bot" and put_calls and put_calls[-1]["target"]["goal"] == "laptop", (msg, put_calls[-1:]))

    # A stale read (KV lags a phone edit by up to a minute) makes the laptop think it is newer; the bot
    # answers 409 with its newer copy, and the laptop must TAKE it, not report a failure.
    Path(tf).write_text(json.dumps(local), encoding="utf-8")
    newer = _dt.fromtimestamp(_time.time() + 30, _tz.utc).isoformat()
    requests.get = lambda url, **k: _Resp(404)
    requests.put = lambda url, **k: _Resp(409, {"target": {"active": True, "goal": "phone-newest"},
                                                "updated_at": newer, "source": "phone"})
    msg = target.sync_with_bot(Path(tf))
    check("9c2. a 409 means the phone's newer copy wins, and the laptop takes it",
          json.loads(Path(tf).read_text(encoding="utf-8"))["goal"] == "phone-newest" and "phone" in msg, msg)
    requests.put = lambda url, **k: put_calls.append(k.get("json")) or _Resp(200, {"ok": True})

    requests.get = lambda url, **k: _Resp(401)
    before = Path(tf).read_text(encoding="utf-8")
    msg = target.sync_with_bot(Path(tf))
    check("9d. a refused token changes nothing and says so",
          "HTTP 401" in msg and Path(tf).read_text(encoding="utf-8") == before, msg)

    requests.get = lambda url, **k: (_ for _ in ()).throw(requests.ConnectionError("down"))
    check("9e. an unreachable bot never raises", "unavailable" in target.sync_with_bot(Path(tf)))

    del os.environ["OH_WORKER_URL"]
    check("9f. no bot configured → silent no-op", target.sync_with_bot(Path(tf)) == "")
finally:
    requests.get, requests.put = _old_get, _old_put
    os.environ.pop("OH_WORKER_URL", None); os.environ.pop("OH_WORKER_TOKEN", None)
    os.unlink(tf)

# ── 10. one pack on request (📦 / /pack N) ───────────────────────────────────────────────────
check("10a. --key refuses anything that is not a 12-hex item key",
      P.run_key("../../etc", dry=True) == 0 and P.run_key("", dry=True) == 0)
fd, hp = tempfile.mkstemp(suffix=".json"); os.close(fd)
config.HISTORY_FILE = Path(hp)
from models import dedup_key_from_dict
old_item = {"title": "Backend Intern", "url": "https://x/old", "source": "unstop"}      # an old run: no "key"
Path(hp).write_text(json.dumps({"runs": [{"date": "2026-09-01", "items": [old_item]},
                                         {"date": "2026-09-27", "items": [{"title": "New", "url": "u", "key": "aaaaaaaaaaaa"}]}]}),
                    encoding="utf-8")
try:
    check("10b. a key is found across ALL of history, even in runs saved before keys were stored",
          (P.find_by_key(dedup_key_from_dict(old_item)) or {}).get("url") == "https://x/old")
    check("10c. an unknown key is None", P.find_by_key("bbbbbbbbbbbb") is None)
finally:
    config.HISTORY_FILE = _old_hist
    os.unlink(hp)

# ── 11. the 📦 button on the digest ──────────────────────────────────────────────────────────
import main as M
intern = Opportunity("Backend Developer Internship", "https://x/i", "unstop", "internship", tags=["internship"])
hack = Opportunity("AI Hackathon", "https://x/h", "devpost", "hackathon", tags=["hackathon"])
intern.score = hack.score = 9
_, kb = M._telegram_digest([intern, hack], [])
cbs = [b.get("callback_data", "") for row in kb for b in row]
check("11a. an internship gets a 📦 Pack button", f"pack:{intern.dedup_key()}" in cbs, cbs)
check("11b. a hackathon does not", f"pack:{hack.dedup_key()}" not in cbs, cbs)

print("=" * 72)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 72)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
