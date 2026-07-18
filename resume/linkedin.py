"""
LinkedIn import (Slice 3b) — read EVERYTHING LinkedIn has on you, the legitimate way.

There is deliberately NO scraping and NO login automation here. LinkedIn's User Agreement forbids
automated access, and it gets accounts restricted/banned — not worth it, and it's on this project's
own refuse-list. Instead we read LinkedIn's OFFICIAL data export, which you own and can download for
free:

    LinkedIn → Settings & Privacy → Data Privacy → "Get a copy of your data" → request the archive.

That archive (a .zip, or the folder you extract it to) contains the full picture as CSVs:
    Skills.csv         — your declared skills
    Positions.csv      — your real work history (company, title, dates, description)  ← the gold
    Certifications.csv — your certificates
    Projects.csv       — your projects
    Profile.csv        — headline + summary

This module parses those into the same evidence-tagged skill set the rest of harvest uses (evidence
label `linkedin:...`), plus your structured work history for later resume tailoring. Same honesty rule
as everywhere else: it only reports what's actually in YOUR export — it invents nothing.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

from .harvest import _canon, _match_tech

# Only these CSVs carry signal we use; a LinkedIn export contains many more we ignore.
_WANTED = {"skills", "positions", "certifications", "projects", "profile", "education"}


def _read_csvs(export_path: str | Path) -> dict[str, list[dict]]:
    """{lower_basename: [row dicts]} from a LinkedIn export given as a folder or a .zip."""
    p = Path(export_path)
    out: dict[str, list[dict]] = {}

    def take(filename: str, text: str):
        stem = Path(filename).stem.lower().replace(" ", "")
        if stem in _WANTED:
            out[stem] = list(csv.DictReader(io.StringIO(text)))

    if p.is_dir():
        for f in p.rglob("*.csv"):
            try:
                take(f.name, f.read_text(encoding="utf-8-sig", errors="ignore"))
            except Exception:
                continue
    elif p.suffix.lower() == ".zip" and p.exists():
        try:
            with zipfile.ZipFile(p) as z:
                for name in z.namelist():
                    if name.lower().endswith(".csv"):
                        try:
                            take(name, z.read(name).decode("utf-8-sig", errors="ignore"))
                        except Exception:
                            continue
        except Exception:
            pass
    return out


def _col(row: dict, *names: str) -> str:
    """Value of the first matching column (case/space-insensitive) — LinkedIn header names vary."""
    norm = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
    for n in names:
        if n.lower() in norm:
            return norm[n.lower()]
    return ""


def linkedin_profile(export_path: str | Path) -> dict:
    """Skills + work history + certs + headline/summary from a LinkedIn data export.

    Returns {"skills": {skill: [evidence]}, "positions": [...], "certifications": [...],
    "headline": str, "summary": str}. Empty/degraded gracefully if files are missing.
    """
    csvs = _read_csvs(export_path)
    skills: dict[str, set[str]] = {}

    def add(skill: str, evidence: str):
        s = _canon(skill)
        if s:
            skills.setdefault(s, set()).add(evidence)

    # Declared skills (self-reported — evidence label makes that transparent).
    for row in csvs.get("skills", []):
        name = _col(row, "Name")
        if name:
            add(name, "linkedin:Skills")

    # Real work history — the most valuable part; also mine tech terms from title + description.
    positions: list[dict] = []
    for row in csvs.get("positions", []):
        title = _col(row, "Title")
        company = _col(row, "Company Name", "Company")
        desc = _col(row, "Description")
        if not (title or company):
            continue
        positions.append({
            "title": title, "company": company, "description": desc,
            "start": _col(row, "Started On"), "end": _col(row, "Finished On"),
        })
        for term in _match_tech(f"{title} {desc}"):
            add(term, f"linkedin:{(company or title)[:40]}")

    # Certificates listed on LinkedIn.
    certifications: list[str] = []
    for row in csvs.get("certifications", []):
        name = _col(row, "Name")
        if not name:
            continue
        authority = _col(row, "Authority")
        certifications.append(f"{name} — {authority}" if authority else name)
        for term in _match_tech(name):
            add(term, f"cert:{name[:40]}")

    # Projects.
    for row in csvs.get("projects", []):
        for term in _match_tech(f"{_col(row, 'Title')} {_col(row, 'Description')}"):
            add(term, "linkedin:Projects")

    # Education.
    education: list[dict] = []
    for row in csvs.get("education", []):
        school = _col(row, "School Name", "School")
        degree = _col(row, "Degree Name", "Degree")
        if school or degree:
            education.append({
                "institution": school, "studyType": degree,
                "startDate": _col(row, "Start Date"), "endDate": _col(row, "End Date"),
            })

    profile_rows = csvs.get("profile", [])
    head = profile_rows[0] if profile_rows else {}
    return {
        "skills": {k: sorted(v) for k, v in skills.items()},
        "positions": positions,
        "certifications": certifications,
        "education": education,
        "headline": _col(head, "Headline"),
        "summary": _col(head, "Summary"),
    }


if __name__ == "__main__":
    import json
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "."
    prof = linkedin_profile(path)
    print("skills:", json.dumps(sorted(prof["skills"]), ensure_ascii=False))
    print("positions:", len(prof["positions"]), "| certifications:", len(prof["certifications"]))
    print("headline:", prof["headline"])
