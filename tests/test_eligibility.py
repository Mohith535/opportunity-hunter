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


# Never reach the live bot from a test: .env carries OH_WORKER_URL on his laptop.
from filters import outcomes as _outcomes
_outcomes.reset_cache({"likes": {}, "avoids": {}, "signals": 0})

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

# ── 10. the daily hunt's gate (main._drop_ineligible) ───────────────────────────────────────
from resume.eligibility import reason_bucket
check("10a. reasons become categories without his values",
      reason_bucket("passout years 2025, 2026; you graduate 2029") == "graduation year"
      and reason_bucket("open to corporates, not students") == "not for students"
      and reason_bucket("a senior role (Senior) — it expects years of experience") == "senior role"
      and reason_bucket("needs 2+ years of experience") == "experience")
import main as M
jobs = [Opportunity("Backend Developer Internship", "https://x/a", "unstop",
                    "internship | Eligibility: open to: students; courses: btech", tags=["internship"]),
        Opportunity("Commodity Advisor", "https://x/b", "unstop",
                    "job | Location: Mumbai | Eligibility: open to: fresher, corporates", tags=["job"]),
        Opportunity("Senior .Net Developer", "https://x/c", "unstop", "job", tags=["job"])]
_old_profile, _old_cand = A._profile, A._candidate
try:
    A._profile = lambda: {}
    kept, hid = M._drop_ineligible(list(jobs))
    check("10b. no career profile → nothing hidden (never judge by someone else's facts)",
          len(kept) == 3 and hid == {}, (len(kept), hid))
    A._profile = lambda: {"education": [{"institution": "X Institute of Technology",
                                          "startDate": "2025", "endDate": "2029"}]}
    kept, hid = M._drop_ineligible(list(jobs))
    check("10c. the graduates-only and senior jobs are dropped",
          [k.title for k in kept] == ["Backend Developer Internship"], [k.title for k in kept])
    check("10d. and counted by category", hid == {"not for students": 1, "senior role": 1}, hid)
    _cfg.HIDE_INELIGIBLE = False
    check("10e. OH_HIDE_INELIGIBLE=false turns it off", len(M._drop_ineligible(list(jobs))[0]) == 3)
    _cfg.HIDE_INELIGIBLE = True
    # 22 Oct: Microsoft's "Research Sciences INTERN" passed on its title and reached him at 9/10.
    big = [Opportunity("Research Sciences INTERN — Microsoft", "https://x/m", "ats", "Microsoft | India",
                       native_id="msft:1", tags=["internship"]),
           Opportunity("Software Engineering Intern — Google", "https://x/g", "ats", "Google | India",
                       native_id="google:2", tags=["internship"]),
           Opportunity("Backend Developer Internship", "https://x/a", "unstop", "internship", tags=["internship"])]
    asked, _fj = [], A.fetch_full_jd
    def _fake_full(d):
        asked.append(d["native_id"])
        return ({"description": "Currently pursuing a Master's or a Doctorate Degree in a relevant field"}
                if d["native_id"].startswith("msft:") else {})       # Google's fetch "fails"
    A.fetch_full_jd = _fake_full
    try:
        kept, deep = M._check_full_postings(list(big))
    finally:
        A.fetch_full_jd = _fj
    check("10f. a new big-company role is read in full: the Master's/PhD one goes, a failed fetch keeps its item, "
          "an Unstop item costs no call",
          [k.title for k in kept] == ["Software Engineering Intern — Google", "Backend Developer Internship"]
          and deep == 1 and asked == ["msft:1", "google:2"], ([k.title for k in kept], deep, asked))
finally:
    A._profile, A._candidate = _old_profile, _old_cand
    _cfg.HIDE_INELIGIBLE = True

# ── 11. 21 Oct — he will move abroad; only a STATED restriction hides a job ─────────────────
# StackAdapt (Canadian co-op, "Remote in Canada") reached him as a 10/10 with "RULES NOT STATED", and
# 182 of 433 jobs kept in two weeks were abroad, every one judged "not stated". Then he said: "I am
# really okay to work in other countries and states, if they accept — just filter real restrictions."
from resume.eligibility import VERIFY_CAP, capped, form_rules, remote_abroad
STAY, GO = Candidate(), Candidate(open_to_relocate=True)
check("11a. 'Remote in Canada' is not work-from-India (it was YES — '_HOME' held the word remote)",
      levels(location_rules("Remote in Canada", None, STAY)) == [NO], location_rules("Remote in Canada", None, STAY))
r = location_rules("Remote in Canada", None, GO)
check("11b. ...for someone open to moving it is a CHECK that names the catch",
      levels(r) == [CHECK] and "remote only from inside Canada" in r[0][1], r)
check("11c. abroad alone never hides a job from him (it was NO)",
      levels(location_rules("Mountain View, CA", None, GO)) == [CHECK])
check("11d. ...but still does for a candidate who will not move",
      levels(location_rules("Mountain View, CA", None, STAY)) == [NO])
check("11e. several places: the best one decides",
      levels(location_rules("Bengaluru, India; Remote in USA", None, STAY)) == [YES])
check("11f. Unstop's work-from-home flag still means India", levels(location_rules("Online", True, GO)) == [YES])
check("11g. citizenship / clearance is a stated restriction",
      NO in levels(text_rules("U.S. citizenship is required for this role due to ITAR.", GO)))
check("11h. a local co-op program is a stated restriction",
      NO in levels(text_rules("You must be currently enrolled in an accredited co-op program.", GO)))
check("11i. Canada work rights + no sponsorship (only the US was caught before)",
      NO in levels(text_rules("Must be legally authorized to work in Canada. We are unable to sponsor.", GO)))
check("11j. abroad + 'Does Not Offer Sponsorship' (SimplifyJobs) is a closed door",
      assess(GO, "internship | Foo | Austin, TX | Summer 2027 | Does Not Offer Sponsorship", "Austin, TX").level == NO)
check("11k. abroad + 'Offers Sponsorship' is an open one",
      assess(GO, "internship | Foo | Austin, TX | Summer 2027 | Offers Sponsorship", "Austin, TX").level == YES)
check("11l. the form's co-op question is a rule (StackAdapt's real rule lived only in its form)",
      levels(form_rules(["Are you currently enrolled in an accredited co-op program?"], GO)) == [NO])
check("11m. 'are you authorised / do you need sponsorship' is on every form — never a rule by itself",
      form_rules(["Are you legally authorized to work in the country where the job is located?",
                  "Will you now or in the future require sponsorship?"], GO) == [])
check("11n. remote tied to a foreign place is found; offices named elsewhere in prose are not",
      remote_abroad("internship | StackAdapt | Remote in Canada | Winter 2027") == "Canada"
      and remote_abroad("Offices in London and Bengaluru; remote OK") == "")
v_check = assess(GO, "", "Remote in Canada")
check("11o. a job he must verify is at most an 8; an eligible one keeps its 10; a hackathon is not capped",
      capped(10, v_check, True) == VERIFY_CAP == 8 and capped(10, assess(GO, "", "Mumbai"), True) == 10
      and capped(10, v_check, False) == 10)

# 11p. End to end, through the source as it really writes the item.
import sources.internships as SI
class _Resp:
    def raise_for_status(self): pass
    def json(self):
        return [{"active": True, "is_visible": True, "title": "Software Engineer Backend Intern",
                 "company_name": "StackAdapt", "locations": ["Remote in Canada"], "terms": ["Winter 2027"],
                 "sponsorship": "Other", "url": "https://job-boards.greenhouse.io/stackadapt-confidential/jobs/4386552009",
                 "id": "e8a1", "date_posted": 1}]
_get = SI.requests.get
SI.requests.get = lambda *a, **k: _Resp()
try:
    sa = SI.fetch()[0]
finally:
    SI.requests.get = _get
d = sa.to_dict()
check("11p. the SimplifyJobs place survives into history (it was dropped: raw 'locations' is not a fact key)",
      (d.get("facts") or {}).get("location") == "Remote in Canada", d.get("facts"))
check("11q. ...so StackAdapt is judged, not 'rules not stated'",
      A.eligibility_of(d, None, GO).level == CHECK and A.eligibility_of(d, None, STAY).level == NO)
from filters import target as T
check("11r. and it no longer earns 'remote, which you accept'", T.is_remote(sa) is False)
check("11s. the employer's own posting is found from an aggregator URL",
      A.ats_native(d) == "gh:stackadapt-confidential:4386552009")
_old_profile, _old_cand = A._profile, A._candidate
try:
    A._profile = lambda: {"education": [{"institution": "X Institute of Technology",
                                          "startDate": "2025", "endDate": "2029"}]}
    A._candidate = lambda prof=None: Candidate(grad_year=2029, start_year=2025, open_to_relocate=True)
    sa.score = 10
    kept, hid = M._drop_ineligible([sa])
    check("11t. the daily gate keeps it, capped at 8 and tagged — visible, never a 10/10 'go'",
          kept and kept[0].score == 8 and "eligibility:verify" in kept[0].tags, (kept and kept[0].score, hid))
finally:
    A._profile, A._candidate = _old_profile, _old_cand

# ── 11u. one posting, one entry (21 Oct: 20 of 481 job items in 14 runs were copies) ──────────
def _o(t, src, co, loc, s=7):
    x = Opportunity(t, f"https://x/{src}/{t}/{loc}", src, "", tags=["internship"], raw={"company": co, "location": loc})
    x.score = s
    return x
folded, n = M._fold_copies([_o("Cloudflare — Software Engineer Intern", "internships", "Cloudflare", "Austin, TX", 9),
                            _o("Software Engineer Intern — Cloudflare", "ats", "Cloudflare", "Austin, TX", 8),
                            _o("TikTok — ML Engineer Intern (Ads)", "internships", "TikTok", "San Jose, CA"),
                            _o("TikTok — ML Engineer Intern (Search)", "internships", "TikTok", "San Jose, CA"),
                            _o("West Monroe — SWE Intern", "internships", "West Monroe", "Seattle, WA")])
check("11u. the same posting from two sources folds to one, keeping the company's own board",
      n == 1 and [x.source for x in folded if "Cloudflare" in x.title] == ["ats"], [(x.title, x.source) for x in folded])
check("11v. different teams (TikTok Ads vs Search) and different places stay apart", len(folded) == 4)

# ── 12. listed as remote, posted as office (career-ops' geo-mismatch, 21 Oct) ──────────────────
from resume.eligibility import attendance_rule
check("12a. a remote listing whose posting says 'hybrid role' / 'work onsite' / 'must relocate' is a CHECK",
      all(attendance_rule(t, "Remote", None) and attendance_rule(t, "Remote", None)[0][0] == CHECK
          for t in ("This is a hybrid role: 3 days a week in the office.", "You will work onsite in Pune.",
                    "Candidates must be willing to relocate to Hyderabad.")))
check("12b. ...quoting the posting's own words", "hybrid role" in attendance_rule("A hybrid role.", "Remote", None)[0][1])
check("12c. 'onsite interviews' and 'our office is in Mumbai' are not attendance rules",
      not attendance_rule("Onsite interviews happen in our Pune office.", "Remote", None)
      and not attendance_rule("Fully remote. Our office is in Mumbai.", "Remote", None))
check("12d. an office job saying 'hybrid' is not a mismatch", not attendance_rule("A hybrid role.", "Mumbai", None))

print("=" * 72)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 72)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
