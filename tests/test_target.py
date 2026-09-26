"""Tests for the STANDING TARGET (filters/target.py).

A target is a goal that keeps applying without anyone retyping a flag: a city, a pay floor, a
date. Two properties matter more than any individual weight:

  1. It RANKS, it never GATES. Missing the target must never remove an opportunity.
  2. Its levers only apply where they mean something. A hackathon has no salary and no office,
     and the first live run proved why that matters - with the levers applied to everything, a
     target meaning "paid internship in Mumbai" promoted a dozen unpaid hackathons to 10/10.

Run:  python tests/test_target.py
"""
import io
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from filters import focus, target
from models import Opportunity

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

BY = date.today() + timedelta(days=70)
SOON = date.today() + timedelta(days=20)
LATE = BY + timedelta(days=30)

_TMP = []
def set_target(**over):
    """Point target.TARGET_FILE at a temp file holding this target."""
    doc = {"active": True, "goal": "g", "by": BY.isoformat(),
           "focus": ["internship", "job"], "locations": ["mumbai", "remote"],
           "min_pay_per_month": 15000, "require_pay": True}
    doc.update(over)
    fd, p = tempfile.mkstemp(suffix=".json"); os.close(fd)
    io.open(p, "w", encoding="utf-8").write(json.dumps(doc))
    _TMP.append(p)
    target.TARGET_FILE = Path(p)
    target.reset_cache()

def clear_target():
    target.TARGET_FILE = Path(tempfile.gettempdir()) / "__no_such_target__.json"
    target.reset_cache()

def opp(title, desc="", source="unstop", tags=None, deadline=SOON, raw=None, score=6):
    o = Opportunity(title=title, url="https://x/" + title[:8], source=source, description=desc,
                    deadline=deadline, tags=list(tags or []), raw=dict(raw or {}))
    o.score = score
    return o

def intern(title="AI Internship", **kw):
    kw.setdefault("tags", ["internship"])
    return opp(title, **kw)

# ── loading ──────────────────────────────────────────────────────────────────────────────
clear_target()
check("1. missing target file = no target", target.load() == {} and not target.active())

set_target(active=False)
check("2. active:false parks the target", not target.active(),
      "so settings can be kept without being applied")

set_target()
check("3. a live target loads", target.active() and target.deadline_by() == BY)

# 4 - the target supplies focus, so no flag is needed
import config
config.FOCUS = []
check("4. target drives focus without a flag", set(focus.active()) == {"internship", "job"})

# 5 - ...but an explicit flag still wins for one run
config.FOCUS = ["hackathon"]
check("5. an explicit --focus overrides the target", focus.active() == ["hackathon"])
config.FOCUS = []

# ── pay extraction ───────────────────────────────────────────────────────────────────────
set_target()
# 6 - structured value from the source is preferred
check("6. structured pay is read", target.pay_of(intern(raw={"pay_max": 25000})) == 25000)

# 7 - an annual figure is normalised to per-month (Unstop mixes stipends and CTC in one field)
check("7. annual CTC normalised to monthly",
      target.pay_of(intern(raw={"pay_max": 1200000})) == 100000, str(target.pay_of(intern(raw={"pay_max": 1200000}))))

# 8 - free text is a fallback
check("8. pay read from text", target.pay_of(intern(desc="Stipend Rs 20,000 per month")) == 20000,
      str(target.pay_of(intern(desc="Stipend Rs 20,000 per month"))))

# 9 - a bare number that is NOT labelled per-month is ignored, so a 100000 prize pool is
#     never mistaken for a salary
check("9. unlabelled money is not treated as salary",
      target.pay_of(opp("Hackathon", "Prize: cash 100000", tags=["hackathon"])) == 0,
      str(target.pay_of(opp("Hackathon", "Prize: cash 100000", tags=["hackathon"]))))

# ── the levers ───────────────────────────────────────────────────────────────────────────
# 10 - a paying role in the right city is lifted
good = intern(raw={"pay_max": 25000, "cities": ["Mumbai"]})
check("10. Mumbai + above floor is lifted", target.adjustment(good) > 0, str(target.reasons(good)))

# 11 - remote counts as a location when you accept remote
rem = intern(raw={"pay_max": 25000, "remote": True})
check("11. remote counts when accepted", target.adjustment(rem) > 0, str(target.reasons(rem)))

# 12 - a role in a city you did NOT name is pushed down
away = intern(raw={"pay_max": 25000, "cities": ["Bangalore"]})
check("12. wrong city is pushed down",
      any(d < 0 for _, d in target.reasons(away)), str(target.reasons(away)))

# 13 - under the floor is pushed down
cheap = intern(raw={"pay_max": 7000, "cities": ["Mumbai"]})
check("13. under the pay floor is pushed down",
      any("only" in why for why, _ in target.reasons(cheap)), str(target.reasons(cheap)))

# 14 - silent on pay, with require_pay on, is pushed down
quiet = intern(raw={"cities": ["Mumbai"]})
check("14. no stated pay is pushed down when require_pay",
      any("does not state" in why for why, _ in target.reasons(quiet)), str(target.reasons(quiet)))

# 15 - ...but NOT when require_pay is off
set_target(require_pay=False)
check("15. require_pay:false forgives unknown pay",
      not any("does not state" in why for why, _ in target.reasons(intern(raw={"cities": ["Mumbai"]}))))

# 16 - a deadline after your date is a real minus
set_target()
late = intern(raw={"pay_max": 25000, "remote": True}, deadline=LATE)
check("16. closing after your by-date is penalised",
      any("after your" in why for why, _ in target.reasons(late)), str(target.reasons(late)))

# 17 - NO bonus for a near deadline: scorer.py already scores urgency, and paying twice handed
#      a free +2 to everything with a date on it (a bug the first live run exposed).
near = intern(raw={"pay_max": 25000, "remote": True}, deadline=SOON)
check("17. no double-counted bonus for a near deadline",
      not any("inside your window" in why for why, _ in target.reasons(near)), str(target.reasons(near)))

# ── THE REGRESSION THAT MATTERS ──────────────────────────────────────────────────────────
# 18 - an online, unpaid hackathon must be left alone by a paid-internship target. Before the
#      fix it collected +3 for "remote, which you accept" and +2 for a near deadline.
hack = opp("Catalyst Hack 2026", "hackathon | online | Team size: 1-4", tags=["hackathon"])
check("18. an unpaid online hackathon is NOT promoted by a paid-job target",
      target.adjustment(hack) == 0, str(target.reasons(hack)))

# 19 - ...and a hackathon closing after the date is still flagged, because that lever is
#      about time, not employment
hack_late = opp("Late Hack", "hackathon | online", tags=["hackathon"], deadline=LATE)
check("19. the by-date lever still applies to non-employment kinds",
      target.adjustment(hack_late) < 0, str(target.reasons(hack_late)))

# 20 - a paper is not a job either
paper = opp("Some Paper", "a study", source="arxiv", deadline=None)
check("20. research is untouched by pay/location levers", target.adjustment(paper) == 0)

# ── it ranks, it never gates ─────────────────────────────────────────────────────────────
set_target()
pool = [good, away, cheap, quiet, hack, paper]
n = len(pool)
target.apply(pool)
check("21. apply() never drops an item", len(pool) == n)
check("22. scores stay inside 0-10", all(0 <= i.score <= 10 for i in pool),
      str([i.score for i in pool]))

# 23 - no target = no movement at all
clear_target()
before = [i.score for i in pool]
check("23. no target = no adjustment", target.apply(pool) == 0 and [i.score for i in pool] == before)

# 24 - describe() is honest about how long is left
set_target()
d = target.describe()
check("24. describe reports the window", "70d left" in d or "d left" in d, d)

# ── the "software sales" false positive (same live run) ──────────────────────────────────
from filters.scorer import score_item
ss = opp("Software Sales Internship", "internship | online | Eligibility: students", tags=["internship"])
se = opp("Software Engineer Internship", "internship | online | Eligibility: students", tags=["internship"])
check("25. 'software sales' is a sales job, not a software job",
      score_item(ss) < score_item(se), f"sales={score_item(ss)} eng={score_item(se)}")
for t2 in ("Tech Sales Internship", "IT Sales Internship", "Digital Marketing Internship",
           "Sales Development Representative Intern"):
    o2 = opp(t2, "internship | online", tags=["internship"])
    check(f"25.{t2.split()[0].lower()} penalised despite a tech word", score_item(o2) <= 5,
          f"{t2}={score_item(o2)}")

clear_target()
for p in _TMP:
    try:
        os.unlink(p)
    except OSError:
        pass

print("=" * 72)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 72)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
