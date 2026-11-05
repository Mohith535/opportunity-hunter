"""Tests for the hourly fresh-postings watcher (filters/fresh.py, main.py --fresh), 4 Nov 2026.

Run:  python tests/test_fresh.py
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from filters import fresh as F
from models import Opportunity

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
r = lambda v: {"raw": {"posted": v}}  # noqa: E731

# Every board's own format, from the live APIs read on 4 Nov.
check("1. Greenhouse first_published (ISO with offset) → hours old",
      round(F.hours_old(r("2026-11-04T05:00:00-04:00"), NOW)) == 3)
check("2. Lever / Microsoft / SimplifyJobs / Himalayas epoch, in seconds or ms",
      F.posted_at(r(1793779690), NOW) == F.posted_at(r(1793779690000), NOW) == F.posted_at(r("1793779690"), NOW))
check("3. Unstop approved_date '2026-11-04 16:22:34 GMT+0530' is 10:52 UTC",
      F.posted_at(r("2026-11-04 16:22:34 GMT+0530"), NOW) == datetime(2026, 11, 4, 10, 52, 34, tzinfo=timezone.utc))
check("4. Workday 'Posted Today' is fresh; 'Posted 30+ Days Ago' is not; Amazon 'November 3, 2026' is",
      F.is_fresh(r("Posted Today"), NOW) and not F.is_fresh(r("Posted 30+ Days Ago"), NOW)
      and F.is_fresh(r("November 3, 2026"), NOW))
check("5. no date, a junk date or a zero → never fresh (the daily digest keeps those)",
      not any(F.is_fresh(r(v), NOW) for v in (None, "", 0, "soon", "13/45/2026")))
check("6. the badge: last hour / N h / yesterday / nothing after 48 h",
      [F.badge(r(v), NOW) for v in ("2026-11-04T11:30:00Z", "2026-11-04T02:00:00Z", "2026-11-03T06:00:00Z",
                                    "2026-11-01T06:00:00Z")]
      == ["🆕 posted in the last hour", "🆕 posted 10 h ago", "🆕 posted yesterday", ""])

import main as M  # noqa: E402
it = Opportunity(title="Software Engineer Intern — Acme", url="https://acme.dev/jobs/1", source="ats",
                 description="internship", native_id="gh:acme:1", tags=["internship"],
                 raw={"company": "Acme", "posted": datetime.now(timezone.utc).isoformat()})
text, kb = M.fresh_alert(it)
check("7. the alert says FRESH and when, names the role, and pushes to apply today",
      text.startswith("🚨🆕 <b>FRESH — POSTED IN THE LAST HOUR</b>") and "Software Engineer Intern — Acme" in text and '<a href="https://acme.dev/jobs/1">' in text
      and "Apply today" in text, text)
key = it.dedup_key()
check("8. its buttons: Open, Pack, Applied, Skip — all ≤ 60 bytes, so they also work in EDI's chat",
      kb[0][0]["url"] == it.url and [b.get("callback_data") for b in kb[0][1:] + kb[1]]
      == [f"pack:{key}", f"applied:{key}", f"skip:{key}"]
      and all(len(b["callback_data"]) <= 60 for row in kb for b in row if "callback_data" in b), kb)

it.tags.append("eligibility:verify")
check("8b. a role whose rules need checking says so in the alert (Shield AI, Dallas, 4 Nov)",
      "⚠ Check first" in M.fresh_alert(it)[0] and "⚠" not in text)

import sources  # noqa: E402
check("9. the watcher's Unstop slice never joins the daily run (it reads all of Unstop already)",
      "unstop_jobs" not in sources.get_sources(None) and list(sources.get_sources(["unstop_jobs"])) == ["unstop_jobs"]
      and set(M.FRESH_SOURCES) <= set(sources.available_sources()))

# 5 Nov, live: "[llm] scored 8/8 … 8 dropped after the model scored them below HIGH" every hour from 12:20 to
# 17:20 IST. Those 8 are never marked seen (the daily run still ranks them), so they came straight back and
# filled all 8 model slots, and a newer posting ranked under them was never read.
import tempfile  # noqa: E402
tmp = os.path.join(tempfile.mkdtemp(), "fresh_checked.json")
ck = {}
added = F.remember(ck, ["a", "b"], NOW) + F.remember(ck, ["b", "c"], NOW)
ck["old"] = "2026-11-01T00:00:00Z"
F.save_checked(ck, tmp)
back = F.load_checked(tmp, NOW)
open(tmp + ".bad", "w").write("{not json")
check("10. turned-down roles are remembered for 48 h and then forgotten; a broken file means none",
      added == 3 and set(back) == {"a", "b", "c"} and F.load_checked(tmp + ".bad", NOW) == {}
      and F.load_checked(tmp + ".missing", NOW) == {})

posted = datetime.now(timezone.utc).isoformat()
roles = [Opportunity(title=f"Backend Engineer Intern {n} — Acme", url=f"https://acme.dev/jobs/{n}", source="ats",
                     description="internship", native_id=f"gh:acme:{n}", tags=["internship"], score=10 - n // 5,
                     raw={"company": "Acme", "posted": posted}) for n in range(9)]
turned_down = {r.dedup_key(): "x" for r in roles[:8]}
picked = M.fresh_pick(roles, turned_down)
check("11. the 8 the model turned down no longer fill every slot: the 9th, ranked under them, is read",
      [r.native_id for r in picked] == ["gh:acme:8"] and len(M.fresh_pick(roles, {})) == M.FRESH_MAX + 3,
      [r.native_id for r in picked])

print("=" * 72)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 72)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
