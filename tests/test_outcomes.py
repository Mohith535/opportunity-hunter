"""Tests for Phase 6 — what his ✅/⏭ taps teach the ranking (filters/outcomes.py).

The old learner used TAGS, which appear on planned and skipped items alike: on his real 51 taps it
found 6 likes and 0 avoids. These tests pin the three things the title-word learner must get right:
it learns avoids from skips, it doesn't learn noise from a couple of planned research papers, and it
never counts a word twice when his target already names it.

Run:  python tests/test_outcomes.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from filters import outcomes as O, target
from models import Opportunity

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

def tr(*rows):
    return {f"k{i}": {"title": t, "status": s} for i, (t, s) in enumerate(rows)}

# A slice shaped like his real tracker: skips on sales/marketing/design, plans on engineering roles,
# and two planned papers that share a brand word.
T = tr(("Marketing Internship", "skipped"), ("Marketing and Sales Internship", "skipped"),
       ("Marketing Sales Internship", "skipped"), ("Graphic Designer Internship", "skipped"),
       ("Graphic Designer Internship", "skipped"),
       ("AI Engineer Intern", "planned"), ("Backend Engineer Intern", "applied"),
       ("ML Engineer Internship", "planned"), ("LLM Agents Engineer", "planned"),
       ("Evaluating LLM reasoning at Tesla", "planned"), ("Tesla scaling study", "planned"),
       ("Some Hackathon", "remind"))
L = O.learn(T)

check("1a. skips become avoids (the old tag learner found none)",
      set(L["avoids"]) >= {"marketing", "sales", "graphic", "designer"}, L["avoids"])
check("1b. a word planned 4x is a like", L["likes"].get("engineer") == [4, 0], L["likes"])
check("1c. two planned papers do not teach 'tesla' (a like needs 3)", "tesla" not in L["likes"], L["likes"])
check("1d. 'remind' is neither a like nor a skip", L["signals"] == 11, L["signals"])
check("1e. packaging words never learn ('internship', 'intern')",
      not ({"internship", "intern"} & (set(L["likes"]) | set(L["avoids"]))))
mixed = O.learn(tr(("Sales Engineer", "skipped"), ("Sales Engineer", "skipped"), ("Sales Engineer", "planned"),
                   ("Sales Engineer", "planned"), ("Sales Engineer", "planned")))
check("1f. more plans than skips is never an avoid", "sales" not in mixed["avoids"], mixed)

# ── nudges ───────────────────────────────────────────────────────────────────────────────────
fd, tp = tempfile.mkstemp(suffix=".json"); os.close(fd)
_old = target.TARGET_FILE
target.TARGET_FILE = Path(tp)
Path(tp).write_text(json.dumps({"active": True, "avoid": ["marketing"], "roles": {"tier1": ["ai engineer"]}}),
                    encoding="utf-8")
target.reset_cache()
try:
    job = lambda t: Opportunity(t, "https://x/" + t[:6], "unstop", "", tags=["internship"])
    g = O.reasons(job("Graphic Designer Internship"), L)
    check("2a. a learned skip pushes down, capped", O.adjustment(job("Graphic Designer Internship"), L) == -4
          and "skip" in g[0][0], g)
    check("2b. a word the target already avoids is left to the target (no double count)",
          O.adjustment(job("Digital Marketing Internship"), L) == 0, O.reasons(job("Digital Marketing Internship"), L))
    check("2d. 'engineer' is covered by the target's 'ai engineer' — no double lift",
          O.adjustment(job("Platform Engineer Intern"), L) == 0, O.reasons(job("Platform Engineer Intern"), L))
    Path(tp).write_text(json.dumps({"active": True}), encoding="utf-8"); target.reset_cache()
    check("2e. without that target word, the like applies (+1)", O.adjustment(job("Platform Engineer Intern"), L) == 1)
    talk = Opportunity("Inside the Software Industry: Skills & Career Growth", "https://x/t", "unstop", "",
                       tags=["meetup"])
    check("2e2. a learned word never touches a talk (the 'career growth' false positive)",
          O.adjustment(talk, L | {"avoids": {**L["avoids"], "growth": [0, 2]}}) == 0)
    check("2f. nothing learned, nothing moves", O.adjustment(job("Graphic Designer"), {"likes": {}, "avoids": {}}) == 0)
    items = [job("Graphic Designer Internship"), job("Platform Engineer Intern"), job("Chef")]
    for i in items:
        i.score = 9
    O.reset_cache(L)
    moved = O.apply(items)
    check("2g. apply() nudges, never drops, stays in 0-10",
          moved == 2 and len(items) == 3 and [i.score for i in items] == [5, 10, 9], [i.score for i in items])
finally:
    target.TARGET_FILE = _old; target.reset_cache(); O.reset_cache(None)
    os.unlink(tp)

# ── no bot, no network ───────────────────────────────────────────────────────────────────────
for k in ("OH_WORKER_URL", "OH_WORKER_TOKEN"):
    os.environ.pop(k, None)
check("3a. with no bot configured, nothing is fetched and nothing is learned",
      O.fetch_tracker() is None and O.learned()["signals"] == 0 and O.publish({"likes": {}, "avoids": {}}) is False)

print("=" * 72)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 72)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
