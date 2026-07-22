"""
Profile Engine (Slice 5) — the single source of truth for "who Mohith is, professionally".

The insight (credit: a good architecture nudge): instead of every feature re-reading GitHub, certs,
and LinkedIn separately, we normalise all of it ONCE into a single `career_profile.json`, and every
career-intelligence feature reads from that. New sources (Credly, Coursera, a Google Developer
profile) just merge into the same file.

Three deliberate design decisions keep this honest and in-bounds:

  1. It aligns to the JSON Resume open standard (basics / work / education / skills / projects /
     certificates) instead of a bespoke shape — interoperable, and it happens to match the `basics`
     key Nova already uses. We extend it (an `x_` namespace) with two things the standard lacks:
       * per-skill EVIDENCE — the provenance trail (repo:/cert:/linkedin:) that makes the never-invent
         guarantee survive persistence. A flat skills list would throw that away.
       * a `declared` layer — interests / companies / psychology from the existing user_profile.py,
         so the one file holds BOTH what Mohith has DONE (verified) and what he WANTS (declared).

  2. It UNIFIES the two profiles that already exist (verified harvest + declared user_profile) rather
     than adding a third competing one.

  3. It stays OPHunter's LOCAL cache/artifact. It is NOT a cross-project memory graph — that's Nova's
     job. Post-Kaggle, OPHunter can EMIT this to Nova's graph (the "emit" organ step); it does not
     become one. And per the Kaggle freeze, only the branch's career-intelligence modules read it —
     the frozen opportunity scorer is left untouched.

Free, offline-friendly, never crashes on a missing source. Output is gitignored (personal data).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .harvest import _canon, github_projects, harvest

_BASE = Path(__file__).resolve().parent.parent
DEFAULT_PATH = _BASE / "data" / "career_profile.json"


# ─── build ───────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _apply_resume(profile: dict, r: dict) -> dict:
    """Merge an ingested résumé into the profile — the richest source the user owns.

    Résumé content is SELF-ASSERTED, so it is tagged `resume:` and never silently upgraded to the
    same standing as a repo or certificate. But it carries what nothing else can: education, awards
    and programs, real project depth, and contact details.
    """
    tag = f"resume:{r.get('_source_file', 'resume')[:32]}"
    rb = r.get("basics") or {}
    b = profile["basics"]

    for key in ("name", "email", "phone", "location", "summary"):
        if rb.get(key):
            b[key] = rb[key]
    b.setdefault("profiles", [])
    for net, url in (("LinkedIn", rb.get("linkedin")), ("Portfolio", rb.get("portfolio")),
                     ("GitHub", rb.get("github"))):
        if url and not any(p.get("network") == net for p in b["profiles"]):
            b["profiles"].append({"network": net, "url": url})

    if r.get("education"):
        profile["education"] = r["education"] + [e for e in profile.get("education", [])]
    if r.get("work"):
        profile["work"] = r["work"] + [w for w in profile.get("work", [])]
    # Awards / selections / programs — a section GitHub and certificates simply cannot produce.
    profile["awards"] = r.get("awards") or []

    # Certificates from a résumé carry issuer + date; folder-derived ones are just filenames.
    if r.get("certificates"):
        seen = {_norm(c.get("name", "")) for c in r["certificates"]}
        rich = [{"name": c.get("name", ""), "issuer": c.get("issuer", ""), "date": c.get("date", ""),
                 "x_source": "resume"} for c in r["certificates"] if c.get("name")]
        keep = [c for c in profile.get("certificates", [])
                if not any(_norm(c["name"]).startswith(s[:12]) or s.startswith(_norm(c["name"])[:12])
                           for s in seen if s)]
        profile["certificates"] = rich + keep

    # Projects: enrich matching repos with the résumé's real bullets; append résumé-only projects.
    gh = profile.get("projects", [])
    for rp in r.get("projects") or []:
        rn = _norm(rp.get("name", ""))
        if not rn:
            continue
        match = next((p for p in gh if _norm(p["name"]) and
                      (rn.startswith(_norm(p["name"])) or _norm(p["name"]).startswith(rn[:14]))), None)
        if match:
            match["highlights"] = rp.get("highlights") or []
            match["x_resume_name"] = rp.get("name")
            if rp.get("description") and len(rp["description"]) > len(match.get("description") or ""):
                match["description"] = rp["description"]
            match["keywords"] = list(dict.fromkeys((match.get("keywords") or []) +
                                                   (rp.get("keywords") or [])))
        else:
            gh.append({"name": rp.get("name"), "description": rp.get("description", ""),
                       "keywords": rp.get("keywords") or [], "url": "", "private": False,
                       "highlights": rp.get("highlights") or [], "x_source": "resume"})
    profile["projects"] = gh

    # Skills the résumé asserts — visible as self-asserted, never dressed up as verified.
    by_name = {s["name"]: s for s in profile.get("skills", [])}
    for raw in r.get("skills") or []:
        name = _canon(re.sub(r"\(.*?\)", "", str(raw)).strip())
        if not name or len(name) < 2:
            continue
        if name in by_name:
            if tag not in by_name[name]["evidence"]:
                by_name[name]["evidence"].append(tag)
                by_name[name]["evidenceCount"] = len(by_name[name]["evidence"])
                if "resume" not in by_name[name]["x_sources"]:
                    by_name[name]["x_sources"].append("resume")
        else:
            by_name[name] = {"name": name, "evidenceCount": 1, "evidence": [tag],
                             "x_sources": ["resume"]}
    profile["skills"] = sorted(by_name.values(),
                               key=lambda s: (-s["evidenceCount"], s["name"]))
    return profile


def build_profile(github_user: str | None = None, certs_folder: str | None = None,
                  linkedin: str | None = None, include_private: bool = False,
                  token: str | None = None, resume_path: str | None = None) -> dict:
    """Gather every source and normalise into one JSON-Resume-aligned profile with evidence.

    Every argument is optional; whatever's provided is merged. Never raises on a missing/broken
    source — it just contributes nothing.
    """
    merged = harvest(github_user, certs_folder, token=token,
                     include_private=include_private, linkedin=linkedin)

    # skills → JSON-Resume-ish entries, evidence + provenance preserved.
    skills = []
    for name, evidence in sorted(merged["skills"].items(), key=lambda kv: (-len(kv[1]), kv[0])):
        sources = sorted({e.split(":", 1)[0] for e in evidence})  # repo / cert / linkedin
        skills.append({"name": name, "evidenceCount": len(evidence),
                       "evidence": evidence, "x_sources": sources})

    certificates = [{"name": c, "x_source": "linkedin" if " — " in c else "certs-folder"}
                    for c in _dedup(merged["certifications"])]
    work = merged.get("positions", [])

    # LinkedIn-only extras (headline / summary / education) come from a direct read.
    headline = summary = ""
    education: list[dict] = []
    if linkedin:
        from .linkedin import linkedin_profile  # noqa: PLC0415
        li = linkedin_profile(linkedin)
        headline, summary, education = li["headline"], li["summary"], li.get("education", [])

    projects = github_projects(github_user, token, include_private) if github_user else []

    # Declared layer (interests / companies / psychology) from the EXISTING profile system.
    declared, name = _declared_layer()

    basics = {"name": name, "label": headline, "summary": summary or declared.get("identity", ""),
              "profiles": []}
    if github_user:
        basics["profiles"].append({"network": "GitHub", "username": github_user,
                                   "url": f"https://github.com/{github_user}"})

    sources = []
    if github_user:
        sources.append("github" + ("+private" if include_private else ""))
    if certs_folder:
        sources.append("certs")
    if linkedin:
        sources.append("linkedin")
    if declared:
        sources.append("declared")

    profile = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "schema": "jsonresume-1.0.0+ophunter",
            "sources": sources,
            "counts": {},
        },
        "basics": basics,
        "skills": skills,
        "certificates": certificates,
        "work": work,
        "projects": projects,
        "education": education,
        "awards": [],
        "x_declared": declared,   # what Mohith WANTS — interests, companies, goals, psychology
    }

    if resume_path:
        from .ingest import ingest_resume  # noqa: PLC0415
        try:
            ingested = ingest_resume(resume_path)
        except (FileNotFoundError, RuntimeError):
            ingested = {}
        if ingested:
            profile = _apply_resume(profile, ingested)
            sources.append("resume")

    profile["meta"]["counts"] = {
        "skills": len(profile["skills"]), "certificates": len(profile["certificates"]),
        "projects": len(profile["projects"]), "work": len(profile["work"]),
        "education": len(profile["education"]), "awards": len(profile.get("awards", [])),
    }
    return profile


def _declared_layer() -> tuple[dict, str]:
    """(declared-preferences dict, name) from the existing user_profile.py. ({}, 'Mohith') on failure."""
    try:
        import user_profile  # noqa: PLC0415  (project root)
        p = user_profile.load_profile()
        return ({
            "identity": p.identity,
            "longTermGoal": p.long_term_goal,
            "personalPurpose": p.personal_purpose,
            "interests": p.interests,
            "companies": p.companies,
            "opportunityTypes": p.opportunity_types,
            "geo": p.geo,
            "values": p.values,
            "drivers": p.drivers,
            "learned": p.learned,
        }, p.name)
    except Exception:
        return {}, "Mohith"


def _dedup(seq: list[str]) -> list[str]:
    seen, out = set(), []
    for s in seq:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


# ─── persist ─────────────────────────────────────────────────────────
def save_profile(profile: dict, path: str | Path = DEFAULT_PATH) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def load_profile_json(path: str | Path = DEFAULT_PATH) -> dict | None:
    """The cached profile, or None if it hasn't been built yet / is unreadable."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def to_harvest_shape(profile: dict) -> dict:
    """Back to the {skills, certifications, positions} shape harvest() emits, so existing consumers
    (verify_against, the simulation's profile block) can read the CACHED single source of truth."""
    return {
        "skills": {s["name"]: s.get("evidence", []) for s in profile.get("skills", [])},
        "certifications": [c["name"] for c in profile.get("certificates", [])],
        "positions": profile.get("work", []),
    }


def relevant_projects(profile: dict, keywords: list[str], limit: int = 6) -> list[dict]:
    """The candidate's REAL projects most relevant to this job — ranked by keyword overlap.

    Only projects that carry real info (a description or tech keywords) are eligible, so the tailorer
    never has to guess what an untitled repo does.
    """
    kws = {k.lower().strip() for k in keywords if k.strip()}
    scored = []
    for p in profile.get("projects", []):
        if not (p.get("description") or p.get("keywords")):
            continue  # nothing real to say about it — skip rather than invent
        hay = (f"{p.get('name','')} {p.get('description','')} "
               f"{' '.join(p.get('keywords') or [])}").lower()
        overlap = sum(1 for k in kws if k and k in hay)
        if overlap:
            scored.append((overlap, p))
    scored.sort(key=lambda s: -s[0])
    return [p for _, p in scored[:limit]]


def evidence_context(profile: dict, keywords: list[str], project_limit: int = 6) -> str:
    """A prompt-ready block of the candidate's REAL projects + work history, for honest tailoring.

    Everything here is sourced (real GitHub repos, real LinkedIn roles), so the tailorer can strengthen
    the resume with genuine experience it might be omitting — without ever inventing.
    """
    lines: list[str] = []
    projects = relevant_projects(profile, keywords, project_limit)
    if projects:
        lines.append("REAL PROJECTS you've actually built (from your verified GitHub):")
        for p in projects:
            priv = " [private]" if p.get("private") else ""
            tech = ", ".join(p.get("keywords") or [])
            desc = p.get("description") or "(no description on GitHub)"
            lines.append(f"- {p.get('name')}{priv}: {desc}" + (f"  (tech: {tech})" if tech else ""))
    work = profile.get("work", [])
    if work:
        lines.append("REAL WORK history (from your LinkedIn export):")
        for w in work:
            when = " – ".join(x for x in [w.get("start"), w.get("end")] if x)
            lines.append(f"- {w.get('title')} at {w.get('company')}"
                         + (f" ({when})" if when else "") + f": {w.get('description', '')}")
    return "\n".join(lines)


# ─── present ─────────────────────────────────────────────────────────
def format_summary(profile: dict) -> str:
    m = profile.get("meta", {})
    c = m.get("counts", {})
    lines = ["=" * 60, "CAREER PROFILE — single source of truth", "=" * 60,
             f"Built: {m.get('generated_at','?')}  |  sources: {', '.join(m.get('sources', [])) or '—'}",
             f"Skills: {c.get('skills',0)}  |  Certificates: {c.get('certificates',0)}  |  "
             f"Projects: {c.get('projects',0)}  |  Work: {c.get('work',0)}  |  "
             f"Education: {c.get('education',0)}", ""]
    top = profile.get("skills", [])[:12]
    if top:
        lines.append("Top verified skills (by independent evidence):")
        for s in top:
            lines.append(f"  • {s['name']:16} ×{s['evidenceCount']}  [{', '.join(s.get('x_sources', []))}]")
    priv = [p for p in profile.get("projects", []) if p.get("private")]
    if priv:
        lines.append(f"\nPrivate projects included: {', '.join(p['name'] for p in priv)}")
    dec = profile.get("x_declared", {})
    if dec:
        interests = sorted(dec.get("interests", {}).items(), key=lambda kv: kv[1], reverse=True)[:6]
        lines.append("\nDeclared focus (what you're chasing): "
                     + ", ".join(k for k, _ in interests))
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────
def main() -> int:
    import argparse
    import os
    ap = argparse.ArgumentParser(
        description="Profile Engine — normalise GitHub + certs + LinkedIn into one career_profile.json.")
    ap.add_argument("--github", default="", help="your GitHub username")
    ap.add_argument("--include-private", action="store_true", help="include private repos (needs token)")
    ap.add_argument("--certs", default="", help="path to your certificates folder")
    ap.add_argument("--linkedin", default="", help="path to your LinkedIn data-export folder or .zip")
    ap.add_argument("--resume", default="",
                    help="path to your EXISTING resume (.pdf/.docx/.txt) — the richest source you "
                         "own: education, awards/programs, real project depth, contact details")
    ap.add_argument("--out", default=str(DEFAULT_PATH), help="where to write the profile JSON")
    ap.add_argument("--show", action="store_true", help="just show the cached profile, don't rebuild")
    args = ap.parse_args()

    if args.show:
        cached = load_profile_json(args.out)
        print(format_summary(cached) if cached else "No cached profile yet — build one first.")
        return 0

    token = os.environ.get("GITHUB_TOKEN")
    try:
        import config  # noqa: PLC0415
        token = getattr(config, "GITHUB_TOKEN", None) or token
    except Exception:
        pass

    profile = build_profile(args.github or None, args.certs or None, args.linkedin or None,
                            include_private=args.include_private, token=token,
                            resume_path=args.resume or None)
    path = save_profile(profile, args.out)
    print(format_summary(profile))
    print(f"\nSaved → {path}  (gitignored; your single source of truth from now on)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
