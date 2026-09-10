"""Tests for explainable ranking (filters/explain.py).

Run:  python tests/test_explain.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from filters.explain import explain, breakdown, dimensions_of

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

class It:
    def __init__(self, d): self.dimensions = d

# 1 - never invent: no LLM dimensions means no rationale at all
check("1. rule-scored item gets NO invented rationale", explain(It({})) == "")
check("1b. and no fake breakdown either", breakdown(It({})) == "")

# 2 - names the real drivers
e = explain(It({"career": 9, "interest": 8, "prestige": 7, "deadline": 6, "skill": 3, "time": 5}))
check("2. names top drivers by weighted contribution", "career fit" in e and "interest match" in e, e)
check("2b. names the weakness", "weak on" in e, e)

# 3 - the weakness named is the one that COSTS most, not the lowest raw number
#     career 3 (w .35) hurts more than prestige 2 (w .15)
e3 = explain(It({"career": 3, "interest": 4, "prestige": 2, "deadline": 9, "skill": 8, "time": 6}))
check("3. weakness = biggest cost (career), not lowest number (prestige)",
      "weak on career fit" in e3, e3)

# 4 - eligibility overrides everything and leads
e4 = explain(It({"career": 9, "interest": 9, "eligible": "no", "elig_note": "PhD required"}))
check("4. ineligible leads the line", e4.startswith("not eligible"), e4)
check("4b. and carries the reason", "PhD required" in e4, e4)

# 5 - unclear eligibility is flagged, not hidden
e5 = explain(It({"career": 8, "interest": 7, "eligible": "unclear"}))
check("5. unclear eligibility flagged", "verify eligibility" in e5, e5)

# 6 - a genuinely average item says so instead of faking a strength
e6 = explain(It({"career": 5, "interest": 5, "prestige": 5, "deadline": 5, "skill": 5, "time": 5}))
check("6. average item admits it is average", "balanced" in e6, e6)

# 7 - non-numeric extras never leak into the dimension math
check("7. extras (eligible/regret) excluded from dimensions",
      set(dimensions_of(It({"career": 8, "eligible": "yes", "regret": True}))) == {"career"})

# 8 - partial dimensions do not crash
check("8. partial dimensions handled", isinstance(explain(It({"career": 9})), str))

print("\n" + "=" * 60)
print("EXPLAINABLE RANKING TESTS")
print("=" * 60)
p = 0
for n, ok, d in R:
    print(("  PASS  " if ok else "  FAIL  ") + n + (f"   [{d}]" if d and not ok else ""))
    p += ok
print("=" * 60)
print(f"{p}/{len(R)} passed")
sys.exit(0 if p == len(R) else 1)
