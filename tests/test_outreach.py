"""Tests for referral outreach (resume/outreach.py), 4 Nov 2026.

Run:  python tests/test_outreach.py
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from resume import outreach as O

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

profile = {"basics": {"name": "K MOHITH KANNAN", "email": "him@example.com", "phone": "+91 90000 00000"},
           "education": [{"institution": "SRM Institute of Science and Technology", "endDate": "2029"}],
           "projects": [{"name": "nova-cortex", "description": "An agent memory that is allowed to say “no”."},
                        {"name": "TaskFlow", "description": ""}]}
rows = [(0, "Understanding of machine learning concepts and algorithms.",
         "I benchmarked my own thesis on a frozen, hash-locked corpus and it was refuted.", "nova-cortex"),
        (0, "Build REST APIs", "Its web dashboard runs on a JSON REST API.", "TaskFlow"),
        (0, "Kafka", "", "")]
title = "Machine Learning Engineer Internship — Vortizo AI"

n = O.note(profile, rows, "Vortizo AI", title)
check("1. the note fits a free account's 200 characters and names the role, the project and what it is",
      len(n) <= 200 and "Vortizo AI" in n and "nova-cortex" in n and "allowed to say" in n, (len(n), n))
long_co = "Very Long Consulting And Technology Solutions Private Limited"
n2 = O.note(profile, rows, long_co, "Senior Associate Machine Learning Engineering Internship Programme 2027")
check("2. a long company and title still fit: the description goes first, never the project", len(n2) <= 200
      and "nova-cortex" in n2, (len(n2), n2))
msgs = [n, O.referral_ask(rows, "Vortizo AI", title, "https://x/apply"), O.follow_up("Vortizo AI", title),
        O.blurb(profile, rows, title)]
tp = {"projects": [{"name": "TaskFlow", "description": "A behavioral-psychology CLI task engine."},
                   {"name": "NitroWatch", "description": "MCP permission layer for AI agents."}]}
fs = O.note(tp, [(0, "x", "y", "TaskFlow")], "Kagnus", "Full Stack Developer Internship")
mc = O.note(tp, [(0, "x", "y", "NitroWatch")], "Zeta", "Backend Engineer Intern")
check("2b. the description reads mid-sentence ('TaskFlow, a behavioral…'), an acronym keeps its case, and a "
      "full-stack job stays full-stack when shortened",
      "TaskFlow, a behavioral" in fs and "full-stack internship" in fs and "NitroWatch, MCP permission" in mc,
      (fs, mc))
check("3. no message reads as a template (no filler, no AI tells, no exclamation marks)",
      all(not O.problems(m) for m in msgs), [O.problems(m) for m in msgs])
ask = msgs[1]
check("4. the ask names the role and link, quotes two answered asks with their projects, and gives an easy out",
      "https://x/apply" in ask and "nova-cortex" in ask and "TaskFlow" in ask and "Kafka" not in ask
      and "no problem" in ask, ask)

posting = ("Send your CV to Careers@Acme.in. Do not write to noreply@acme.in. "
           "Logo: banner@2x.png. Questions: hr.team@acme.co.in.")
check("5. only addresses the employer published, no no-reply ones, no image names",
      O.published_emails(posting) == ["careers@acme.in", "hr.team@acme.co.in"], O.published_emails(posting))

lk = O.links("Vortizo AI SRM Institute of Science and Technology", '"Vortizo AI" "SRM Institute"')
check("6. links are search pages he opens, the company encoded", all(v.startswith(("https://www.linkedin.com/",
      "https://www.google.com/search")) for v in lk.values()) and "Vortizo+AI" in lk["LinkedIn"], lk)
src = Path(O.__file__).read_text(encoding="utf-8")
check("7. the module can't contact anyone: it imports no HTTP client",
      not re.search(r"^\s*(import|from)\s+(requests|urllib\.request|http\.client|httpx)", src, re.M))
check("8. ML job → look for ML engineers; the board's ' — Company' is dropped from the role",
      O.role_title(title) == "Machine Learning Engineer" and O.plain_title(title) == "Machine Learning Engineer Internship")

md = O.outreach_md({"title": title, "url": "https://x/job", "description": ""},
                   {"description": posting, "apply_url": "https://x/apply"}, profile, rows, "Vortizo AI")
check("9. outreach.md: alumni first, the 3-a-month budget, the email only to the published address, "
      "the connect.py line, the never list",
      md.index("SRM alumni") < md.index("engineering manager") and "3 a month" in md
      and "To: careers@acme.in" in md and "python connect.py add" in md and "Never pay anyone" in md, md[:300])
check("10. his phone number is not handed to strangers", "+91 90000 00000" not in md)
# 4 Nov, read as he would on the real Vortizo AI pack: the same Jobs link under all four people, "applying
# for Machine Learning…", a sentence cut at "Merge k…", and "LeetCode solutions" in the blurb as a project.
lc_rows = rows[:1] + [(0, "Strong problem-solving skills", "34 LeetCode problems solved in C, #1 to #35, including "
                       "Median of Two Sorted Arrays, Regular Expression Matching and Merge k Sorted Lists.",
                       "LeetCode solutions")]
lc_profile = dict(profile, projects=profile["projects"] + [{"name": "LeetCode solutions",
                                                             "description": "34 LeetCode problems solved in C."}])
md2 = O.outreach_md({"title": title, "url": "https://x/job"}, {}, lc_profile, lc_rows, "Vortizo AI")
b2 = O.blurb(lc_profile, lc_rows, title)
check("13b. a long list is cut at a comma, and a sentence that names its project is not prefixed with it",
      "- “Strong problem-solving skills”: 34 LeetCode problems solved in C, #1 to #35, including Median of Two "
      "Sorted Arrays.\n" in md2 and "Merge k…" not in md2
      and "LeetCode solutions:" not in md2, md2[md2.find("Two things"):md2.find("Two things") + 400])
check("12. the LinkedIn Jobs link appears once, not under every person", md2.count("linkedin.com/jobs/search") == 1)
check("13. the ask reads as English and cuts his sentence at its clause, not mid-word",
      "applying for the Machine Learning Engineer Internship" in md2
      and "in nova-cortex, I benchmarked my own thesis on a frozen, hash-locked corpus and it was refuted." in md2,
      md2[md2.find("Two things"):md2.find("Two things") + 400])
check("14. the referral blurb names only things he built", "LeetCode" not in b2 and "nova-cortex" in b2, b2)
op = dict(profile, projects=profile["projects"] + [{"name": "OPHunter",
          "description": "A daily agent that finds internships for me and prepares my applications."}])
b3 = O.blurb(op, rows[:1] + [(0, "Agents", "Runs every morning.", "OPHunter")], title)
check("15. the blurb is about him throughout: his descriptions turn third-person",
      "finds internships for him and prepares his applications" in b3 and " me " not in b3, b3)
md0 = O.outreach_md({"title": title, "url": "https://x/job"}, {}, profile, rows, "Vortizo AI")
check("11. no published address → no email section", "To:" not in md0 and "Contacts the employer" not in md0)

# The linkedin-agent's handoff (4 Nov): connect.py's file has "## Who", "## Why reach out" and "## The note (send
# this by hand)" with the note in a code block, read by its NOTE_RE. Same headings here = a straight copy.
blk = md0[md0.index("~~~markdown"):md0.index("~~~", md0.index("~~~markdown") + 3)]
NOTE_RE = re.compile(r"## The note.*?```(.*?)```", re.S)       # connect.py, line 31
check("18. the three blocks copy straight into connect.py's file: its headings, its note block, none of its "
      "template text", all(f"\n{h}\n" in blk for h in ("## Who", "## Why reach out", "## The note (send this by hand)"))
      and NOTE_RE.search(blk).group(1).strip() == O.note(profile, rows, "Vortizo AI", title)
      and "No guesses" not in blk and "is not a reason" not in blk, blk)
pub = dict(profile, projects=[dict(profile["projects"][0], url="https://github.com/x/nova-cortex", private=False)])
priv = dict(profile, projects=[dict(profile["projects"][0], url="https://github.com/x/nova-cortex", private=True)])
check("19. 'the code is on his GitHub' only when a stranger can open it: nova-cortex is private (5 Nov)",
      "on his GitHub" in O.blurb(pub, rows[:1], title) and "on his GitHub" not in O.blurb(priv, rows[:1], title)
      and "on his GitHub" not in O.blurb(profile, rows[:1], title) and "nova-cortex" in O.blurb(priv, rows[:1], title)
      and "on his GitHub" not in O.blurb(dict(profile, projects=[dict(pub["projects"][0], private=None)]), rows[:1], title))

hp = dict(O.hiring_posts("Mumbai"))
check("16. hiring posts: LinkedIn POST search (not Jobs), last 24 h, newest first; his city added; X live",
      all("/search/results/content/" in hp[k] and "past-24h" in hp[k] and "date_posted" in hp[k]
          for k in ("AI/ML", "software", "remote", "Mumbai"))
      and "Mumbai" in hp["Mumbai"] and hp["on X"].startswith("https://x.com/search?f=live") and "Mumbai" not in dict(O.hiring_posts()))
import main as M  # noqa: E402
from filters import target as T  # noqa: E402
_load = T.load
T.load = lambda path=None: {"locations": ["remote", "mumbai"]}
try:
    pl = M._posts_line()
finally:
    T.load = _load
check("17. the digest line: Telegram-safe links (& escaped), remote skipped, the city named",
      pl.startswith("🔎 Hiring posts") and "&amp;datePosted" in pl and ">Mumbai</a>" in pl and "&datePosted" not in pl, pl)

print("=" * 72)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 72)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
