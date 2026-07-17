"""
Profile harvesting (Slice 3) — build a VERIFIED skill set from what the candidate has actually done.

Slices 1–2 made you type `--have "Docker,SQL"` by hand. This slice fills that in automatically — but
only with skills it can PROVE. It reads two evidence sources the candidate genuinely owns:

  * GitHub  — public repos: primary `language`, assigned `topics`, and tech terms in each
    description. A repo written in Python is real evidence of Python; a repo tagged `github-actions`
    is real evidence of that. Free, unauthenticated (60 req/hr) or with the project's GITHUB_TOKEN.
  * Certificates folder — the credential is encoded in each filename (e.g. "AWS Building a Generative
    AI", "Google AI Essentials", "IBM LLM"). We clean off dates/noise and match tech terms.

The never-invent rule is UPHELD, not bypassed: every skill this returns carries an evidence trail
(`repo:<name>` / `cert:<title>`). Auto-confirming "Docker" because a real repo uses it is honest —
it's proof, not a guess. Skills with no evidence are never added; the gap list still asks about those.

No LinkedIn scraping (against ToS, and brittle) — LinkedIn integration, if ever, is via the user's own
data export, not this module.
"""

from __future__ import annotations

import re
from pathlib import Path

# Tech/skill phrases we recognise in free text (repo descriptions, cert titles). Curated so a match
# means something — we never emit a skill that isn't on this list from free text. Languages/topics
# from GitHub are trusted directly (they're structured, not guessed).
_TECH = [
    "python", "javascript", "typescript", "java", "c++", "c#", "kotlin", "swift", "go", "rust",
    "php", "ruby", "scala", "r", "matlab", "sql", "html", "css", "bash", "shell",
    "react", "angular", "vue", "next.js", "node", "express", "flask", "fastapi", "django",
    "spring", "streamlit", "tailwind", "bootstrap",
    "docker", "kubernetes", "aws", "azure", "gcp", "google cloud", "cloud", "terraform",
    "linux", "git", "github actions", "ci/cd", "devops",
    "mysql", "postgresql", "postgres", "mongodb", "redis", "sqlite", "firebase", "supabase",
    "machine learning", "deep learning", "neural networks", "nlp", "computer vision",
    "llm", "llms", "large language models", "generative ai", "genai", "gen ai",
    "ai agents", "agentic", "agents", "mcp", "rag", "prompt engineering", "prompting",
    "pytorch", "tensorflow", "keras", "scikit-learn", "pandas", "numpy", "opencv", "hugging face",
    "data analytics", "data analysis", "data science", "power bi", "tableau", "excel",
    "rest api", "rest apis", "api", "graphql", "microservices", "automation", "web scraping",
    "cybersecurity", "security", "security copilot", "critical thinking", "ui/ux", "ui ux",
]

# Fold alias spellings onto one canonical skill so "gen ai" / "genai" / "generative ai" don't show up
# as three separate skills, and JD keywords verify against the same canonical form.
_CANON = {
    "gen ai": "generative ai", "genai": "generative ai",
    "llms": "llm", "large language models": "llm",
    "rest apis": "rest api",
    "postgres": "postgresql",
    "gcp": "google cloud",
    "ui ux": "ui/ux",
    "js": "javascript",
    "data analysis": "data analytics",
}


def _canon(skill: str) -> str:
    s = skill.lower().strip()
    return _CANON.get(s, s)


# Filename tokens that carry no skill signal — dates, capture artefacts, filler.
_MONTHS = {
    "jan", "january", "feb", "february", "fed", "mar", "march", "apr", "april", "apirl",
    "may", "jun", "june", "jul", "july", "aug", "august", "sep", "sept", "september",
    "oct", "october", "nov", "november", "dec", "december",
}
_CERT_NOISE = {
    "badge", "screenshot", "screanshot", "snapshot", "proof", "confirmation", "confermation",
    "gmail", "page", "application", "snippet", "v1", "v2",
}
# Standalone connectors that are usually date/filler glue in a filename ("8 to 12", "from hp").
_CERT_CONNECTORS = {"to", "from", "by", "on"}


# ─── GitHub ──────────────────────────────────────────────────────────
def _github_repos(username: str, token: str | None, include_private: bool = False) -> list[dict]:
    """Non-fork repos as raw dicts, all pages. [] on any failure (network, bad user, rate limit).

    Public repos come from the public endpoint. PRIVATE repos require a token whose OWN account is
    `username` — then we use the authenticated `/user/repos` endpoint (the public one never returns
    private repos, even with auth). We verify ownership first so a token for someone else can't be
    used to claim another user's private work.
    """
    import requests  # noqa: PLC0415
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "OpportunityHunter/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    use_auth = False
    if include_private and token:
        try:
            me = requests.get("https://api.github.com/user", headers=headers, timeout=10)
            use_auth = me.status_code == 200 and \
                (me.json().get("login", "").lower() == username.lower())
        except Exception:
            use_auth = False

    repos: list[dict] = []
    try:
        page = 1
        while True:
            if use_auth:
                url, params = "https://api.github.com/user/repos", {
                    "per_page": 100, "page": page, "visibility": "all",
                    "affiliation": "owner,collaborator,organization_member", "sort": "updated"}
            else:
                url, params = f"https://api.github.com/users/{username}/repos", {
                    "per_page": 100, "page": page, "sort": "updated"}
            r = requests.get(url, params=params, headers=headers, timeout=10)
            if r.status_code != 200:
                break
            batch = r.json()
            if not isinstance(batch, list) or not batch:
                break
            repos.extend(b for b in batch if isinstance(b, dict) and not b.get("fork"))
            if len(batch) < 100:
                break
            page += 1
    except Exception:
        return repos
    return repos


def github_skills(username: str, token: str | None = None,
                  include_private: bool = False) -> dict[str, list[str]]:
    """{skill: [evidence repos]} inferred from a GitHub user's repos (public, +private with a token).

    Language and topics are trusted directly; descriptions are matched against the tech lexicon.
    Evidence is the repo name, so every skill is traceable to real code.
    """
    skills: dict[str, set[str]] = {}

    def add(skill: str, repo: str):
        s = _canon(skill)
        if s:
            skills.setdefault(s, set()).add(f"repo:{repo}")

    for repo in _github_repos(username, token, include_private):
        name = repo.get("name") or "?"
        if repo.get("language"):
            add(repo["language"], name)
        # Topics are user-assigned tags — many describe the project's DOMAIN (hackathons, students)
        # rather than a skill. Keep only those that match the tech lexicon, same as descriptions.
        for topic in repo.get("topics") or []:
            for term in _match_tech(topic.replace("-", " ")):
                add(term, name)
        for term in _match_tech(repo.get("description") or ""):
            add(term, name)
    return {k: sorted(v) for k, v in skills.items()}


# ─── certificates ────────────────────────────────────────────────────
def _clean_cert_name(filename: str) -> str:
    """A readable credential title from a messy filename — dates and capture-artefacts stripped."""
    name = re.sub(r"\.(pdf|png|jpe?g)$", "", filename, flags=re.I).replace("_", " ")
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)  # split runTogether camelCase filenames
    name = re.sub(r"-?20\d\d", " ", name)  # strip embedded years like 2026 / -2026
    kept: list[str] = []
    for tok in re.split(r"\s+", name):
        t = tok.strip(".,()").lower()
        if not t or t in _MONTHS or t in _CERT_NOISE or t in _CERT_CONNECTORS:
            continue
        if re.fullmatch(r"\d{1,4}", t):  # bare day / year numbers
            continue
        kept.append(tok.strip(".,()"))
    return re.sub(r"\s+", " ", " ".join(kept)).strip()


def certificate_skills(folder: str | Path) -> tuple[list[str], dict[str, list[str]]]:
    """(credential titles, {skill: [cert titles as evidence]}) from a folder of certificate files."""
    p = Path(folder)
    if not p.is_dir():
        return [], {}
    titles: dict[str, None] = {}   # ordered de-dup of cleaned titles
    skills: dict[str, set[str]] = {}
    for f in sorted(p.iterdir()):
        if f.suffix.lower() not in (".pdf", ".png", ".jpg", ".jpeg"):
            continue
        title = _clean_cert_name(f.name)
        if not title:
            continue
        titles.setdefault(title, None)
        for term in _match_tech(title):
            skills.setdefault(_canon(term), set()).add(f"cert:{title[:45]}")
    return list(titles), {k: sorted(v) for k, v in skills.items()}


# ─── shared: tech lexicon match ──────────────────────────────────────
def _match_tech(text: str) -> list[str]:
    """Tech/skill phrases from the lexicon that appear in `text` (word-boundary, case-insensitive)."""
    low = text.lower()
    found = []
    for term in _TECH:
        # boundaries that also respect symbols like + # . / so "c++" and "ci/cd" match cleanly
        if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", low):
            found.append(term)
    return found


# ─── assemble + verify ───────────────────────────────────────────────
def harvest(github_user: str | None = None, certs_folder: str | Path | None = None,
            token: str | None = None, include_private: bool = False,
            linkedin: str | Path | None = None) -> dict:
    """Merge every evidence source into one verified profile.

    Sources: GitHub repos (public, +private with a token), a certificates folder, and a LinkedIn
    data export (folder or .zip — never scraped). Returns {"skills": {skill: [evidence...]},
    "certifications": [titles], "positions": [work history from LinkedIn]}. Each skill's evidence
    list says exactly why we believe the candidate has it — nothing here is unsourced.
    """
    skills: dict[str, set[str]] = {}

    def merge(part: dict[str, list[str]]):
        for skill, ev in part.items():
            skills.setdefault(skill, set()).update(ev)

    certifications: list[str] = []
    positions: list[dict] = []
    if github_user:
        merge(github_skills(github_user, token, include_private))
    if certs_folder:
        certs, cert_sk = certificate_skills(certs_folder)
        certifications += certs
        merge(cert_sk)
    if linkedin:
        from .linkedin import linkedin_profile  # noqa: PLC0415
        li = linkedin_profile(linkedin)
        merge(li["skills"])
        certifications += li["certifications"]
        positions = li["positions"]
    return {
        "skills": {k: sorted(v) for k, v in sorted(skills.items())},
        "certifications": certifications,
        "positions": positions,
    }


def verify_against(harvested: dict, keywords: list[str]) -> dict[str, list[str]]:
    """For each JD keyword, the evidence (if any) that the candidate genuinely has it.

    {keyword: [evidence...]} — an empty list means "no proof found, still ask the human". A keyword
    matches a harvested skill on exact match, or containment either way for terms ≥3 chars (so "REST
    APIs" is satisfied by the harvested "api", "AWS" by "aws").
    """
    have = harvested.get("skills", {})
    out: dict[str, list[str]] = {}
    for kw in keywords:
        k = kw.lower().strip()
        ev: set[str] = set()
        for skill, evidence in have.items():
            if k == skill or (len(k) >= 3 and (k in skill or skill in k)):
                ev.update(evidence)
        out[kw] = sorted(ev)
    return out


def format_profile(harvested: dict) -> str:
    """A compact 'verified profile' block for the CLI — skills with evidence counts + certifications."""
    skills = harvested.get("skills", {})
    certs = harvested.get("certifications", [])
    lines = ["── Verified profile (auto-built from your real evidence) ──"]
    if not skills and not certs:
        lines.append("  (no evidence sources given — pass --github <user> and/or --certs <folder>)")
        return "\n".join(lines)
    if skills:
        lines.append("  Skills (with # of evidence sources):")
        # Most-evidenced first — that's your strongest, most-demonstrated skills.
        for skill, ev in sorted(skills.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            lines.append(f"    • {skill}  ×{len(ev)}  ({', '.join(ev[:3])}{'…' if len(ev) > 3 else ''})")
    if certs:
        lines.append(f"  Certifications ({len(certs)}):")
        for c in certs:
            lines.append(f"    • {c}")
    return "\n".join(lines)


if __name__ == "__main__":
    import json
    prof = harvest(github_user="Mohith535", certs_folder="E:/certificates")
    print(format_profile(prof))
    print("\nJSON skills keys:", json.dumps(sorted(prof["skills"]), ensure_ascii=False))
