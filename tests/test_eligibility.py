"""Tests for Phase 3 — "can I even apply?", and the list he picks packs from.

Every case here is a real one: a sentence from a live posting, a shape of Unstop JSON measured live,
or a defect that shipped. The expensive failure is a WRONG ⛔ — `--list` hides those rows, so a false
"not eligible" is a real internship he never sees. Several tests exist only to stop that:
    - Unstop's stored course list was `sorted(courses)[:6]`, which cut `btech` from nearly every list,
      and 33 real internships and hackathons were hidden as "not open to B.Tech".
    - 65 of 76 live listings leave the engineering group EMPTY beside "others: all", which is not
      an exclusion.
    - the full-listing experience rule read a field that was empty on 88 of 88 listings.
    - `region: online` is how you register, not where you work; 33 of 60 "online" jobs were in an office.

Run:  python tests/test_eligibility.py
"""
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from resume.eligibility import (CHECK, NO, NOT_STATED, YES, Candidate, assess, from_description,
                                location_rules, text_rules, title_rules, unstop_rules, who_rules, _verdict)

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

C = Candidate(grad_year=2029, start_year=2025)
def levels(rules):
    return [lvl for lvl, _ in rules]

# ── 1. free-text rules, on sentences from live postings ────────────────────────────────────
check("1a. 'graduating in 2028' excludes a 2029 graduate",
      NO in levels(text_rules("Must be planning on graduating in 2028.", C)))
check("1b. a range ending before 2029 excludes",
      NO in levels(text_rules("Graduating between December 2027 and Summer 2028 (required)", C)))
check("1c. a range that includes 2029 is a YES",
      YES in levels(text_rules("Expected graduation 2028 or 2029.", C)))
check("1d. 'or later' is not an upper bound",
      NO not in levels(text_rules("Graduating in 2027 or later.", C)))
r = text_rules("Currently in your junior year of an undergraduate program (rising senior in summer 2027)", C)
check("1e. junior/rising senior excludes a year-2 student", NO in levels(r), str(r))
check("1f. 'undergraduate' is not read as a graduation-year rule",
      not any("graduation" in w for _, w in r), str(r))
check("1g. US work authorisation without sponsorship excludes",
      NO in levels(text_rules("You must be authorized to work in the United States; "
                              "visa sponsorship is not available.", C)))
check("1h. a university-in-another-country rule excludes",
      NO in levels(text_rules("Pursuing a degree in Computer Science from a university in Mexico (required)", C)))
check("1i. PhD-only excludes", NO in levels(text_rules("You are pursuing a PhD in machine learning.", C)))
check("1j. early-year programs are a YES",
      YES in levels(text_rules("Open to first-year or second-year students.", C)))
check("1k. CS degree is not flagged", CHECK not in levels(text_rules("a degree in Computer Science or related field", C)))

# ── 2. location ─────────────────────────────────────────────────────────────────────────────
check("2a. Mumbai works from India", levels(location_rules("Mumbai, Maharashtra", False, C)) == [YES])
check("2b. a US state excludes", levels(location_rules("San Francisco, CA", False, C)) == [NO])
check("2c. remote works", levels(location_rules("Anywhere", True, C)) == [YES])
check("2d. an unknown place is a CHECK", levels(location_rules("Atlantis", False, C)) == [CHECK])

# ── 3. titles ───────────────────────────────────────────────────────────────────────────────
check("3a. 'Senior .Net Developer' is not for a 2nd-year student",
      levels(title_rules("Senior .Net Developer", C)) == [NO])
check("3b. a senior-sounding intern title is left alone", title_rules("Senior Software Engineer Intern", C) == [])
check("3c. 'Lead' is not treated as senior (student leads exist)", title_rules("GDG Campus Lead", C) == [])

# ── 4. the stored Unstop line (what --list reads) ───────────────────────────────────────────
old6 = "Eligibility: students; courses: artsOthers, bSchoolOthers, ba, barch, bba, bca"
check("4a. the OLD six-course list cannot prove 'not B.Tech'",
      from_description(old6, C).level != NO, from_description(old6, C).line())
cut = "Eligibility: open to: students; courses: mba1, mba2, bba, bSchoolOthers, bcom, mcom (+27 more)"
check("4b. a list that says it was cut cannot prove 'not B.Tech'", from_description(cut, C).level != NO)
check("4c. btech in the list is a YES",
      from_description("Eligibility: courses: btech, mtech (+37 more)", C).level == YES)
check("4d. every engineering course is a YES",
      from_description("Eligibility: courses: allEngineering, mba1", C).level == YES)
short = "Eligibility: courses: mba1, mba2"
check("4e. a complete list without B.Tech is a CHECK, never a hide",
      from_description(short, C).level == CHECK, from_description(short, C).line())
check("4f. a short passout list without 2029 excludes",
      from_description("Eligibility: passout: 2025, 2026", C).level == NO)
check("4g. the OLD six-year cap (earliest six kept) cannot prove 2029 is missing",
      from_description("Eligibility: passout: 2023, 2024, 2025, 2026, 2027, 2028", C).level != NO)
check("4g2. ...but years that all come AFTER 2029 do exclude",
      from_description("Eligibility: passout: 2030, 2031, 2032, 2033, 2034, 2035", C).level == NO)
check("4h. 2029 listed is a YES", from_description("Eligibility: passout: 2028, 2029", C).level == YES)
check("4i. OLD unlabelled 'corporates; 1 year, 2 years' excludes",
      from_description("Eligibility: corporates; 1 year, 2 years, 3 years", C).level == NO)
check("4j. labelled 'open to: fresher' excludes a student",
      from_description("Eligibility: open to: fresher; experience: 1 year", C).level == NO)
r = from_description("Eligibility: open to: fresher, students; experience: 1 year", C)
check("4k. experience listed beside 'students' is a CHECK, not a hide", r.level == CHECK, r.line())
check("4l. no eligibility at all is NOT_STATED", from_description("A hackathon about AI", C).level == NOT_STATED)

# ── 5. the full Unstop listing (what job.md reads), in shapes measured live ─────────────────
def listing(**el):
    base = {"sector": ["students"], "engineering": [], "bSchools": [], "arts": [], "others": ["all"],
            "experience": ["all"]}
    base.update(el)
    return {"regnRequirements": {"eligibility": json.dumps(base), "gender": ["A"]}}

v = _verdict(unstop_rules(listing(bSchools=["allCourses", {"course": "mba1", "passoutYear": ["all"]}]), C))
check("5a. engineering EMPTY beside others:all is a CHECK, not a hide", v.level == CHECK, v.line())
v = _verdict(unstop_rules(listing(engineering=[{"course": "mtech", "passoutYear": ["all"]}]), C))
check("5b. engineering listed without btech excludes", v.level == NO, v.line())
v = _verdict(unstop_rules(listing(engineering=["allCourses"]), C))
check("5c. all engineering courses is a YES", v.level == YES, v.line())
v = _verdict(unstop_rules(listing(engineering=[{"course": "btech", "passoutYear": ["2026", "2027"]}]), C))
check("5d. btech with the wrong passout years excludes", v.level == NO and "2029" in v.line(), v.line())
v = _verdict(unstop_rules(listing(sector=["corporates"], engineering=["allCourses"]), C))
check("5e. 'corporates' only excludes a student", v.level == NO, v.line())
v = _verdict(unstop_rules(listing(sector=["fresher"], engineering=["allCourses"],
                                  experience=["1 year", "2 years"]), C))
check("5f. the REAL experience field (eligibility.experience) is read", "experience" in v.line(), v.line())
check("5g. gender ['A'] means all, not 'restricted to: a'",
      not any("restricted" in w for _, w in unstop_rules(listing(engineering=["allCourses"]), C)))
g = listing(engineering=["allCourses"]); g["regnRequirements"]["gender"] = ["F"]
check("5h. a real gender restriction is a CHECK for him to read",
      _verdict(unstop_rules(g, C)).level == CHECK)
check("5i. who_rules: nothing stated says nothing", who_rules([], []) == [])

# ── 6. the source writes that line — and must not lose btech again ─────────────────────────
from sources.hackathons import _elig_text, _unstop_pay_location
el = {"sector": ["fresher"], "experience": ["1 year", "2 years"],
      "engineering": [{"course": "btech", "passoutYear": ["2029"]}, {"course": "mtech", "passoutYear": ["all"]}],
      # The live shape: six courses that sort before "btech" — which is exactly how it got cut.
      "bSchools": [{"course": c, "passoutYear": ["all"]} for c in ("bSchoolOthers", "bba", "bca", "bcom", "mba1", "mba2")],
      "arts": [{"course": c, "passoutYear": ["all"]} for c in ("artsOthers", "ba", "barch", "bdes", "bsc", "msc")],
      "studentPassoutYearsSelected": [2028, 2030]}
t = _elig_text(el)
check("6a. btech survives (engineering first)", "btech" in t, t)
check("6b. a cut list says it was cut", "(+8 more)" in t, t)
check("6c. who and experience come first and are labelled",
      t.startswith("open to: fresher; experience: 1 year, 2 years"), t)
check("6d. top-level student passout years are kept", "2028" in t and "2030" in t and "2029" in t, t)
check("6e. every engineering course becomes allEngineering",
      "allEngineering" in _elig_text({"engineering": ["allCourses"], "others": ["all"]}))
check("6f. what the source writes, the reader understands",
      from_description("Eligibility: " + t, C).level == NO)   # fresher-only: not a student

check("6g. in_office + region online is NOT remote",
      _unstop_pay_location({"jobDetail": {"type": "in_office", "locations": ["Mumbai"]}, "region": "online"})["remote"] is False)
check("6h. wfh is remote",
      _unstop_pay_location({"jobDetail": {"type": "wfh"}, "region": "online"})["remote"] is True)
check("6i. an online hackathon (no job type) is remote",
      _unstop_pay_location({"region": "online"})["remote"] is True)
check("6j. hybrid is not remote",
      _unstop_pay_location({"jobDetail": {"type": "hybrid", "locations": ["Pune"]}, "region": "online"})["remote"] is False)

# ── 7. facts survive into history (models.to_dict) ──────────────────────────────────────────
from models import Opportunity
o = Opportunity("Backend Intern", "https://x/1", "unstop", "d",
                raw={"pay_max": 30000, "cities": ["Mumbai"], "remote": False, "secret_blob": {"x": 1}})
d = o.to_dict()
check("7a. pay and city are saved", d.get("facts", {}).get("pay_max") == 30000 and d["facts"].get("cities") == ["Mumbai"], d.get("facts"))
check("7b. raw itself is still not saved", "raw" not in d and "secret_blob" not in json.dumps(d))
check("7c. Nova's keys are untouched", all(k in d for k in ("title", "url", "source", "score", "key")))

# ── 8. the list: one ranking, stable numbers, nothing closed ────────────────────────────────
import resume.apply as A
from filters import target
from pathlib import Path
import tempfile
fd, tp = tempfile.mkstemp(suffix=".json"); os.close(fd)
Path(tp).write_text(json.dumps({"active": True, "focus": ["internship"], "locations": ["mumbai", "remote"],
                                "roles": {"tier1": ["backend"], "tier2": ["data analyst"]},
                                "avoid": ["seo", "sales"]}), encoding="utf-8")
_old_file = target.TARGET_FILE
target.TARGET_FILE = Path(tp); target.reset_cache()

soon = (date.today() + timedelta(days=10)).isoformat()
past = (date.today() - timedelta(days=2)).isoformat()
FAKE = [
    {"title": "Backend Developer Internship", "url": "u1", "source": "unstop", "tags": ["internship"],
     "deadline": soon, "description": "internship | Eligibility: courses: btech", "facts": {"cities": ["Mumbai"]}},
    {"title": "SEO Internship", "url": "u2", "source": "unstop", "tags": ["internship"], "deadline": soon,
     "description": "internship | Remote/WFH"},
    {"title": "Senior .Net Developer", "url": "u3", "source": "unstop", "tags": ["job"], "deadline": soon,
     "description": "job"},
    {"title": "Closed Internship", "url": "u4", "source": "unstop", "tags": ["internship"], "deadline": past,
     "description": "internship"},
    {"title": "AI Hackathon", "url": "u5", "source": "unstop", "tags": ["hackathon"], "deadline": soon,
     "description": "hackathon | online"},
    {"title": "Data Analyst Internship", "url": "u6", "source": "unstop", "tags": ["internship"],
     "deadline": soon, "description": "internship | Remote/WFH"},
]
_old_recent, _old_cand = A.recent_items, A._candidate
A.recent_items = lambda limit=40: [dict(x) for x in FAKE]
A._candidate = lambda profile=None: C
import config as _cfg
_old_focus = getattr(_cfg, "FOCUS", None); _cfg.FOCUS = None
try:
    rows = A.ranked_items()
    titles = [r[1]["title"] for r in rows]
    check("8a. a past deadline is dropped", "Closed Internship" not in titles, titles)
    check("8b. numbers are 1..N over the whole list, ineligible included",
          [r[0] for r in rows] == list(range(1, len(rows) + 1)) and "Senior .Net Developer" in titles, titles)
    check("8c. the tier-1 Mumbai internship ranks first", titles[0] == "Backend Developer Internship", titles)
    check("8d. tier-2 beats an avoid-list role", titles.index("Data Analyst Internship") < titles.index("SEO Internship"), titles)
    offs = [r[4] for r in rows]
    check("8e. the focus zone comes before other kinds",
          offs == sorted(offs) and rows[titles.index("AI Hackathon")][4] is True
          and rows[titles.index("SEO Internship")][4] is False, offs)
    senior = next(r for r in rows if r[1]["title"] == "Senior .Net Developer")
    check("8f. the senior job is ⛔ and keeps its number", senior[3].level == NO and senior[0] > 0)
    n = senior[0]
    check("8g. resolve(n) builds exactly the job printed as n",
          A.resolve(str(n))["title"] == "Senior .Net Developer")
    check("8h. resolve(1) is row 1", A.resolve("1")["title"] == titles[0])
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        A.show_list()
    out = buf.getvalue()
    check("8i. --list hides the ⛔ row but says so", "Senior .Net" not in out and "1 not-eligible" in out, out[-300:])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        A.show_list(show_all=True)
    out2 = buf.getvalue()
    check("8j. --all shows it under the SAME number", f"{n:>3}. " in out2 and "Senior .Net" in out2)
    check("8k. every row says why it ranks there", "tier-1 role" in out and "avoid list" in out, out)
finally:
    A.recent_items, A._candidate = _old_recent, _old_cand
    _cfg.FOCUS = _old_focus
    target.TARGET_FILE = _old_file; target.reset_cache()
    os.unlink(tp)

# ── 9. skill evidence: built vs studied vs gap ──────────────────────────────────────────────
from resume.fit import BUILT, GAP, LEARNED, skill_evidence
P = {"projects": [{"x_source": "resume-2026-09", "x_resume_name": "nova-cortex",
                   "x_techline": "Python, FastAPI, MCP", "highlights": ["Built an MCP server"]}],
     "skills": [{"name": "Docker", "evidence": ["cert:Docker Essentials"]}],
     "x_resume": {"skill_groups": {"Languages": ["Java"]}}}
ev = skill_evidence("We use Python, the Model Context Protocol (MCP), Docker, Java and Kubernetes.", P)
lvl = {t: l for t, l, _ in ev}
check("9a. a skill in a featured project is BUILT", lvl.get("python") == BUILT, ev)
check("9b. MCP and 'model context protocol' are ONE row",
      sum(1 for t in lvl if t in ("mcp", "model context protocol")) == 1, list(lvl))
check("9c. a certificate is LEARNED, not BUILT", lvl.get("docker") == LEARNED, ev)
check("9d. the skills section counts as LEARNED", lvl.get("java") == LEARNED, ev)
check("9e. nothing backing it is a GAP", lvl.get("kubernetes") == GAP, ev)
check("9f. rows are ordered built, learned, gap",
      [l for _, l, _ in ev] == sorted([l for _, l, _ in ev], key=[BUILT, LEARNED, GAP].index))

print("=" * 72)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 72)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
