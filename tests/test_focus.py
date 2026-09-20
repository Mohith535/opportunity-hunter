"""Tests for FOCUS (filters/focus.py) and the closed-round deadline radar (sources/programs.py).

Focus decides what gets hunted this week. Two things must hold, or it is worse than useless:
  1. It never silently hides something genuinely critical.
  2. It classifies the categories Mohith actually named, not a taxonomy we invented.

Run:  python tests/test_focus.py
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
from filters import focus
from models import Opportunity

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

def opp(title, source="unstop", desc="", score=5, tags=None):
    o = Opportunity(title=title, url="https://x/" + title[:10], source=source,
                    description=desc, tags=list(tags or []))
    o.score = score
    return o

def with_focus(kinds, mode="boost"):
    """Temporarily set the focus config (restored by the caller via restore())."""
    config.FOCUS, config.FOCUS_MODE = kinds, mode

_ORIG = (list(getattr(config, "FOCUS", [])), getattr(config, "FOCUS_MODE", "boost"))
def restore():
    config.FOCUS, config.FOCUS_MODE = _ORIG

# ── kind_of: the categories he actually named ────────────────────────────────────────────
# 1 - the source settles it when the source is unambiguous
check("1. arxiv is always research", focus.kind_of(opp("Hackathon Scaling Laws", "arxiv")) == "research",
      "a paper titled 'hackathon' is still a paper")

# 2 - the paid ambassador program he missed classifies correctly
check("2. campus ambassador detected",
      focus.kind_of(opp("Claude Campus Ambassador Program", "programs", "USD 3,600 stipend")) == "ambassador")

# 3 - fellowship
check("3. fellowship detected",
      focus.kind_of(opp("MLH Fellowship", "programs", "open source fellows program")) == "fellowship")

# 4 - government funding lands in grant, not startup
check("4. government scheme is a grant",
      focus.kind_of(opp("Startup India Seed Fund Scheme", "programs", "Up to Rs 20 lakh via incubators")) == "grant")

# 5 - accelerator wins the ambiguous word "residency"
check("5. Antler Residency is startup, not fellowship",
      focus.kind_of(opp("Antler India Residency", "programs", "day-zero accelerator cohort")) == "startup")

# 6 - ...but a residency with no startup wording is still a fellowship
check("6. bare residency stays fellowship",
      focus.kind_of(opp("OpenAI Residency", "programs", "six month residency for researchers")) == "fellowship")

# 7 - an unstop tag beats our keyword guess
check("7. source tag wins",
      focus.kind_of(opp("Innovation Challenge 2026", "unstop", "build something", tags=["hackathon"])) == "hackathon")

# ── apply(): ranking ─────────────────────────────────────────────────────────────────────
# 8 - no focus set is a true no-op
with_focus([])
items = [opp("A", score=5), opp("B", score=7)]
out = focus.apply(items)
check("8. no focus = untouched", len(out) == 2 and out[0].score == 5 and out[1].score == 7)

# 9 - boost mode lifts on-topic and demotes off-topic, hiding nothing
with_focus(["hackathon"])
hack = opp("Smart India Hackathon", tags=["hackathon"], score=6)
paper = opp("Some Paper", "arxiv", score=6)
out = focus.apply([hack, paper])
check("9. boost lifts the focus kind", hack.score == 8, f"got {hack.score}")
check("10. boost demotes off-topic", paper.score == 4, f"got {paper.score}")
check("11. boost hides nothing", len(out) == 2)

# 12 - the tag explains the re-ranking (never silent)
check("12. focus tags are recorded",
      "focus:hackathon" in hack.tags and "focus:off-topic" in paper.tags)

# ── apply(): "only" mode and the safety hatch ────────────────────────────────────────────
# 13 - only mode really does drop off-topic items
with_focus(["hackathon"], "only")
hack2 = opp("AI Hackathon", tags=["hackathon"], score=6)
paper2 = opp("Some Paper", "arxiv", score=6)
out = focus.apply([hack2, paper2])
check("13. only mode drops off-topic", len(out) == 1 and out[0] is hack2)

# 14 - THE IMPORTANT ONE: a critical off-topic item is never hidden
with_focus(["hackathon"], "only")
gold = opp("Thiel Fellowship", "programs", "USD 200,000", score=focus.KEEP_ANYWAY)
out = focus.apply([gold])
check("14. only mode still shows a 9+ off-topic item", len(out) == 1,
      "a once-a-year fellowship must survive 'hackathons only'")

# 15 - one below the hatch is dropped, so the hatch is a real threshold not a bypass
with_focus(["hackathon"], "only")
near = opp("Some Fellowship", "programs", "stipend", score=focus.KEEP_ANYWAY - 1)
check("15. just below the hatch is dropped", len(focus.apply([near])) == 0)

# 16 - unknown focus kinds are ignored rather than silently filtering everything out
with_focus(["nonsense-kind"])
check("16. unknown focus kind = no focus", focus.active() == [])

# 17 - describe() tells the brief what happened
with_focus(["hackathon", "fellowship"], "only")
d = focus.describe()
check("17. describe names mode and kinds", "only" in d and "hackathon" in d and "fellowship" in d, d)

restore()

# ── the deadline radar must not invent urgency for a closed round ────────────────────────
import json
import tempfile
import sources.programs as programs

def radar(window, round_closed=None):
    payload = {"programs": [{"id": "t", "title": "T", "url": "u",
                             "deadline": None, "window": window, "tags": [],
                             "description": "d", **({"round_closed": round_closed} if round_closed else {})}]}
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    open(path, "w", encoding="utf-8").write(json.dumps(payload))
    orig = programs.PROGRAMS_FILE
    programs.PROGRAMS_FILE = __import__("pathlib").Path(path)
    try:
        return programs.fetch()[0]
    finally:
        programs.PROGRAMS_FILE = orig
        os.unlink(path)

this_month = date.today().strftime("%b").lower()
# 18 - in season with no closed round: still fires, as before (no regression)
it = radar(f"Applications ~{this_month}")
check("18. in-season still opens the window", "in-season" in it.tags and it.deadline is not None)

# 19 - in season BUT this year's round already closed: no false urgency
closed = date(date.today().year, date.today().month, 1).isoformat()
it = radar(f"Applications ~{this_month}", round_closed=closed)
check("19. closed round does not invent a deadline", it.deadline is None and "in-season" not in it.tags,
      f"deadline={it.deadline} tags={it.tags}")
check("20. closed round says so, and names the next one",
      "CLOSED" in it.description and str(date.today().year + 1) in it.description)

# 21 - a round closed in a PRIOR year must not suppress this year's window
it = radar(f"Applications ~{this_month}", round_closed=f"{date.today().year - 1}-01-01")
check("21. last year's closure does not block this year", "in-season" in it.tags, str(it.tags))

# ── report ───────────────────────────────────────────────────────────────────────────────
print("=" * 68)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 68)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
