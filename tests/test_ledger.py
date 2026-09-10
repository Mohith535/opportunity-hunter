"""Tests for the Source Signal Ledger (filters/ledger.py).

Run:  python tests/test_ledger.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
from filters import ledger

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

def hist(spec):
    """spec: {source: [scores]} -> a temp history.json path"""
    items = [{"title": f"{s}{i}", "url": f"u{i}", "source": s, "ai_score": sc, "tags": []}
             for s, scores in spec.items() for i, sc in enumerate(scores)]
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    json.dump({"runs": [{"items": items}]}, open(path, "w", encoding="utf-8"))
    return path

# 1 - a source below MIN_SAMPLE gets NO opinion (8 observations is not evidence)
p = hist({"tiny": [10] * 8, "big": [9] * 40})
led = ledger.build(p)
check("1. under-sampled source is not judged", led["tiny"]["judged"] is False
      and led["tiny"]["adjust"] == 0.0)
check("1b. well-sampled source IS judged", led["big"]["judged"] is True)

# 2 - bands: a proven source is lifted, a noisy one is pushed down
p = hist({"gold": [9] * 40, "noise": [1] * 100})
led = ledger.build(p)
check("2. proven source lifted", led["gold"]["adjust"] > 0, str(led["gold"]["adjust"]))
check("2b. noisy source pushed down", led["noise"]["adjust"] < 0, str(led["noise"]["adjust"]))

# 3 - the adjustment is BOUNDED: it nudges, it never censors
check("3. adjustment never exceeds +/-1", all(abs(e["adjust"]) <= 1.0 for e in led.values()))

# 4 - hit rate is computed off the HIGH threshold, not the raw mean
p = hist({"mixed": [7] * 25 + [1] * 25})     # exactly half clear HIGH
led = ledger.build(p)
check("4. hit_rate = fraction clearing HIGH", abs(led["mixed"]["hit_rate"] - 0.5) < 0.01,
      str(led["mixed"]["hit_rate"]))

# 5 - a missing / unreadable history never crashes the run
check("5. missing history -> empty ledger, no crash", ledger.build("does_not_exist.json") == {})

# 6 - unscored items (ai_score -1) fall back to the rule score
p = hist({"x": [-1] * 40})
led = ledger.build(p)
check("6. unscored items do not inflate the hit rate", led["x"]["hit_rate"] == 0.0)

# 7 - the toggle really disables the effect end to end
from models import Opportunity
from filters import policy
o = Opportunity("t", "u", "reddit", "d"); o.ai_score = 7
ledger._CACHE = {"reddit": {"adjust": -1.0, "judged": True, "hit_rate": 0.01, "band": "mostly noise"}}
on = policy.effective_score(o)
config.LEDGER_ENABLED = False
off = policy.effective_score(o)
config.LEDGER_ENABLED = True
check("7. OH_LEDGER toggle works", on == 6 and off == 7, f"on={on} off={off}")

# 8 - a genuine 10 from a noisy source still reaches you (de-prioritised, not censored)
o2 = Opportunity("t", "u", "reddit", "d"); o2.ai_score = 10
check("8. a true 10 from a noisy source is not buried", policy.effective_score(o2) >= 9)

# 9 - score never leaves the 0-10 range
o3 = Opportunity("t", "u", "reddit", "d"); o3.ai_score = 0
check("9. never falls below 0", policy.effective_score(o3) == 0)

# 10 - explicit act/skip data outranks score-yield once there is enough of it
check("10. basis is reported honestly",
      "score yield" in ledger.build(hist({"a": [9] * 40}))["a"]["basis"])

ledger._CACHE = None
print("\n" + "=" * 60)
print("SOURCE SIGNAL LEDGER TESTS")
print("=" * 60)
p_ = 0
for n, ok, d in R:
    print(("  PASS  " if ok else "  FAIL  ") + n + (f"   [{d}]" if d and not ok else ""))
    p_ += ok
print("=" * 60)
print(f"{p_}/{len(R)} passed")
sys.exit(0 if p_ == len(R) else 1)
