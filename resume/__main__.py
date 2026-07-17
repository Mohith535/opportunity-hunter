"""CLI for Resume Intelligence.

    python -m resume --resume path/to/resume.pdf --jd path/to/jd.txt
    python -m resume --resume resume.docx --jd "paste the job description text here"

Reads your resume + a job description, prints an honest ATS parse check and a real keyword-coverage
report (never a fake score, never invented experience).
"""

import argparse
import os
import sys
from pathlib import Path

from .analyzer import analyze, format_report


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Resume Intelligence — honest resume vs job-description analysis.")
    ap.add_argument("--resume", required=True, help="path to your resume (.pdf / .docx / .txt)")
    ap.add_argument("--jd", required=True,
                    help="path to a job-description .txt file, OR the JD text inline")
    ap.add_argument("--have", default="",
                    help="comma-separated skills you've CONFIRMED you genuinely have (from the gap "
                         "list) — woven into the tailored draft, truthfully")
    ap.add_argument("--github", default="",
                    help="your GitHub username — auto-verifies skills from your real public repos")
    ap.add_argument("--certs", default="",
                    help="path to your certificates folder — auto-verifies skills from credentials")
    ap.add_argument("--tailor", action="store_true",
                    help="also produce a tailored DRAFT (Summary / Skills / rewritten Experience)")
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

    # Slice 3: auto-build a VERIFIED skill set from real evidence, and auto-check the gap list.
    verified_missing: list[str] = []
    if args.github or args.certs:
        from .harvest import format_profile, harvest, verify_against
        token = os.environ.get("GITHUB_TOKEN")
        try:
            import config  # project root; optional (raises the unauthenticated rate limit if present)
            token = getattr(config, "GITHUB_TOKEN", None) or token
        except Exception:
            pass
        harvested = harvest(args.github or None, args.certs or None, token=token)
        print("\n" + format_profile(harvested))

        checked = verify_against(harvested, result["missing"])
        verified_missing = [kw for kw, ev in checked.items() if ev]
        if result["missing"]:
            print("\n── Gap list, auto-checked against your real evidence ──")
            for kw in result["missing"]:
                ev = checked.get(kw) or []
                if ev:
                    print(f"  ✅ {kw} — evidence found ({', '.join(ev[:2])}) → safe to add, in your own words")
                else:
                    print(f"  ⚠️ {kw} — no evidence found → only add if it's genuinely true")

    if args.tailor:
        from .tailor import tailor
        # Truthful skill set = JD keywords in the resume + evidenced skills + anything you confirmed.
        confirmed = (list(result["present"])
                     + verified_missing
                     + [s.strip() for s in args.have.split(",") if s.strip()])
        draft = tailor(result["text"], jd_text, confirmed)
        print("\n" + "=" * 60)
        print("TAILORED DRAFT — review + edit; nothing here is applied or submitted")
        print("=" * 60)
        print(draft or "(tailoring unavailable — set an LLM key in .env)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
