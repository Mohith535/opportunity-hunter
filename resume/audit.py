"""
Evidence audit — fix the INPUT, and every output gets better.

The rest of this engine is only as strong as the evidence behind it. A repo with no description is
invisible to the resume generator, the cover letter, and the fit matcher — it can't be written about
without inventing, so it simply gets skipped. This module finds those holes and tells you exactly
what to fix.

The distinction that matters most here, and that nothing else in the engine says out loud:

    a certificate proves EXPOSURE.   a repo proves PRACTICE.

A skill backed only by a certificate is the weakest claim you can make — you can defend "I completed
the AWS GenAI course", you cannot defend "I build on AWS". This audit separates those, because an
interviewer will.

Fully deterministic — no LLM, no network. It reads `career_profile.json` and reports.
"""

from __future__ import annotations

from datetime import datetime, timezone

_STALE_DAYS = 14


def audit_profile(profile: dict) -> list[dict]:
    """Concrete evidence problems, each with the fix and why it matters. Severity-ordered by caller."""
    issues: list[dict] = []

    def add(sev: str, issue: str, fix: str, impact: str):
        issues.append({"severity": sev, "issue": issue, "fix": fix, "impact": impact})

    meta = profile.get("meta", {})
    projects = profile.get("projects", [])
    skills = profile.get("skills", [])

    # 1. Projects with no description — the single biggest silent loss.
    undescribed = [p["name"] for p in projects if not (p.get("description") or "").strip()]
    if undescribed:
        add("high",
            f"{len(undescribed)} of {len(projects)} projects have NO GitHub description: "
            f"{', '.join(undescribed[:6])}{'…' if len(undescribed) > 6 else ''}",
            "Add a one-line description on GitHub (what it does + the tech), then rebuild the profile. "
            "One sentence each is enough.",
            "These are skipped by the resume generator, cover letter, and fit matcher — they can't be "
            "written about without inventing, so your real work stays invisible.")

    # 2. Cert-only skills — exposure, not practice.
    cert_only = [s["name"] for s in skills if s.get("x_sources") == ["cert"]]
    if cert_only:
        add("medium",
            f"{len(cert_only)} skills are backed ONLY by a certificate (exposure, not practice): "
            f"{', '.join(cert_only[:8])}{'…' if len(cert_only) > 8 else ''}",
            "Ship one small public repo per skill you actually want to claim. A repo turns 'I took the "
            "course' into 'I built with it'.",
            "You can defend completing the course; you cannot defend building with it. Interviewers "
            "probe exactly this gap.")

    # 3. Thin skills — a single piece of evidence.
    thin = [s["name"] for s in skills if s.get("evidenceCount", 0) == 1 and s.get("x_sources") != ["cert"]]
    if thin:
        add("low",
            f"{len(thin)} skills rest on a single piece of evidence: {', '.join(thin[:8])}"
            f"{'…' if len(thin) > 8 else ''}",
            "Fine to keep — just know these are your thinnest claims. A second project or a mention in "
            "a repo description strengthens them.",
            "Thin ≠ false, but it's the first place a sharp interviewer pushes.")

    # 4. Missing sources.
    sources = meta.get("sources", [])
    if not any(s.startswith("linkedin") for s in sources):
        add("medium",
            "No LinkedIn export in the profile — Work Experience and Education are empty.",
            "When the export arrives: rebuild with --linkedin <folder-or-zip>.",
            "Every document is projects-only until then. Fine for a student, but work history is the "
            "one thing projects can't substitute for.")
    if not any(s.startswith("github") for s in sources):
        add("high", "No GitHub source in the profile — your strongest evidence is missing entirely.",
            "Rebuild with --github <username> --include-private.",
            "Repos are the only evidence that proves practice rather than exposure.")
    elif "github+private" not in sources:
        add("low", "Private repos are NOT included in this profile.",
            "Rebuild with --include-private (needs a GITHUB_TOKEN with 'repo' scope).",
            "Private work is often your most serious work — it can still back a claim even if the code "
            "stays closed.")

    # 5. Staleness.
    gen = meta.get("generated_at", "")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(gen)).days
        if age >= _STALE_DAYS:
            add("medium", f"Profile is {age} days old.",
                "Rebuild it — python -m resume.profile --github <you> --include-private --certs <folder>",
                "New repos, new certificates, and new descriptions aren't reflected until you rebuild.")
    except Exception:
        pass

    # 6. Projects with no topics (weaker skill extraction).
    no_topics = [p["name"] for p in projects
                 if (p.get("description") or "").strip() and len(p.get("keywords") or []) <= 1]
    if no_topics:
        add("low",
            f"{len(no_topics)} described projects carry no GitHub topics: {', '.join(no_topics[:6])}"
            f"{'…' if len(no_topics) > 6 else ''}",
            "Add 3-5 topics per repo (the tech + the domain).",
            "Topics feed skill extraction and JD matching — without them a relevant project can be "
            "missed by the fit matcher.")

    return issues


_ICON = {"high": "🔴", "medium": "🟡", "low": "⚪"}
_ORDER = {"high": 0, "medium": 1, "low": 2}


def format_audit(profile: dict, issues: list[dict]) -> str:
    meta, counts = profile.get("meta", {}), profile.get("meta", {}).get("counts", {})
    lines = ["=" * 64, "EVIDENCE AUDIT — fix the input, every output improves", "=" * 64,
             f"Profile built {meta.get('generated_at', '?')} | sources: {', '.join(meta.get('sources', [])) or '—'}",
             f"skills {counts.get('skills', 0)} · projects {counts.get('projects', 0)} · "
             f"certificates {counts.get('certificates', 0)} · work {counts.get('work', 0)}", ""]
    if not issues:
        lines.append("✅ No evidence gaps found — your profile is in good shape.")
        return "\n".join(lines)

    for it in sorted(issues, key=lambda x: _ORDER.get(x["severity"], 9)):
        lines.append(f"{_ICON.get(it['severity'], '•')} {it['issue']}")
        lines.append(f"     FIX    → {it['fix']}")
        lines.append(f"     WHY    → {it['impact']}")
        lines.append("")
    high = sum(1 for i in issues if i["severity"] == "high")
    lines.append(f"{high} high-impact fix(es). Start there — they cost minutes and strengthen the "
                 "resume, cover letter, simulation, and fit matching all at once.")
    return "\n".join(lines)


def main() -> int:
    from .profile import load_profile_json
    profile = load_profile_json()
    if not profile:
        print("No career_profile.json yet — build it first:\n"
              "   python -m resume.profile --github <you> --include-private --certs <folder>")
        return 1
    print(format_audit(profile, audit_profile(profile)))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
