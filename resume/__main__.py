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
    ap.add_argument("--include-private", action="store_true",
                    help="also read your PRIVATE repos (needs GITHUB_TOKEN with 'repo' scope, your own)")
    ap.add_argument("--certs", default="",
                    help="path to your certificates folder — auto-verifies skills from credentials")
    ap.add_argument("--linkedin", default="",
                    help="path to your LinkedIn data-export folder or .zip (Settings > Get a copy of "
                         "your data) — verifies skills + work history, no scraping")
    ap.add_argument("--profile", action="store_true",
                    help="read your cached career_profile.json (build via `python -m resume.profile`) "
                         "as the single source of truth — includes your real projects for tailoring")
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

    # Verified skill set — from the cached SSOT (--profile) or a live harvest (--github/--certs/--linkedin).
    verified_missing: list[str] = []
    evidence_ctx = ""
    harvested = None
    profile_obj = None

    if args.profile:
        from .profile import load_profile_json, to_harvest_shape
        profile_obj = load_profile_json()
        if profile_obj:
            harvested = to_harvest_shape(profile_obj)
            print("\n[reading your cached career_profile.json — single source of truth]")
        else:
            print("\n[--profile given but no cached profile found — build it first:\n"
                  "   python -m resume.profile --github <you> --include-private --certs <folder>]")

    if harvested is None and (args.github or args.certs or args.linkedin):
        from .harvest import harvest
        token = os.environ.get("GITHUB_TOKEN")
        try:
            import config  # project root; optional (raises the unauthenticated rate limit if present)
            token = getattr(config, "GITHUB_TOKEN", None) or token
        except Exception:
            pass
        harvested = harvest(args.github or None, args.certs or None, token=token,
                            include_private=args.include_private, linkedin=args.linkedin or None)

    if harvested is not None:
        from .harvest import format_profile, verify_against
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
        # Real projects + work history for honest tailoring grounding — only from the full profile.
        if profile_obj:
            from .profile import evidence_context
            evidence_ctx = evidence_context(profile_obj, result["keywords"])

    if args.tailor:
        from .tailor import tailor
        # Truthful skill set = JD keywords in the resume + evidenced skills + anything you confirmed.
        confirmed = (list(result["present"])
                     + verified_missing
                     + [s.strip() for s in args.have.split(",") if s.strip()])
        draft = tailor(result["text"], jd_text, confirmed, evidence_context=evidence_ctx)
        print("\n" + "=" * 60)
        print("TAILORED DRAFT — review + edit; nothing here is applied or submitted")
        print("=" * 60)
        print(draft or "(tailoring unavailable — set an LLM key in .env)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
