"""CLI for Resume Intelligence.

    python -m resume --resume path/to/resume.pdf --jd path/to/jd.txt
    python -m resume --resume resume.docx --jd "paste the job description text here"

Reads your resume + a job description, prints an honest ATS parse check and a real keyword-coverage
report (never a fake score, never invented experience).
"""

import argparse
import sys
from pathlib import Path

from .analyzer import analyze, format_report


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Resume Intelligence — honest resume vs job-description analysis.")
    ap.add_argument("--resume", required=True, help="path to your resume (.pdf / .docx / .txt)")
    ap.add_argument("--jd", required=True,
                    help="path to a job-description .txt file, OR the JD text inline")
    args = ap.parse_args()

    jd_path = Path(args.jd)
    jd_text = (jd_path.read_text(encoding="utf-8", errors="ignore")
               if jd_path.exists() else args.jd)

    try:
        result = analyze(args.resume, jd_text)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"Error: {e}")
        return 1

    print(format_report(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
