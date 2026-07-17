"""Resume Intelligence (Slice 1) — honest resume ↔ job-description analysis.

Free, human-in-the-loop, and deliberately honest: no fake ATS score, no invented experience,
no auto-submit. See analyzer.py. CLI: `python -m resume --resume <file> --jd <file-or-text>`.
"""
from .analyzer import (
    analyze,
    ats_format_check,
    extract_jd_keywords,
    extract_text,
    format_report,
    keyword_coverage,
)
from .harvest import format_profile, harvest, verify_against
from .tailor import tailor

__all__ = [
    "analyze", "format_report", "extract_text",
    "ats_format_check", "extract_jd_keywords", "keyword_coverage",
    "tailor",
    "harvest", "verify_against", "format_profile",
]
