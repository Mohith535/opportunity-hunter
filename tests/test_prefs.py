"""Tests for TaskFlow-driven down-weighting (taskflow/prefs.py), 4 Nov 2026.

Run:  python tests/test_prefs.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
from models import Opportunity
from taskflow import prefs

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

d = Path(tempfile.mkdtemp())
config.TASKFLOW_DATA_DIR = d          # never his real ~/.taskflow
(d / "config.json").write_text("{}", encoding="utf-8")
tasks = [
    # His board on 4 Nov: 42 of 59 "set down" tasks were OFFLOADS ("not now"), many back in todo since.
    *[{"title": f"Apply: AI internship {i}", "tags": ["internship", "ophunter"], "status": "offloaded"} for i in range(3)],
    {"title": "study egd", "tags": ["study"], "status": "todo",
     "edit_history": [{"field": "status", "new_value": "offloaded"}, {"field": "status", "new_value": "todo"}]},
    {"title": "study eee", "tags": ["study"], "status": "todo", "offloaded_at": "2026-10-01"},
    # Dropped, and still dropped: "I will not do this" — the one real taste signal.
    *[{"title": f"Apply: Video Editing gig {i}", "tags": ["design", "internship"], "status": "dropped"} for i in range(2)],
]
(d / "tasks.json").write_text(json.dumps({"tasks": tasks}), encoding="utf-8")

sig = prefs.offload_signals()
check("1. an offload is 'not now', not 'stop finding me this' — offloaded internships teach nothing",
      "internship" not in sig["tags"], sig)
check("2. a task he offloaded and brought back (study egd) is not a signal", "study" not in sig["tags"], sig)
check("3. the kind he hunts is never a dislike, even on dropped tasks (#internship ×2 dropped)",
      not set(sig["tags"]) & set(__import__("filters.focus", fromlist=["KINDS"]).KINDS), sig)
check("4. what he keeps dropping still counts (#design, 'video', 'editing')",
      "design" in sig["tags"] and "video" in sig["keywords"], sig)

intern = Opportunity("ML Engineer Internship", "https://a", "unstop", "internship | online", tags=["internship"])
video = Opportunity("Video Editing Internship", "https://b", "unstop", "internship | online", tags=["internship"])
intern.score = video.score = 9
n = prefs.apply_downweight([intern, video])
check("5. the ML internship keeps its 9; the video-editing one is pushed down",
      intern.score == 9 and video.score < 9 and n == 1, (intern.score, video.score, n))

print("=" * 72)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 72)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
