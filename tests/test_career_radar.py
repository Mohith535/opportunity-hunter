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

print("=" * 72)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 72)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
