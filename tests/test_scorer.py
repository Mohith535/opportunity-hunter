"""Tests for the rule scorer (filters/scorer.py) — specifically the domain-fit and
naming-asymmetry fixes.

Why these exist: Mohith reported "I used to get good hackathons, now I get internships."
Measured on live Unstop data the cause was structural, not random — the word "Internship" is
itself one of config.INTERESTS and appears in nearly every internship's title, so an internship
banked +5 before anything relevant was judged, while "NASA Space Apps Challenge" banked 0. A
Video Editor internship outranked it. These tests hold that fix in place.

Run:  python tests/test_scorer.py
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from filters.scorer import score_item
from models import Opportunity

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

SOON = date.today() + timedelta(days=12)

def opp(title, desc="", source="unstop", tags=None, deadline=SOON):
    return Opportunity(title=title, url="https://x/" + title[:8], source=source,
                       description=desc, deadline=deadline, tags=list(tags or []))

# The two real listings that exposed the bug, with their real Unstop descriptions.
NASA = opp("NASA Space Apps Challenge 2026",
           "hackathon | hybrid | Eligibility: students | Team size: 1-6 | By Chandigarh University",
           tags=["hackathon"])
VIDEO = opp("Video Editor Internship",
            "internship | online | Eligibility: students, fresher; courses: artsOthers, ba, bba, bcom "
            "| By Dezainahub | stipend",
            tags=["internship"])

# 1 - THE REGRESSION TEST. A famous hackathon must outrank a video-editing internship.
check("1. hackathon outranks an off-domain internship",
      score_item(NASA) > score_item(VIDEO),
      f"NASA={score_item(NASA)} video={score_item(VIDEO)}")

# 2 - a brand-named hackathon is not punished for omitting the word "hackathon"
anon = opp("YODHA 2.0", "hackathon | online | Team size: 1-4", tags=["hackathon"])
check("2. brand-named hackathon still scores", score_item(anon) >= 5, str(score_item(anon)))

# 3 - the technical internship he DOES want still scores high
tech = opp("Artificial Intelligence Internship",
           "internship | online | Eligibility: students | stipend", tags=["internship"])
check("3. AI internship scores high", score_item(tech) >= 9, str(score_item(tech)))

# 4 - ...and clearly outranks the non-technical one
check("4. technical internship beats non-technical",
      score_item(tech) > score_item(VIDEO), f"{score_item(tech)} vs {score_item(VIDEO)}")

# 5 - the off-domain penalty is judged on the TITLE, so a technical role at a
#     marketing company is not punished for its employer's description
at_agency = opp("Python Developer Internship",
                "internship | online | By a digital marketing agency | social media clients",
                tags=["internship"])
check("5. off-domain words in the body do not sink a technical title",
      score_item(at_agency) >= 9, str(score_item(at_agency)))

# 6 - conversely a marketing title is penalised even when the body sounds technical
mktg = opp("Digital Marketing Internship",
           "internship | online | Eligibility: btech, engineering students | analytics tools",
           tags=["internship"])
check("6. marketing title is penalised despite a technical-sounding body",
      score_item(mktg) <= 5, str(score_item(mktg)))

# 7 - "Video Editor" must actually match the off-domain pattern. The first version used the
#     bare prefix "video edit" inside a group closed by \b, which can never match "Editor";
#     that single bug let this listing score 10.
check("7. 'Video Editor' matches off-domain (the \\b prefix bug)",
      score_item(VIDEO) <= 5, str(score_item(VIDEO)))
for role in ("Content Writing Internship", "Graphic Designer Internship",
             "Telecaller Internship", "Social Media Internship"):
    r = opp(role, "internship | online | Eligibility: students", tags=["internship"])
    check(f"7.{role.split()[0].lower()} penalised", score_item(r) <= 5, f"{role}={score_item(r)}")

# 8 - a CTF is in-domain (security is his field) and outranks the video editor
ctf = opp("SecLeaf Q4 CTF 2026", "hackathon | online | 24-hour Capture The Flag", tags=["hackathon"])
check("8. CTF scores as technical", score_item(ctf) >= 8 and score_item(ctf) > score_item(VIDEO),
      str(score_item(ctf)))

# 9 - scores stay inside 0-10 even with the penalty applied
floor = opp("Insurance Sales Internship", "internship", tags=["internship"], deadline=None)
check("9. score never goes negative", 0 <= score_item(floor) <= 10, str(score_item(floor)))

# 10 - genuinely irrelevant content still scores 0
check("10. irrelevant content scores 0",
      score_item(Opportunity("Random local news", "u", "news", "nothing relevant here")) == 0)

# 11 - an urgent deadline still lifts an otherwise equal item (the original rule survives)
urgent = opp("Q Hackathon", "hackathon | online", tags=["hackathon"],
             deadline=date.today() + timedelta(days=3))
later = opp("Q Hackathon", "hackathon | online", tags=["hackathon"],
            deadline=date.today() + timedelta(days=200))
check("11. nearer deadline still ranks higher", score_item(urgent) > score_item(later),
      f"{score_item(urgent)} vs {score_item(later)}")

# 12 - three titles found at 10/10 in `resume.apply --list` on 2026-09-27, none of them a CSE role
for t in ("SEO Internship", "Caller Internship", "Public Relations Internship"):
    o = opp(t, "internship | online | Eligibility: students | stipend", tags=["internship"])
    check(f"12. '{t}' no longer reaches the top", score_item(o) <= 6, f"{t}={score_item(o)}")
check("12b. ...while a technical title is untouched",
      score_item(opp("Backend Developer Internship", "internship | online | Eligibility: students | stipend",
                     tags=["internship"])) >= 9)

print("=" * 70)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 70)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
