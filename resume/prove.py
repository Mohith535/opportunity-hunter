"""
"Prove it" — a receipt for every claim on your resume.

The rest of the engine works hard to never invent. This closes the loop from the other side: take a
finished resume (or cover letter) and, line by line, show the EVIDENCE behind each claim — and flag
anything it cannot back.

Why this matters more than it sounds: the resume gets you into the room, but the interview is where
every line is questioned. Walking in already knowing "that bullet is backed by repo X" — and knowing
which single line is your soft spot — is the difference between defending your resume and improvising.

Two directions are checked, deterministically (no LLM, no network):
  * Every verified skill / project you mention  → ✅ receipt (repo: / cert: / linkedin:)
  * Every recognised technology you mention that the profile CANNOT back → ⚠️ flagged

A flag is not an accusation — you may genuinely have used it somewhere the profile can't see (a class
project, work under NDA). It means: *be ready to explain this one, or cut it.*
"""

from __future__ import annotations

import re

from .harvest import _canon, _match_tech

_MIN_LINE = 15  # shorter lines are headings/contact details, not claims


def prove_claims(resume_text: str, profile: dict) -> list[dict]:
    """Per content line: [{line, backed:[(term, [evidence])], unproven:[terms]}]."""
    verified: dict[str, list[str]] = {s["name"]: s.get("evidence", [])
                                      for s in profile.get("skills", [])}
    projects = {(p.get("name") or "").lower(): p for p in profile.get("projects", []) if p.get("name")}
    rows: list[dict] = []

    for raw in resume_text.splitlines():
        line = raw.strip().lstrip("#-*• ").strip()
        if len(line) < _MIN_LINE or line.startswith("*Draft"):
            continue
        # Contact/header lines aren't claims — skip them (a profile URL isn't an assertion of skill).
        if line.startswith("http") or "[add email]" in line or line.startswith("---"):
            continue
        low = line.lower()
        backed: dict[str, list[str]] = {}
        unproven: set[str] = set()

        # (a) recognised tech mentioned in the line — backed or not?
        for term in _match_tech(line):
            c = _canon(term)
            if c in verified:
                backed[c] = verified[c]
            else:
                unproven.add(c)

        # (b) verified skills the lexicon doesn't know (repo languages, topics) mentioned literally
        for skill, ev in verified.items():
            if len(skill) >= 3 and skill not in backed and \
                    re.search(r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])", low):
                backed[skill] = ev

        # (c) named projects are themselves receipts
        for pname, p in projects.items():
            if len(pname) >= 4 and pname in low:
                tag = f"repo:{p['name']}" + (" [private]" if p.get("private") else "")
                backed.setdefault(p["name"], [tag])

        if backed or unproven:
            rows.append({"line": line, "backed": sorted(backed.items()),
                         "unproven": sorted(unproven)})
    return rows


def format_proof(rows: list[dict]) -> str:
    lines = ["=" * 64, "PROVE IT — the receipt behind every claim", "=" * 64, ""]
    if not rows:
        lines.append("No recognisable claims found. Is this the right file?")
        return "\n".join(lines)

    total_backed, all_unproven = 0, set()
    for r in rows:
        lines.append(f"“{r['line'][:96]}{'…' if len(r['line']) > 96 else ''}”")
        for term, ev in r["backed"]:
            total_backed += 1
            lines.append(f"   ✅ {term} ← {', '.join(ev[:3])}{'…' if len(ev) > 3 else ''}")
        for term in r["unproven"]:
            all_unproven.add(term)
            lines.append(f"   ⚠️ {term} — no evidence in your profile")
        lines.append("")

    lines += ["─" * 64,
              f"{total_backed} claim(s) backed by real evidence."]
    if all_unproven:
        lines += [f"{len(all_unproven)} unproven: {', '.join(sorted(all_unproven))}",
                  "",
                  "Unproven ≠ untrue — you may have used these somewhere the profile can't see (a "
                  "course project, private/NDA work). But before you send this:",
                  "  • can you tell a specific story about each one? → keep it",
                  "  • not really? → cut it. One line you can't defend costs more than it earns."]
    else:
        lines.append("Nothing unproven — every claim on this document has a receipt. 🛡️")
    return "\n".join(lines)


def main() -> int:
    import argparse
    from pathlib import Path
    from .analyzer import extract_text
    from .profile import load_profile_json

    ap = argparse.ArgumentParser(
        description="Prove it — show the evidence behind every claim on a resume/cover letter.")
    ap.add_argument("--resume", required=True,
                    help="path to the document to check (.md / .txt / .pdf / .docx)")
    args = ap.parse_args()

    profile = load_profile_json()
    if not profile:
        print("No career_profile.json yet — build it first:\n"
              "   python -m resume.profile --github <you> --include-private --certs <folder>")
        return 1

    p = Path(args.resume)
    try:
        text = extract_text(p) if p.suffix.lower() in (".pdf", ".docx") else \
            p.read_text(encoding="utf-8", errors="ignore")
    except (FileNotFoundError, RuntimeError) as e:
        print(f"Error: {e}")
        return 1

    print(format_proof(prove_claims(text, profile)))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
