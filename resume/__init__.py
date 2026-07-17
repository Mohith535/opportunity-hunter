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

# NOTE: `simulate` is intentionally NOT imported here. It's its own CLI entry point
# (`python -m resume.simulate`); eager-importing it in the package __init__ makes that command emit a
# spurious RuntimeWarning (submodule already in sys.modules). Import it directly where needed:
#   from resume.simulate import simulate

__all__ = [
    "analyze", "format_report", "extract_text",
    "ats_format_check", "extract_jd_keywords", "keyword_coverage",
    "tailor",
    "harvest", "verify_against", "format_profile",
]
