"""Tests for the big-company career radar (21 Oct 2026) — Workday, Amazon, Microsoft, Google, Avature.

Offline: every response below is the shape a live call returned on 20–21 Oct, trimmed. The parsers
are regexes over other people's HTML, so these are the checks that notice when one stops matching.

Run:  python tests/test_career_radar.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sources import ats
from resume.eligibility import Candidate, NO, title_rules
import resume.apply as A

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

calls = []
def fake(responses):
    def _get(url, budget=25, body=None, text=False):
        calls.append((url, body))
        return responses.pop(0)
    return _get

real_get = ats._get_json
try:
    # ── Workday: a POST search, 20 a page; senior roles dropped; the job URL built from externalPath
    ats._get_json = fake([{"total": 3, "jobPostings": [
        {"title": "2027 Intern - Software Engineer", "externalPath": "/job/Bangalore/X_R1", "locationsText": "Bangalore", "postedOn": "Posted Today"},
        {"title": "Senior Software Engineer", "externalPath": "/job/Bangalore/X_R2", "locationsText": "Bangalore"},
        {"title": "PhD Intern, AI ML", "externalPath": "/job/India-Bengaluru/X_R3", "locationsText": "India, Bengaluru"}]}])
    got = ats._workday("adobe.wd5/adobe/external_experienced", "Adobe", 25, {"query": "intern"})
    check("1a. Workday keeps student roles only", [o.title for o in got] == ["2027 Intern - Software Engineer — Adobe", "PhD Intern, AI ML — Adobe"], [o.title for o in got])
    check("1b. ...as a POST with the entry's query", calls[-1][1] and calls[-1][1]["searchText"] == "intern" and "/wday/cxs/adobe/external_experienced/jobs" in calls[-1][0])
    check("1c. the listing URL and the native id the pack uses",
          got[0].url == "https://adobe.wd5.myworkdayjobs.com/external_experienced/job/Bangalore/X_R1"
          and got[0].native_id == "workday:adobe.wd5/adobe/external_experienced:/job/Bangalore/X_R1")
    check("1d. a short page ends the paging (no wasted requests)", len(calls) == 1)

    # ── Amazon: loc_query is not a filter, so the country and a tech category are checked per job
    ats._get_json = fake([{"jobs": [
        {"title": "WHS Intern", "country_code": "ESP", "job_category": "Medical, Health, & Safety", "job_path": "/en/jobs/1/whs"},
        {"title": "Finance Intern", "country_code": "IND", "job_category": "Finance & Accounting", "job_path": "/en/jobs/2/f"},
        {"title": "SDE Intern", "country_code": "IND", "job_category": "Software Development", "job_path": "/en/jobs/3/sde",
         "normalized_location": "Bengaluru, KA, IND", "id_icims": "3"}]}])
    got = ats._amazon("IND", "Amazon", 25, {})
    check("2a. Amazon: only the Indian tech intern survives (Spain's WHS and a finance role do not)",
          [o.title for o in got] == ["SDE Intern — Amazon"] and got[0].url == "https://www.amazon.jobs/en/jobs/3/sde", [o.title for o in got])
    check("2b. ...and the country goes in the query, not loc_query", "normalized_country_code" in calls[-1][0] and "loc_query" not in calls[-1][0])

    # ── Microsoft (Eightfold pcsx)
    ats._get_json = fake([{"data": {"positions": [
        {"id": 1970393556978896, "name": "Research Sciences INTERN", "locations": ["India, Multiple Locations"]},
        {"id": 5, "name": "Principal Architect", "locations": ["India"]}]}}])
    got = ats._microsoft("India", "Microsoft", 25, {})
    check("3a. Microsoft: intern kept, principal dropped, URL from the id",
          len(got) == 1 and got[0].url == "https://apply.careers.microsoft.com/careers/job/1970393556978896"
          and got[0].raw["location"] == "India, Multiple Locations")

    # ── Google: page 1 HTML; the title lives in the link's aria-label
    page = ('<a class="WpHeLc" href="jobs/results/109976286780105414-software-engineering-phd-intern-summer-2027?q=intern&amp;location=India" '
            'aria-label="Learn more about Software Engineering PhD Intern, Summer 2027" jsname="hSRGPd"></a>'
            '<a href="jobs/results/1-staff-engineer" aria-label="Learn more about Staff Software Engineer"></a>')
    ats._get_json = fake([page])
    got = ats._google("India", "Google", 25, {})
    check("4a. Google: the title from aria-label, senior roles dropped",
          [o.title for o in got] == ["Software Engineering PhD Intern, Summer 2027 — Google"], [o.title for o in got])
    check("4b. ...first page only (robots.txt disallows ?page=)", len(calls) and "page=" not in calls[-1][0])

    # ── Avature (EA): a real result card, as served on 21 Oct
    card = ('<article class="article article--result article--non-toggle" id="article--1"> <div class="article__header"> '
            '<div class="article__header__text"> <h3 class="article__header__text__title title title--04 " data-au="ag-h3-6"> '
            '<a class="link link_result" href="https://jobs.ea.com/en_US/careers/JobDetail/Analytics-Intern/216252" data-au="ag-a-10"> '
            'Analytics Intern </a> </h3> <div class="article__header__text__subtitle"> <span class="list-item-location">Orlando, '
            'United States of America</span> </div> </div> </div> </article>')
    ats._get_json = fake([card * 1])
    got = ats._avature("jobs.ea.com/en_US/careers", "Electronic Arts", 25, {"query": "intern"})
    check("5a. Avature: title, link, location and role id from EA's card",
          len(got) == 1 and got[0].title == "Analytics Intern — Electronic Arts"
          and got[0].url.endswith("/JobDetail/Analytics-Intern/216252")
          and got[0].raw["location"] == "Orlando, United States of America"
          and got[0].native_id == "avature:jobs.ea.com/en_US/careers:216252", got and (got[0].title, got[0].raw))
    check("5b. ...a page with fewer than 20 cards is the last", len(calls) and calls[-1][0].endswith("jobOffset=0"))

    # ── one broken board never takes the others down
    def boom(*a, **k):
        raise ats.requests.HTTPError("429 Client Error: Too Many Requests")
    ats._get_json = boom
    check("6a. a 429 from one company (Salesforce, 21 Oct) returns [] instead of raising",
          ats._fetch_one({"platform": "workday", "slug": "salesforce.wd12/salesforce/External_Career_Site", "name": "Salesforce"}) == [])
finally:
    ats._get_json = real_get

# ── eligibility from the title, where these boards state the degree
C = Candidate()
check("7a. 'PhD Intern' is not for a bachelor's student", [l for l, _ in title_rules("Software Engineering PhD Intern, Summer 2027", C)] == [NO])
check("7b. '- Masters -' in EA's title is not either",
      [l for l, _ in title_rules("AI/ML Software Engineer Intern (Summer 2027 - 8-Months - Masters - QVS)", C)] == [NO])
check("7c. 'Master Data Management Intern' and 'PhD or Bachelor' are fine",
      title_rules("Master Data Management Intern", C) == [] and title_rules("PhD or Bachelor Research Intern", C) == [])
check("7d. a Workday item's pack reads the employer's own posting",
      A.ats_native({"native_id": "workday:adobe.wd5/adobe/external_experienced:/job/Bangalore/X_R1"}).startswith("workday:")
      and "workday" in A._ATS)

# ── the same role must not score 5 points lower because a board says "Intern" (21 Oct)
from filters import focus
from filters.scorer import score_item
from models import Opportunity
board = ats._opp("Software Engineer Intern", "https://x", "Adobe", "Workday", "Bangalore")
unstop = Opportunity("Software Engineer Internship", "https://y", "unstop",
                     "internship | Adobe | Bangalore", tags=["internship"])
check("8a. a board's 'Intern' title is an internship (it was tagged 'job')", focus.kind_of(board) == "internship")
check("8b. ...and scores within a point of the same role titled 'Internship' (it was 4 vs 9)",
      abs(score_item(board) - score_item(unstop)) <= 1, (score_item(board), score_item(unstop)))
check("8c. a board role without 'intern' stays a job", focus.kind_of(ats._opp("New Grad Engineer", "u", "S", "Lever")) == "job")

# ── EA's full posting: the job description, not the company blurb or the page footer (21 Oct)
from resume.eligibility import text_rules, CHECK
FIELD = '<div class="article__content__view__field__value">'
page = (f'<article>{FIELD}Electronic Arts creates next-level entertainment experiences.</div></article>'
        f'<article>{FIELD}<p>Project Management Intern – JD</p><p>Key Responsibilities</p><p>Support project tracking.</p>'
        f'<p>Skills &amp; Experience</p><p>Currently pursuing an MBA with a specialization in Operations, IT Project '
        f'Management, or a closely related field with undergrad degree in B. Tech/B.Sc</p></div></article>'
        f'<article>{FIELD}1449 - Back to Role List - Apply - Share this role - LinkedIn - X - WhatsApp - Email - '
        f'Facebook - Copy link - Privacy - Terms - Cookies - Accessibility - Careers home - Students - Teams</article>'
        + "<footer>" + "x " * 400 + "</footer>")
real_req = A.requests.get
class _P:
    def __init__(self, t): self.text = t
A.requests.get = lambda *a, **k: _P(page)
try:
    full = A._avature_detail("jobs.ea.com/en_US/careers", "216036")
finally:
    A.requests.get = real_req
check("9a. EA: the job description is taken, not the company blurb or the page footer",
      full["description"].startswith("Project Management Intern") and "MBA" in full["description"], full["description"][:60])
check("9b. 'currently pursuing an MBA' rules out a bachelor's student (the EA Hyderabad intern)",
      [l for l, _ in text_rules(full["description"], C)] == [NO])
check("9c. ...but 'a Master's or Bachelor's degree' does not",
      text_rules("Currently pursuing a Master's or Bachelor's degree in Computer Science.", C) == []
      and text_rules("Students pursuing B.Tech or M.Tech are welcome.", C) == [])
check("9d. EA packs read EA's own posting", "avature" in A._ATS
      and A.ats_native({"native_id": "avature:jobs.ea.com/en_US/careers:216036"}).startswith("avature:"))

# ── remote jobs open to India (Himalayas, 22 Oct) ──────────────────────────────────────────────
import sources.remote as RM
job = {"title": "Machine Learning (ML) Engineer Intern - (Paid - India/Remote)", "companyName": "Peakflo",
       "guid": "https://himalayas.app/companies/peakflo/jobs/ml-engineer-intern", "employmentType": "Intern",
       "applicationLink": "https://himalayas.app/companies/peakflo/jobs/ml-engineer-intern?utm_source=x",
       "locationRestrictions": ["India"], "excerpt": "Build ML models."}
o = RM.to_opportunity(job)
check("10a. Himalayas: an internship, its apply link UNCHANGED (their terms), credited as the source",
      o and o.tags == ["internship"] and o.url == job["applicationLink"] and "via Himalayas" in o.description)
check("10b. ...and a native id the pack can refetch the full posting with",
      o.native_id == "himalayas:peakflo:ml-engineer-intern" and "himalayas" in A._ATS)
check("10c. where a candidate may be: no restriction = worldwide; else the countries",
      RM.place({"locationRestrictions": []}) == "Remote (worldwide)"
      and RM.place({"locationRestrictions": ["Canada", "Germany"]}) == "Remote — Canada, Germany")
from resume.eligibility import location_rules, YES as _Y, CHECK as _C
check("10d. which the eligibility rules read: worldwide/India ✅, Canada+Germany only ⚠ for him",
      location_rules("Remote (worldwide)", None, C)[0][0] == _Y and location_rules("Remote — India", None, C)[0][0] == _Y
      and location_rules("Remote — Canada, Germany", None, Candidate(open_to_relocate=True))[0][0] == _C)
check("10e. only tech roles: a co-founder / CMO 'internship' and sales are left out",
      RM.to_opportunity({**job, "title": "AI Research Lab Co-Founder / CMO (100 % remote)"}) is None
      and RM.to_opportunity({**job, "title": "Inside Sales Intern"}) is None)

# ── HackerEarth challenges (22 Oct): hackathons, and hiring tests filed as jobs ───────────────
import sources.hackathons as HK
from datetime import date as _d, timedelta as _td
soon = (_d.today() + _td(days=20)).isoformat() + " 18:29:00+00:00"
past = (_d.today() - _td(days=2)).isoformat() + " 18:29:00+00:00"
feed = {"response": [
    {"title": "Agentic Banking Hackathon", "url": "https://www.hackerearth.com/challenges/hackathon/agentic-banking-hackathon-2/",
     "challenge_type": "Monthly Challenges", "end_utc_tz": soon, "status": "ONGOING", "college": "False", "description": "<p>Build agents</p>"},
    {"title": "Acme Backend Hiring Challenge", "url": "https://www.hackerearth.com/challenges/hiring/acme/",
     "challenge_type": "Hiring Challenges", "end_utc_tz": soon, "status": "UPCOMING", "college": "False", "description": ""},
    {"title": "Old one", "url": "u3", "challenge_type": "Hackathon", "end_utc_tz": past, "status": "ONGOING", "college": "False"},
    {"title": "One college only", "url": "u4", "challenge_type": "Hackathon", "end_utc_tz": soon, "status": "UPCOMING", "college": "True"},
    {"title": "Finished", "url": "u5", "challenge_type": "Hackathon", "end_utc_tz": soon, "status": "FINISHED", "college": "False"}]}
class _HR:
    def raise_for_status(self): pass
    def json(self): return feed
_g = HK.requests.get
HK.requests.get = lambda *a, **k: _HR()
try:
    he = HK.fetch_hackerearth()
finally:
    HK.requests.get = _g
check("11a. HackerEarth: live hackathons in, with the end date as the deadline",
      [o.title for o in he][:1] == ["Agentic Banking Hackathon"] and he[0].deadline and he[0].tags == ["hackathon"])
check("11b. a hiring challenge is a company recruiting by test — filed as a job",
      any(o.title == "Acme Backend Hiring Challenge" and o.tags == ["job"] for o in he))
check("11c. ended, finished, and one-college-only events are left out",
      not any(o.title in ("Old one", "One college only", "Finished") for o in he))

# ── Hack2Skill (22 Oct): open registrations only; a bootcamp is learning, a paid ticket is said ──
h2s = {"data": {
    "flagshipEvents": [
        {"title": "Build with AI: PromptWars", "eventUrl": "promptwars", "customEventUrl": "https://promptwars.in/promptwars.html?ref=x",
         "registrationEnd": soon, "tags": {"mode": {"value": "Online"}, "ticket": {"value": "FREE"}}},
        {"title": "Closed Challenge", "eventUrl": "closed", "registrationEnd": past, "tags": {}}],
    "communityEvents": [
        {"title": "Build with AI: Bootcamps", "eventUrl": "bootcamps", "registrationEnd": soon,
         "tags": {"mode": {"value": "Offline"}, "ticket": {"value": "PAID"}}}]}}
class _H2:
    def raise_for_status(self): pass
    def json(self): return h2s
HK.requests.get = lambda *a, **k: _H2()
try:
    hs = HK.fetch_hack2skill()
finally:
    HK.requests.get = _g
check("11d. Hack2Skill: an open build is a hackathon, online, linked without tracking params",
      [o.title for o in hs] == ["Build with AI: PromptWars", "Build with AI: Bootcamps"]
      and hs[0].tags == ["hackathon"] and hs[0].raw["remote"] and hs[0].url == "https://promptwars.in/promptwars.html", hs)
check("11e. a bootcamp is learning, a paid ticket is said, a closed registration is left out",
      hs[1].tags == ["learning"] and "paid ticket" in hs[1].description
      and hs[1].url == "https://hack2skill.com/event/bootcamps" and not hs[1].raw["remote"])

print("=" * 72)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 72)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
