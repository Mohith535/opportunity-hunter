"""
Resume ingestion — your existing résumé is the richest evidence source you own.

This module exists because of a real failure. The generator was producing thin, generic resumes while
the user's own résumé was far better — and the reason was not the prompt, it was the DATA. GitHub repo
metadata and certificate filenames simply cannot see:

    education (SRMIST, school, ranks) · selections and programs (GSSoC, GCI World, Deloitte camp) ·
    the real depth of a project ("3200+ lines across 8 versions, grounded in published behavioural
    research") · leadership · contact details

All of that lives in a résumé the user already wrote. Ignoring it was the bug. The best open-source
tools in this space work the same way — generate from an EXISTING résumé plus the job description.

So: this reads a résumé (.pdf/.docx/.txt), extracts it into JSON-Resume-shaped structure, and merges
it into `career_profile.json` as another source, alongside GitHub / certificates / LinkedIn.

Honesty note — and it matters: résumé content is **self-asserted**, not externally verified like a
repo or a certificate. It is therefore tagged `resume:` so the provenance stays visible, and the
evidence audit treats resume-only skills as weaker than repo-backed ones. Extraction copies the
résumé's own wording; it never invents, embellishes, or "improves" a claim.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from filters.llm_scorer import complete

_INGEST_PROMPT = """Extract structured data from this résumé EXACTLY as written. Do NOT invent,
embellish, summarise away detail, or add anything that is not present in the text.

Return ONLY valid JSON — no markdown fences, no commentary — in exactly this shape:
{{
  "basics": {{"name": "", "email": "", "phone": "", "location": "", "linkedin": "", "github": "",
              "portfolio": "", "summary": ""}},
  "education": [{{"institution": "", "studyType": "", "area": "", "startDate": "", "endDate": "",
                  "note": ""}}],
  "work": [{{"name": "", "position": "", "startDate": "", "endDate": "", "highlights": [""]}}],
  "projects": [{{"name": "", "description": "", "keywords": [""], "date": "", "highlights": [""]}}],
  "awards": [{{"title": "", "awarder": "", "date": "", "summary": ""}}],
  "certificates": [{{"name": "", "issuer": "", "date": ""}}],
  "skills": [""]
}}

RULES:
- Copy the résumé's OWN wording for highlights/bullets. Keep every specific: numbers, versions, line
  counts, tool names, research references. Those specifics are the whole value — do not generalise them.
- "awards" means selections, programs, competitions, honours and leadership (open-source programs,
  university labs, corporate challenges, hackathon roles, academic rank).
- "projects.highlights" = the bullet points under that project, verbatim.
- Omit anything you cannot find — use "" or []. Never fabricate a date, metric, or employer.

RÉSUMÉ TEXT:
{text}
"""


def _parse_json(raw: str) -> dict:
    """Tolerant JSON extraction — models like to wrap output in prose or fences."""
    if not raw:
        return {}
    txt = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    start, end = txt.find("{"), txt.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(txt[start:end + 1])
    except json.JSONDecodeError:
        # Second chance: strip trailing commas, a common model slip.
        try:
            return json.loads(re.sub(r",(\s*[}\]])", r"\1", txt[start:end + 1]))
        except json.JSONDecodeError:
            return {}


# PDF fonts often map ligatures and symbols to characters that don't survive text extraction.
# Expanding the real ligatures is safe and fixes the common damage ("certiﬁcate", "diﬀerent").
_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
              "–": "-", "—": "—", "‘": "'", "’": "'", "“": '"',
              "”": '"', " ": " ", "�": " "}


def normalize_pdf_text(text: str) -> tuple[str, list[str]]:
    """(cleaned text, lines that still look glyph-damaged).

    A resume PDF can encode an arrow or symbol as a glyph with no unicode mapping — extraction then
    yields something like "blueﬁamberﬁred" for "blue→amber→red". Expansion can't recover the original
    symbol, so those lines are RETURNED FOR REVIEW rather than silently shipped into a resume.
    """
    suspicious = [ln.strip() for ln in text.splitlines()
                  if re.search(r"[a-z]{3}[ﬀ-ﬄ][a-z]{3}", ln)]
    for bad, good in _LIGATURES.items():
        text = text.replace(bad, good)
    return text, suspicious[:5]


def ingest_resume(path: str | Path) -> dict:
    """Structured content extracted from an existing résumé. {} if unreadable or the LLM is down."""
    from .analyzer import extract_text  # noqa: PLC0415
    text, suspicious = normalize_pdf_text(extract_text(path))
    if not text.strip():
        return {}
    data = _parse_json(complete(_INGEST_PROMPT.format(text=text[:12000]),
                                max_tokens=3000, temperature=0.1))
    if not isinstance(data, dict):
        return {}
    data["_source_file"] = Path(path).name
    if suspicious:
        data["_review"] = suspicious
    return data


def summarize(data: dict) -> str:
    """One-line-per-section summary of what was pulled out — so the user can sanity-check it."""
    if not data:
        return "Nothing extracted (unreadable file, or no LLM available)."
    b = data.get("basics", {}) or {}
    parts = [
        f"name: {b.get('name') or '—'}",
        f"contact: {', '.join(x for x in [b.get('email'), b.get('phone'), b.get('linkedin'), b.get('portfolio')] if x) or '—'}",
        f"education: {len(data.get('education') or [])}",
        f"work: {len(data.get('work') or [])}",
        f"projects: {len(data.get('projects') or [])} "
        f"({sum(len(p.get('highlights') or []) for p in data.get('projects') or [])} bullets)",
        f"awards/programs: {len(data.get('awards') or [])}",
        f"certificates: {len(data.get('certificates') or [])}",
        f"skills: {len(data.get('skills') or [])}",
    ]
    out = "\n".join(f"  • {p}" for p in parts)
    if data.get("_review"):
        out += ("\n\n  ⚠️  These lines look glyph-damaged by PDF extraction — a symbol your PDF font\n"
                "      couldn't encode (e.g. an arrow). Fix them by hand in the generated resume:")
        out += "".join(f"\n        · {ln[:96]}" for ln in data["_review"])
    return out


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Preview what would be extracted from an existing résumé.")
    ap.add_argument("--resume", required=True, help="path to your résumé (.pdf / .docx / .txt)")
    ap.add_argument("--json", action="store_true", help="dump the full extracted JSON")
    args = ap.parse_args()

    try:
        data = ingest_resume(args.resume)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"Error: {e}")
        return 1

    print("=" * 64)
    print(f"RESUME INGEST — {Path(args.resume).name}")
    print("=" * 64)
    print(summarize(data))
    if args.json:
        print("\n" + json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print("\nAdd it to your profile with:\n"
              f'   python -m resume.profile --github <you> --include-private --certs <folder> '
              f'--resume "{args.resume}"')
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
