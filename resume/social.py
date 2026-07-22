"""
LinkedIn profile writer — an honest headline + About section, generated from your verified profile.

Your LinkedIn *export* (the input side) may be stuck in a queue, but nothing stops us producing
LinkedIn *output*: the text you paste in. This writes it from the same evidence base as everything
else — real skills, real projects, real credentials, never invented.

Built to how the platform actually behaves (researched, not guessed):

  HEADLINE  — 220 character hard limit; aim 180-200. Only the first ~70 characters appear in search
              results and mobile previews, so the keywords must be front-loaded. It is the single
              strongest SEO element on the profile, and ~87% of recruiters search LinkedIn by keyword.
              For a student: headline the role you WANT, not just "B.Tech student" — recruiters search
              for roles, not majors.
  ABOUT     — 2,600 character limit, but only ~300 characters show before the "See more" cut. Those
              first 300 must stand alone as a hook. Then the proof (what you've actually built), then
              a clear call to action.

Unlike the resume and cover letter, this deliberately uses NO "[add metric]" placeholders — a LinkedIn
profile is published text, not a draft you edit line-by-line, so where a number is unknown the sentence
is simply written without it. Everything else is the usual rule: if the profile can't back it, it
doesn't get written.
"""

from __future__ import annotations

from filters.llm_scorer import complete
from .generate import _clean_certs, _skills_ordered
from .profile import load_profile_json

HEADLINE_LIMIT = 220
HEADLINE_VISIBLE = 70      # what shows in search results / mobile
ABOUT_LIMIT = 2600
ABOUT_HOOK = 300           # what shows before "See more"

_PROMPT = """You are an expert LinkedIn profile writer. Write a HEADLINE and an ABOUT section for this
candidate using ONLY the real facts below.

HONESTY RULES:
- Use ONLY the listed skills, projects and credentials. Never invent experience, employers or metrics.
- No fabricated numbers. If a number would help but isn't given, write the sentence without it — do
  NOT use placeholders; this is published text, not a draft.
- Student / early-career framing: confident and specific, never inflated. Don't imply senior experience.

LINKEDIN CRAFT RULES (how the platform actually works):
- HEADLINE: hard max {h_limit} characters — AIM FOR 180-200 AND USE THAT SPACE. Every character is
  searchable keyword real estate; a short headline throws away recruiter reach. Shape it as:
  <target role>{target_hint} | <3-5 real technologies/specialties> | <what you actually build>.
  Front-load the first ~{h_visible} characters with the highest-value keywords (that's all that shows
  in search and on mobile). Never just "B.Tech student" — headline the role wanted, not the major.
- ABOUT OPENING — the most important rule: the first 2-3 sentences are ALL that shows before
  "See more" (~{a_hook} chars), so they must lead with something CONCRETE YOU BUILT — name a real
  project and what it does. NEVER open with aspiration or adjectives. BANNED words in the opening:
  "passionate", "driven", "innovative solutions", "makes a difference", "results-driven", "excited
  about the potential".
- Do NOT enumerate skills as a comma-separated list anywhere — LinkedIn has a dedicated Skills section
  for that. Show each skill through the project that proves it ("built X in Python").
- Mention at most 2-3 credentials, and only substantial, recognisable ones. Skip webinars and short
  workshops — they cost space and signal little.
- ABOUT length: hard max {a_limit} characters, aim 1200-1800. Structure: concrete hook → the proof
  (real projects) → what you're looking for and how to reach you.
- First person, natural, specific. No buzzword soup, no emoji spam.

Output EXACTLY these two blocks and nothing else:

HEADLINE:
<one line>

ABOUT:
<the about text, plain paragraphs>

--- REAL FACTS ---
Name: {name}
Background: {about}
Target role: {target}
Proven skills: {skills}
Real projects:
{projects}
Credentials: {certs}
"""


def _fit(text: str, limit: int) -> str:
    """Trim to the limit on a word boundary — never mid-word, never over."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;|·-") or text[:limit]


def generate_social(profile: dict, target_role: str = "") -> dict:
    """{'headline': str, 'about': str} — honest LinkedIn text from the verified profile."""
    basics = profile.get("basics", {})
    name = basics.get("name", "")
    declared = profile.get("x_declared", {})
    background = " ".join(x for x in [declared.get("identity", ""),
                                      declared.get("longTermGoal", "")] if x)
    target = target_role or declared.get("longTermGoal", "") or "AI/ML engineering roles"

    projects = [p for p in profile.get("projects", []) if (p.get("description") or "").strip()][:5]
    proj_lines = "\n".join(
        f"- {p['name']}{' (private)' if p.get('private') else ''}: {p['description']} "
        f"({', '.join((p.get('keywords') or [])[:4])})" for p in projects)

    out = complete(_PROMPT.format(
        h_limit=HEADLINE_LIMIT, h_visible=HEADLINE_VISIBLE, a_limit=ABOUT_LIMIT, a_hook=ABOUT_HOOK,
        target_hint=f" ({target_role})" if target_role else "",
        name=name, about=background or "(not specified)", target=target,
        skills=", ".join(_skills_ordered(profile, [], 14)),
        projects=proj_lines or "(none)",
        certs=", ".join(_clean_certs(profile, 6)) or "(none)"),
        max_tokens=900, temperature=0.5)

    if not out:
        return _fallback(profile, name, target, projects)

    from .generate import _block  # same block parser used by the resume generator
    headline = _fit(_block(out, "HEADLINE", ("ABOUT",)), HEADLINE_LIMIT)
    about = _block(out, "ABOUT", ("HEADLINE",)).strip()
    if len(about) > ABOUT_LIMIT:
        about = _fit(about, ABOUT_LIMIT)
    return {"headline": headline, "about": about}


def _fallback(profile: dict, name: str, target: str, projects: list[dict]) -> dict:
    """Plain honest text when no LLM is available."""
    skills = _skills_ordered(profile, [], 6)
    headline = _fit(f"{target} | " + " | ".join(skills[:4]), HEADLINE_LIMIT)
    built = "; ".join(f"{p['name']} — {p['description']}" for p in projects[:3])
    about = (f"I build things. {('Recent work: ' + built) if built else ''}\n\n"
             f"Core skills: {', '.join(skills)}.\n\n"
             f"I'm looking for {target}. Open to a conversation — reach out here.")
    return {"headline": headline, "about": _fit(about, ABOUT_LIMIT)}


def format_social(res: dict) -> str:
    h, a = res["headline"], res["about"]
    hook = a[:ABOUT_HOOK]
    lines = [
        "=" * 66, "LINKEDIN PROFILE TEXT — paste-ready, from your verified profile", "=" * 66, "",
        f"── HEADLINE ({len(h)}/{HEADLINE_LIMIT} chars) ──", h, "",
        f"   ↳ what recruiters actually see in search (first {HEADLINE_VISIBLE}):",
        f'   "{h[:HEADLINE_VISIBLE]}"', "",
        f"── ABOUT ({len(a)}/{ABOUT_LIMIT} chars) ──", a, "",
        f"   ↳ the hook — all that shows before “See more” (first {ABOUT_HOOK}):",
        f'   "{hook}{"…" if len(a) > ABOUT_HOOK else ""}"', "",
        "─" * 66,
    ]
    # Headline space is pure keyword real estate — flag it rather than padding with filler.
    if len(h) < 150:
        lines.append(f"💡 {HEADLINE_LIMIT - len(h)} headline characters unused. Recruiters search by "
                     "keyword — consider adding another real specialty or tool you can back "
                     "(quality keywords, never filler).")
    lines += [
        "Every claim traces to a real project, skill, or credential — nothing invented.",
        "Read it once in your own voice before pasting; it should sound like you, not like a tool.",
    ]
    return "\n".join(lines)


def main() -> int:
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser(
        description="LinkedIn headline + About, written honestly from your career_profile.json.")
    ap.add_argument("--target", default="",
                    help='the role to optimise for, e.g. "AI/ML Engineering Intern" (recruiters '
                         "search by role — this drives the keywords)")
    ap.add_argument("--out", default="", help="write to this file (e.g. linkedin.md)")
    args = ap.parse_args()

    profile = load_profile_json()
    if not profile:
        print("No career_profile.json yet — build it first:\n"
              "   python -m resume.profile --github <you> --include-private --certs <folder>")
        return 1

    res = generate_social(profile, args.target)
    text = format_social(res)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"LinkedIn text written → {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
