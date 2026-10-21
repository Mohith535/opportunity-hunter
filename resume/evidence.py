"""
EVIDENCE BANK — facts from every one of his repos, proposed for HIM to confirm (21 Oct 2026).

Why. Until 21 Oct OPH could read only his public repos, so the skills behind the "Do you fit?" table
and the screening answers cited Java practice folders while nova-cortex and LoopLab were invisible. The
first read of the private repos found what the profile had wrong or missing:
  * nova-cortex's api/app.py is a FastAPI service (POST /remember, /recall, /surface; GET /history,
    /health) — while the drafted Unstop answer said "Not with FastAPI, Flask or Django".
  * nova-cortex has exactly 190 test functions — his resume's "190 tests", confirmed by a second route.
  * LoopLab's repo has 35 commits; his resume says 108. A question for him, never a correction.

Nothing is added on its own. This writes applications/EVIDENCE-TO-CONFIRM.md (gitignored: it describes
private repos); he ticks the lines that are true; --apply adds only those, after a backup.

    py -m resume.evidence           # read the repos, write the checklist
    py -m resume.evidence --apply   # add the ticked lines to data/career_profile.json
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path

import config

APPS = config.BASE_DIR / "applications"
CHECKLIST = APPS / "EVIDENCE-TO-CONFIRM.md"
STORE = APPS / ".evidence-proposals.json"
PROFILE = config.DATA_DIR / "career_profile.json"
OWNER = "Mohith535"

# What a manifest line means, in the names the skills list uses. Only deliberate choices: a framework
# or platform someone installs on purpose, never a transitive helper (dotenv, autoprefixer, @types/*).
_DEPS = {
    "fastapi": "fastapi", "flask": "flask", "django": "django", "flask-sqlalchemy": "sqlalchemy",
    "sqlalchemy": "sqlalchemy", "flask-jwt-extended": "jwt", "pyjwt": "jwt", "psycopg": "postgresql",
    "psycopg2": "postgresql", "psycopg2-binary": "postgresql", "boto3": "aws", "mangum": "aws lambda",
    "pygame": "pygame", "pytest": "pytest", "playwright": "playwright",
    "google-adk": "google adk", "mcp": "mcp", "anthropic": "anthropic api", "openai": "openai api",
    "next": "next.js", "react": "react", "three": "three.js", "express": "express", "vite": "vite",
    "typescript": "typescript", "tailwindcss": "tailwind", "framer-motion": "framer motion",
    "wrangler": "cloudflare workers", "@cloudflare/workers-types": "cloudflare workers",
    "@modelcontextprotocol/sdk": "mcp", "hono": "hono", "zod": "zod", "vitest": "vitest", "jest": "jest",
}
# A Python web framework in requirements.txt is only claimed when the code imports it: a manifest line
# alone can be a leftover. nova-cortex's api/app.py was checked this way first.
_PY_LIBS = {"fastapi", "flask", "django", "sqlalchemy", "jwt", "postgresql", "aws", "aws lambda", "pygame",
            "pytest", "playwright", "google adk", "mcp", "anthropic api", "openai api"}
_VERIFY_IMPORT = {"fastapi": r"from fastapi import|import fastapi", "flask": r"from flask import|import flask",
                  "django": r"from django|import django"}


def frameworks_from(path: str, text: str) -> set[str]:
    """Skills a manifest file states, by name. requirements.txt / pyproject / package.json."""
    names: set[str] = set()
    if path.endswith(".txt"):
        names = {m.lower() for m in re.findall(r"^\s*([A-Za-z][\w.\-]*)", text, re.M)}
    elif path.endswith(".toml"):
        names = {m.lower() for m in re.findall(r'["\']([A-Za-z][\w.\-]*)\s*(?:[<>=~!\[;"\'])', text)}
        if re.search(r"^\s*name\s*=", text, re.M) and "wrangler" in path:
            names.add("wrangler")
    elif path.endswith("package.json"):
        try:
            pj = json.loads(text)
        except ValueError:
            return set()
        names = {k.lower() for sec in ("dependencies", "devDependencies") for k in (pj.get(sec) or {})}
    return {_DEPS[n] for n in names if n in _DEPS}


def claims_in(highlights: list[str]) -> dict[str, int]:
    """The numbers his resume states about a project that a repo can check: commits and tests."""
    text = " ".join(highlights or [])
    out = {}
    for key, pat in (("commits", r"(\d[\d,]*)\s+commits"), ("tests", r"(\d[\d,]*)\s+(?:automated\s+)?(?:tests|checks)\b")):
        m = re.search(pat, text)
        if m:
            out[key] = int(m.group(1).replace(",", ""))
    return out


def test_count(path: str, text: str) -> int:
    if path.endswith(".py"):
        return len(re.findall(r"^\s*(?:async\s+)?def test_|^\s*check\(", text, re.M))
    return len(re.findall(r"(?:^|[^\w.])(?:it|test)\s*\(\s*['\"`]|^\s*check\(", text, re.M))


# ─── collecting (network) ─────────────────────────────────────────────────────────────────────
def _gh():
    import requests  # noqa: PLC0415
    from dotenv import load_dotenv  # noqa: PLC0415
    load_dotenv(config.BASE_DIR / ".env", override=True)
    tok = os.environ.get("GITHUB_TOKEN", "")
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json", "User-Agent": config.USER_AGENT}
    return requests, tok, h


def _no_params(routes):
    """Routes without a <param> or {param}: on a resume "<tracking_id>" reads as template text left in."""
    return [(v, r) for v, r in routes if not re.search(r"[<{]", r)]


def collect(repo: dict) -> dict:
    """Facts about one repo, each with where it came from. Never raises: a repo that fails is skipped."""
    requests, _, H = _gh()
    raw = {**H, "Accept": "application/vnd.github.raw"}
    name = repo["name"]
    base = f"https://api.github.com/repos/{OWNER}/{name}"
    f = {"repo": name, "private": bool(repo.get("private")), "description": repo.get("description") or "",
         "homepage": repo.get("homepage") or "", "created": (repo.get("created_at") or "")[:10],
         "pushed": (repo.get("pushed_at") or "")[:10], "skills": {}, "routes": [], "tests": 0, "test_files": 0}
    try:
        lang = requests.get(repo["languages_url"], headers=H, timeout=20).json()
        tot = sum(lang.values()) or 1
        f["languages"] = [(k, round(v * 100 / tot)) for k, v in sorted(lang.items(), key=lambda kv: -kv[1])[:3]]
        c = requests.get(f"{base}/commits", params={"per_page": 1}, headers=H, timeout=20)
        m = re.search(r'page=(\d+)>; rel="last"', c.headers.get("Link", ""))
        f["commits"] = int(m.group(1)) if m else len(c.json() if c.ok else [])
        tree = requests.get(f"{base}/git/trees/HEAD", params={"recursive": 1}, headers=H, timeout=30).json().get("tree") or []
    except Exception as e:  # noqa: BLE001
        f["error"] = type(e).__name__
        return f
    paths = [t["path"] for t in tree if t.get("type") == "blob" and "node_modules/" not in t["path"]]
    get = lambda p: requests.get(f"{base}/contents/{p}", headers=raw, timeout=20).text  # noqa: E731
    for p in [p for p in paths if re.search(r"(^|/)(requirements\.txt|pyproject\.toml|package\.json|wrangler\.toml)$", p)][:6]:
        for s in frameworks_from(p, get(p)):
            f["skills"].setdefault(s, f"{p} lists it")
    py = [p for p in paths if p.endswith(".py")]
    f["py_files"] = len(py)
    if not py:
        # swiftship-flask-mysql has a requirements.txt naming Flask, SQLAlchemy and JWT, and no Python at
        # all (HTML/JS/CSS): a list of libraries is not code that uses them.
        for s in [s for s in f["skills"] if s in _PY_LIBS]:
            del f["skills"][s]
    for s, pat in _VERIFY_IMPORT.items():
        if s in f["skills"]:
            used = next((p for p in py[:60] if re.search(pat, get(p))), None)
            if used:
                f["skills"][s] = f"{used} imports it"
                if s in ("fastapi", "flask"):
                    f["routes"] = [(r if v == "route" else f"{v.upper()} {r}") for v, r in _no_params(re.findall(
                        r'@\w+\.(get|post|put|delete|patch|route)\(\s*["\']([^"\']+)', get(used)))][:8]
            else:
                del f["skills"][s]                    # listed, never imported: not evidence
    tests = [p for p in paths if re.search(r"(^|/)tests?/|(^|/)test_[^/]+\.py$|\.(test|spec)\.(m?[jt]s)$", p)]
    f["test_files"] = len(tests)
    f["tests"] = sum(test_count(p, get(p)) for p in tests[:40])
    return f


# ─── proposing (pure) ─────────────────────────────────────────────────────────────────────────
def _project_for(profile: dict, repo: str) -> dict | None:
    for p in profile.get("projects", []):
        url = (p.get("url") or "").rstrip("/").lower()
        if url.endswith(f"/{repo.lower()}") or (p.get("x_resume_name") or "").lower() == repo.lower():
            if p.get("x_source") == "resume-2026-09" or p.get("x_confirmed"):
                return p
    return None


SHOW = {"next.js": "Next.js", "react": "React", "tailwind": "Tailwind CSS", "three.js": "three.js", "typescript": "TypeScript", "framer motion": "Framer Motion", "cloudflare workers": "Cloudflare Workers", "flask": "Flask", "jwt": "JWT", "sqlalchemy": "SQLAlchemy", "zod": "Zod", "fastapi": "FastAPI", "postgresql": "PostgreSQL", "aws": "AWS", "aws lambda": "AWS Lambda", "mcp": "MCP", "google adk": "Google ADK", "vite": "Vite", "pytest": "pytest", "playwright": "Playwright", "pygame": "pygame", "express": "Express", "django": "Django", "hono": "Hono"}   # how a skill is written in a sentence


def _cap(s: str) -> str:
    """First letter up, the rest untouched — str.capitalize() turned "Flask REST API" into "flask rest api"."""
    return s[:1].upper() + s[1:]


def proposals(facts: list[dict], profile: dict) -> list[dict]:
    """Every line he might confirm. kind: skill (a repo backs a skill), fact (a sentence for a project he
    already shows), project (a repo not on his resume yet), check (a resume number this repo confirms),
    question (a resume number this repo does NOT match — his to explain, never ours to fix)."""
    have = {s["name"].lower(): set(s.get("evidence") or []) for s in profile.get("skills", [])}
    out, seen = [], set()
    for f in facts:
        if f.get("error") or f["repo"].lower() in seen:
            continue
        seen.add(f["repo"].lower())                     # the repo listing returned NitroWatch twice
        repo = f["repo"]
        proj = _project_for(profile, repo)
        for skill, how in sorted(f["skills"].items()):
            if f"repo:{repo}" not in have.get(skill, set()):
                out.append({"kind": "skill", "repo": repo, "skill": skill,
                            "text": f"**{skill}** — built with it in `{repo}` ({how})"})
        # A skill the profile ALREADY credits to this repo, which has no code for it: the June harvest
        # read repo names, so "swiftship-flask-mysql" made Flask a built skill. His to answer.
        if f.get("py_files") == 0:
            for skill in sorted(_PY_LIBS):
                if f"repo:{repo}" in have.get(skill, set()):
                    langs = ", ".join(n for n, _ in f.get("languages") or []) or "no code"
                    out.append({"kind": "question", "repo": repo, "text":
                                f"your profile counts **{skill}** as built because of `{repo}` — but that repo has "
                                f"no Python code ({langs}). Is the backend somewhere else? If not, I'll take "
                                f"{skill} off your BUILT list."})
        if f["routes"] and proj:
            fw = "FastAPI" if "fastapi" in f["skills"] else "Flask"
            sent = f"Its API is a {fw} service: " + ", ".join(f["routes"][:6]) + "."
            if not any(fw in h for h in proj.get("highlights") or []):
                out.append({"kind": "fact", "repo": repo, "project": proj.get("x_resume_name"),
                            "text": f"**{proj.get('x_resume_name')}** — {sent} _(from `{repo}`)_", "sentence": sent})
        if proj:
            stated = claims_in(proj.get("highlights") or [])
            mine = {"commits": f.get("commits") or 0, "tests": f.get("tests") or 0}
            for k, v in stated.items():
                if mine[k] == v:
                    out.append({"kind": "check", "repo": repo, "text": f"your resume says **{v} {k}** for "
                                f"{proj.get('x_resume_name')} — `{repo}` has exactly {mine[k]} ✓"})
                elif mine[k]:
                    out.append({"kind": "question", "repo": repo, "text": f"your resume says **{v} {k}** for "
                                f"{proj.get('x_resume_name')}; the `{repo}` repo shows **{mine[k]}**. Another repo, "
                                f"another branch, or a different git email? Only you know — tell me, and I keep yours."})
        elif not f.get("private") or f["skills"] or f.get("homepage"):
            langs = ", ".join(f"{n} {p}%" for n, p in f.get("languages") or [])
            bits = [f"{f.get('description') or repo}"]
            if f["routes"]:
                fw = "FastAPI" if "fastapi" in f["skills"] else "Flask"
                bits.append(f"a {fw} REST API: " + ", ".join(f["routes"][:6]))
            if f["skills"]:
                main = (f.get("languages") or [("", 0)])[0][0]
                shown = [SHOW.get(k, k) for k in sorted(f["skills"])]
                lead = f"{main}, with " if main and main not in shown and main not in ("HTML", "CSS") else "built with "
                bits.append(lead + ", ".join(shown))
            if f.get("homepage"):
                bits.append(f"live at {f['homepage'].replace('https://', '')}")
            if f.get("tests"):
                bits.append(f"{f['tests']} tests")
            if f["skills"] or f.get("homepage") or f.get("tests"):
                out.append({"kind": "project", "repo": repo, "text": f"**{repo}** — " + "; ".join(bits)
                            + (f" ({langs})" if langs else ""), "sentence": _cap("; ".join(bits[1:])) + "."})
    for n, p in enumerate(out, 1):
        p["id"] = n
    return out


def render(props: list[dict]) -> str:
    head = {"question": "## Questions — numbers on your resume a repo does not match (answer me; I keep your answer)",
            "check": "## Already right — checked against the repo (nothing to do)",
            "fact": "## New facts for projects on your resume",
            "skill": "## Skills your repos prove (the \"Do you fit?\" table counts these as BUILT)",
            "project": "## Repos not on your resume yet (ticking one makes it evidence, not a resume section)"}
    L = ["# Evidence to confirm", "",
         f"_Read from your GitHub on {date.today().isoformat()} (edi-vault is never read). Nothing below is in "
         "your profile yet. Change `[ ]` to `[x]` on every line that is TRUE and that you could explain in an "
         "interview, then run:_ `py -m resume.evidence --apply`", ""]
    for kind in ("question", "check", "fact", "skill", "project"):
        rows = [p for p in props if p["kind"] == kind]
        if not rows:
            continue
        L += [head[kind], ""]
        for p in rows:
            box = "" if kind in ("question", "check") else "[ ] "
            L.append(f"- {box}{p['text']}  <!-- id:{p['id']} -->")
        L.append("")
    return "\n".join(L)


def ticked(md: str) -> set[int]:
    return {int(m) for m in re.findall(r"^- \[[xX]\].*<!-- id:(\d+) -->", md, re.M)}


def apply_to(profile: dict, props: list[dict], ids: set[int], today: str) -> tuple[dict, list[str]]:
    """The profile with the ticked lines added, and a line per change. Pure: the caller writes it."""
    prof = json.loads(json.dumps(profile))
    done = []
    skills = {s["name"].lower(): s for s in prof.setdefault("skills", [])}
    for p in props:
        if p["id"] not in ids:
            continue
        if p["kind"] == "skill":
            s = skills.get(p["skill"]) or {"name": p["skill"], "evidenceCount": 0, "evidence": []}
            if p["skill"] not in skills:
                prof["skills"].append(s)
                skills[p["skill"]] = s
            ev = f"repo:{p['repo']}"
            if ev not in s["evidence"]:
                s["evidence"].append(ev)
                s["evidenceCount"] = len(s["evidence"])
                done.append(f"skill {p['skill']} ← {p['repo']}")
        elif p["kind"] == "fact":
            proj = next((x for x in prof.get("projects", []) if x.get("x_resume_name") == p["project"]), None)
            if proj is not None and p["sentence"] not in (proj.get("highlights") or []):
                proj.setdefault("highlights", []).append(p["sentence"])
                done.append(f"{p['project']}: + “{p['sentence'][:60]}”")
        elif p["kind"] == "project":
            proj = next((x for x in prof.get("projects", []) if (x.get("url") or "").rstrip("/").lower()
                         .endswith("/" + p["repo"].lower())), None)
            if proj is None:
                proj = {"name": p["repo"], "url": f"https://github.com/{OWNER}/{p['repo']}"}
                prof.setdefault("projects", []).append(proj)
            proj["x_resume_name"] = proj.get("x_resume_name") or p["repo"]
            proj["x_confirmed"] = today
            if p.get("sentence") and p["sentence"] not in (proj.get("highlights") or []):
                proj["highlights"] = [p["sentence"]] + list(proj.get("highlights") or [])
            done.append(f"project {p['repo']} confirmed")
    return prof, done


STUDY = APPS / "KNOW-YOUR-CODE.md"


def study_list(props: list[dict], ids: set[int], job_texts: list[str]) -> str:
    """What to be able to explain, for every skill he confirmed — most-asked first. He chose to claim them
    all on 21 Oct ("imagine I can explain everything — I will learn them"), so the bridge from "it is in my
    repo" to "I can explain it in an interview" is a reading list from his own code, not a course."""
    blob = " ".join(job_texts).lower()
    rows: dict[str, list[str]] = {}
    for p in props:
        if p["id"] in ids and p["kind"] == "skill":
            how = re.sub(r"^.*\((.*)\)$", r"\1", p["text"])
            rows.setdefault(p["skill"], []).append(f"`{p['repo']}` — {how}")
    for p in props:
        if p["id"] in ids and p["kind"] in ("fact", "project") and re.search(r"FastAPI|Flask", p["text"]):
            fw = "fastapi" if "FastAPI" in p["text"] else "flask"
            rows.setdefault(fw, []).append(f"`{p['repo']}` — routes: " + (p.get("sentence") or "").split(":", 1)[-1].strip())
    demand = {s: len(re.findall(r"\b" + re.escape(s.replace(".js", "")) + r"(?:\.js)?\b", blob)) for s in rows}
    L = ["# Know your own code", "",
         "_Every skill below is now on your BUILT list because a repo of yours uses it. Before an interview "
         "for a job that names one, open the file and be able to say three things out loud._", "",
         "**For each:** (1) what it does in your project, (2) why you chose it over the obvious "
         "alternative, (3) one problem you hit with it and how you fixed it — with a number if you have one.", ""]
    for s in sorted(rows, key=lambda k: (-demand[k], k)):
        asked = f"asked in {demand[s]} of the job texts OPH saw" if demand[s] else "not asked yet in your jobs"
        L += [f"## {SHOW.get(s, s)} — {asked}", *[f"- {r}" for r in dict.fromkeys(rows[s])], ""]
    return "\n".join(L)


def _job_texts() -> list[str]:
    try:
        runs = json.loads(config.HISTORY_FILE.read_text(encoding="utf-8")).get("runs") or []
    except (OSError, ValueError, AttributeError):
        return []
    return [f"{i.get('title', '')} {i.get('description', '')}" for r in runs[-30:] for i in r.get("items") or []
            if any(t in (i.get("tags") or []) for t in ("internship", "job"))]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--study" in sys.argv[1:]:
        props = json.loads(STORE.read_text(encoding="utf-8"))
        STUDY.write_text(study_list(props, ticked(CHECKLIST.read_text(encoding="utf-8")), _job_texts()), encoding="utf-8")
        print(f"Wrote applications/{STUDY.name}")
        return 0
    if "--apply" in sys.argv[1:]:
        if not (CHECKLIST.exists() and STORE.exists()):
            print("Run `py -m resume.evidence` first — there is no checklist to apply.")
            return 1
        props = json.loads(STORE.read_text(encoding="utf-8"))
        ids = ticked(CHECKLIST.read_text(encoding="utf-8"))
        if not ids:
            print("Nothing is ticked. Change [ ] to [x] on the lines that are true, then run this again.")
            return 0
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        new, done = apply_to(profile, props, ids, date.today().isoformat())
        backup = PROFILE.with_name(f"career_profile.backup-{date.today().isoformat()}.json")
        shutil.copy2(PROFILE, backup)
        PROFILE.write_text(json.dumps(new, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Added {len(done)} line(s) to your profile (backup: data/{backup.name}):")
        for d in done:
            print("  +", d)
        STUDY.write_text(study_list(props, ids, _job_texts()), encoding="utf-8")
        print(f"\nWhat to be able to explain, most-asked first: applications/{STUDY.name}")
        print("The cloud uses a copy — run `py sync_secrets.py` so tomorrow's packs have it too.")
        return 0
    from .harvest import _github_repos  # noqa: PLC0415
    _, tok, _ = _gh()
    if not tok:
        print("GITHUB_TOKEN is not set in .env — nothing to read your private repos with.")
        return 1
    repos = _github_repos(OWNER, tok, include_private=True)
    print(f"Reading {len(repos)} repos (edi-vault never)…")
    facts = [collect(r) for r in repos]
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    props = proposals(facts, profile)
    APPS.mkdir(exist_ok=True)
    STORE.write_text(json.dumps(props, indent=1, ensure_ascii=False), encoding="utf-8")
    CHECKLIST.write_text(render(props), encoding="utf-8")
    kinds = {k: sum(1 for p in props if p["kind"] == k) for k in ("question", "check", "fact", "skill", "project")}
    print(f"Wrote applications/{CHECKLIST.name}: " + ", ".join(f"{v} {k}" for k, v in kinds.items() if v))
    print("Tick the true lines, then: py -m resume.evidence --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
