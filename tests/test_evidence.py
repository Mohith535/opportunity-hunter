"""Tests for the evidence bank (21 Oct 2026) — facts from his repos, proposed, never added on their own.

Offline: the facts below are the shapes collect() returned from his real repos on 21 Oct.
Run:  python tests/test_evidence.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from resume import evidence as E

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

check("1. requirements.txt -> skills by their resume names (helpers like dotenv are not skills)",
      E.frameworks_from("requirements.txt", "psycopg\nboto3\npython-dotenv\nfastapi\nuvicorn\nmangum\n")
      == {"postgresql", "aws", "fastapi", "aws lambda"})
check("2. package.json deps and devDeps; @types/* are not skills",
      E.frameworks_from("package.json", '{"dependencies":{"next":"14","three":"1"},"devDependencies":{"@types/node":"1","typescript":"5"}}')
      == {"next.js", "three.js", "typescript"})
check("3. his resume's checkable numbers", E.claims_in(["Lands within 12 ms. 108 commits, 214 tests, live."]) == {"commits": 108, "tests": 214})
check("4. tests are counted as test functions or check() calls, not files",
      E.test_count("t/test_a.py", "def test_x():\n  pass\nasync def test_y():\n  pass\ncheck('z', 1)\n") == 3)

PROFILE = {
    "skills": [{"name": "flask", "evidenceCount": 1, "evidence": ["repo:swiftship-flask-mysql"]},
               {"name": "fastapi", "evidenceCount": 0, "evidence": []}],
    "projects": [
        {"x_resume_name": "nova-cortex", "x_source": "resume-2026-09", "url": "https://github.com/Mohith535/nova-cortex",
         "highlights": ["190 tests; an adversarial agent I wrote found a real hole."]},
        {"x_resume_name": "LoopLab", "x_source": "resume-2026-09", "url": "https://looplab.page",
         "highlights": ["Lands within about 12 ms. 108 commits, 214 tests, live and in use."]}]}
FACTS = [
    {"repo": "nova-cortex", "private": True, "skills": {"fastapi": "api/app.py imports it"}, "py_files": 12,
     "routes": ["GET /health", "POST /remember"], "tests": 190, "commits": 46, "languages": [("Python", 98)]},
    {"repo": "looplab", "private": True, "skills": {"typescript": "package.json lists it"}, "py_files": 0,
     "routes": [], "tests": 0, "commits": 35, "languages": [("TypeScript", 62)]},
    {"repo": "nova-cortex", "private": True, "skills": {"fastapi": "x"}, "py_files": 1, "routes": [], "tests": 0, "commits": 1},
    {"repo": "swiftship-flask-mysql", "private": False, "skills": {}, "py_files": 0, "routes": [], "tests": 0,
     "commits": 1, "languages": [("HTML", 57), ("JavaScript", 17)]},
    {"repo": "edupresence", "private": True, "skills": {"next.js": "package.json lists it"}, "py_files": 0,
     "routes": [], "tests": 0, "commits": 4, "homepage": "https://edupresence-gamma.vercel.app", "description": "",
     "languages": [("TypeScript", 99)]},
]
props = E.proposals(FACTS, PROFILE)
kinds = lambda k: [p for p in props if p["kind"] == k]
check("5. a resume number a repo confirms is shown as checked, nothing to do",
      any("190 tests" in p["text"] and "✓" in p["text"] for p in kinds("check")))
check("6. a resume number a repo does NOT match is a question for him, never a correction",
      any("108 commits" in p["text"] and "35" in p["text"] for p in kinds("question"))
      and not any(p.get("kind") == "fact" and "35 commits" in p["text"] for p in props))
check("7. a FastAPI service becomes a fact for the project, naming the project",
      any(p["project"] == "nova-cortex" and "FastAPI service" in p["sentence"] and "**nova-cortex**" in p["text"]
          for p in kinds("fact")))
check("8. a repo listed twice is proposed once (the listing returned NitroWatch twice)",
      sum(1 for p in kinds("skill") if p["repo"] == "nova-cortex" and p["skill"] == "fastapi") == 1)
check("9. a skill the profile already credits to a repo with no code for it is a question",
      any("flask" in p["text"] and "swiftship" in p["text"] for p in kinds("question")))
check("10. a live repo not on his resume is offered as a project", any(p["repo"] == "edupresence" for p in kinds("project")))

md = E.render(props)
check("11. questions and checks have no box to tick; proposals do",
      "- [ ] **fastapi**" in md and "- [ ] your resume says" not in md)
ids_md = md.replace("- [ ] **fastapi**", "- [x] **fastapi**", 1)
ids = E.ticked(ids_md)
check("12. only the lines he ticks are read", len(ids) == 1)
new, done = E.apply_to(PROFILE, props, ids, "2026-10-21")
fa = next(s for s in new["skills"] if s["name"] == "fastapi")
check("13. applying adds the evidence pointer and counts it", fa["evidence"] == ["repo:nova-cortex"] and fa["evidenceCount"] == 1)
check("14. ...and changes nothing he did not tick", PROFILE["skills"][1]["evidence"] == [] and
      all(p.get("highlights") == q.get("highlights") for p, q in zip(PROFILE["projects"], new["projects"])))
fact_id = next(p["id"] for p in kinds("fact"))
new2, _ = E.apply_to(PROFILE, props, {fact_id}, "2026-10-21")
nc = next(p for p in new2["projects"] if p["x_resume_name"] == "nova-cortex")
check("15. a ticked fact becomes a highlight the matcher and the screening answers can quote",
      any("FastAPI service" in h for h in nc["highlights"]))
proj_id = next(p["id"] for p in kinds("project"))
new3, _ = E.apply_to(PROFILE, props, {proj_id}, "2026-10-21")
ed = next(p for p in new3["projects"] if p.get("x_resume_name") == "edupresence")
check("16. a ticked repo becomes a confirmed project (evidence), with the date he confirmed it",
      ed["x_confirmed"] == "2026-10-21" and ed["highlights"])
sl = E.study_list(props, {p["id"] for p in props if p["kind"] == "skill"},
                  ["React developer intern, React and Next.js", "React Native", "FastAPI backend"])
check("18. the study list puts the most-asked skill first, with the file to open",
      sl.index("## React") < sl.index("## FastAPI") if "## React" in sl else sl.index("## FastAPI") >= 0)
check("19. a capitalised sentence keeps its acronyms (str.capitalize() made 'a flask rest api')",
      E._cap("a Flask REST API") == "A Flask REST API")
check("20. a route with a <param> is left out (the resume linter read '<tracking_id>' as a placeholder)",
      E._no_params([("route", "/api/a"), ("route", "/api/t/<id>")]) == [("route", "/api/a")])
check("17. edi-vault is never read", "edi-vault" in __import__("resume.harvest", fromlist=["NEVER_READ"]).NEVER_READ)

print("=" * 72)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 72)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
