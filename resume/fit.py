"""
Feed → Fit — "of everything OPHunter found, which can I actually win?"

This closes the loop in the project. One half discovers and ranks opportunities (`data/feed.json`);
the other half knows, with evidence, what you can actually do (`career_profile.json`). Until now those
two halves had never spoken. This module introduces them.

It answers the question that comes *before* "how do I apply?" — namely **"which one?"** — and it is
OPHunter's own stated organ: *discover → rank → **assess fit honestly** → emit*.

Deliberately honest, in three ways:
  * **No fabricated "87% match."** Same rule as the resume's no-fake-ATS-score: it reports a REAL
    count — how many of the skills this opportunity calls for you can *prove* — plus OPHunter's
    existing relevance score. Both are shown separately, so the ranking is explainable rather than an
    opaque number.
  * **It will say "not yet."** A tool that tells you everything is a great fit is useless. The verdict
    vocabulary is STRONG FIT / STRETCH / NOT YET, and the model is told to use the honest one.
  * **Expired deadlines are dropped**, not quietly ranked.

Cheap: the shortlist is computed deterministically (no LLM per item), and a single LLM call writes the
verdicts for the finalists.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import json
from pathlib import Path

from filters.llm_scorer import complete
from .simulate import load_feed

_INBOX_PATH = Path(__file__).resolve().parent.parent / "data" / "inbox_items.json"


def load_inbox_items() -> list[dict]:
    """Opportunities the Inbox Scout (gmail_digest.py) saved from your email — [] if none yet."""
    try:
        return json.loads(_INBOX_PATH.read_text(encoding="utf-8")).get("items", [])
    except Exception:
        return []

_VERDICTS = ("STRONG FIT", "STRETCH", "NOT YET")


def _score_of(item: dict) -> int:
    try:
        return int(item.get("ai_score", item.get("score", 0)) or 0)
    except (TypeError, ValueError):
        return 0


def _deadline_date(item: dict) -> date | None:
    """A real date from the item's deadline string, if one can be read out of it."""
    raw = str(item.get("deadline") or "")
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
    except ValueError:
        return None


def provable_overlap(item: dict, verified: dict[str, list[str]]) -> list[str]:
    """Which of the candidate's PROVEN skills this opportunity actually asks for."""
    hay = " ".join(str(item.get(k, "")) for k in ("title", "ai_summary", "description", "action_plan"))
    hay = (hay + " " + " ".join(item.get("tags") or [])).lower()
    hits = []
    for skill in verified:
        if len(skill) < 3:
            continue
        if re.search(r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])", hay):
            hits.append(skill)
    return sorted(hits)


def shortlist(feed: list[dict], profile: dict, top: int = 8, min_score: int = 1,
              include_expired: bool = False) -> list[dict]:
    """Deterministic shortlist: proven-skill overlap first, then OPHunter's own relevance score."""
    verified = {s["name"]: s.get("evidence", []) for s in profile.get("skills", [])}
    today = date.today()
    rows = []
    for it in feed:
        score = _score_of(it)
        if score < min_score:          # unscored (-1) / low-value items
            continue
        dl = _deadline_date(it)
        expired = bool(dl and dl < today)
        if expired and not include_expired:
            continue
        proven = provable_overlap(it, verified)
        rows.append({"item": it, "score": score, "proven": proven, "deadline": dl,
                     "rank": len(proven) * 2 + score})
    rows.sort(key=lambda r: (-r["rank"], -r["score"]))
    return rows[:top]


_VERDICT_PROMPT = """You are an honest career advisor. For each opportunity below, judge how well this
candidate ACTUALLY fits, using ONLY their verified profile.

RULES:
- No percentages, no scores, no flattery. A tool that says everything is a great fit is useless.
- Use exactly one verdict per opportunity: STRONG FIT, STRETCH, or NOT YET. Use NOT YET when it's true.
- Name the single biggest gap plainly. If they're missing a hard requirement, say so.
- Judge only against the verified profile — do not assume unlisted skills.

Output ONE line per opportunity, numbered to match, in exactly this format and nothing else:
<number>. <VERDICT> — <one sentence: why, and the biggest gap>

--- VERIFIED PROFILE ---
{profile}

--- OPPORTUNITIES ---
{opps}
"""


def add_verdicts(rows: list[dict], profile: dict) -> list[dict]:
    """One LLM call for the finalists; rows are returned unchanged if the LLM is unavailable."""
    if not rows:
        return rows
    skills = ", ".join(f"{s['name']} (x{s['evidenceCount']})" for s in profile.get("skills", [])[:20])
    projects = "; ".join(f"{p['name']}: {p.get('description') or 'no description'}"
                         for p in profile.get("projects", [])[:8])
    declared = profile.get("x_declared", {})
    prof_block = (f"Background: {declared.get('identity','')}\nProven skills: {skills}\n"
                  f"Real projects: {projects}")
    opps = "\n".join(
        f"{i}. {r['item'].get('title','')[:90]} | tags: {', '.join(r['item'].get('tags') or [])[:60]}"
        f" | summary: {str(r['item'].get('ai_summary',''))[:160]}"
        for i, r in enumerate(rows, 1))

    out = complete(_VERDICT_PROMPT.format(profile=prof_block, opps=opps),
                   max_tokens=700, temperature=0.3)
    if not out:
        return rows
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)[.)]\s*(.+)", line.strip())
        if not m:
            continue
        idx = int(m.group(1)) - 1
        if not (0 <= idx < len(rows)):
            continue
        text = m.group(2).strip()
        verdict = next((v for v in _VERDICTS if text.upper().startswith(v)), "")
        rows[idx]["verdict"] = verdict or ""
        rows[idx]["reason"] = text[len(verdict):].lstrip(" —-:") if verdict else text
    return rows


_BADGE = {"STRONG FIT": "🟢", "STRETCH": "🟡", "NOT YET": "🔴"}


def format_fit(rows: list[dict], profile: dict, feed_size: int) -> str:
    n_skills = len(profile.get("skills", []))
    lines = ["=" * 66, "FIT MATCH — which of your opportunities can you actually win?", "=" * 66,
             f"{feed_size} opportunities in your feed · {n_skills} verified skills to match against",
             ""]
    if not rows:
        lines.append("Nothing qualified — the feed may be stale or every deadline has passed.\n"
                     "Run a fresh hunt (python main.py --now), or pass --include-expired to look back.")
        return "\n".join(lines)

    for i, r in enumerate(rows, 1):
        it = r["item"]
        badge = _BADGE.get(r.get("verdict", ""), "•")
        head = f"{i}. {badge} {r.get('verdict') or 'shortlisted'} — {it.get('title','')[:78]}"
        lines.append(head)
        dl = r["deadline"].isoformat() if r["deadline"] else (it.get("deadline") or "rolling")
        lines.append(f"   deadline {dl} · relevance {r['score']}/10 · source {it.get('source','?')}")
        if r["proven"]:
            lines.append(f"   ✅ you can PROVE {len(r['proven'])} skill(s) it asks for: "
                         f"{', '.join(r['proven'][:8])}")
        else:
            lines.append("   ⚠️ no skill overlap it names explicitly — read it before spending time")
        if r.get("reason"):
            lines.append(f"   → {r['reason']}")
        if it.get("url"):
            lines.append(f"   {it['url']}")
        lines.append("")

    strong = sum(1 for r in rows if r.get("verdict") == "STRONG FIT")
    lines += ["─" * 66,
              f"{strong} strong fit(s) in this shortlist. Ranking = proven-skill overlap first, then "
              "OPHunter's own relevance score — both shown above, no invented match percentage.",
              "Next: `python -m resume.generate --jd <the posting>` then `python -m resume.cover`."]
    return "\n".join(lines)


def main() -> int:
    import argparse
    from .profile import load_profile_json

    ap = argparse.ArgumentParser(
        description="Feed → Fit — rank your real opportunities against your verified profile.")
    ap.add_argument("--top", type=int, default=8, help="how many to shortlist (default 8)")
    ap.add_argument("--min-score", type=int, default=1, help="ignore items below this relevance")
    ap.add_argument("--include-expired", action="store_true", help="also consider passed deadlines")
    ap.add_argument("--no-verdict", action="store_true", help="skip the LLM verdicts (offline/fast)")
    ap.add_argument("--no-inbox", action="store_true",
                    help="exclude opportunities saved from your Gmail by the Inbox Scout")
    args = ap.parse_args()

    profile = load_profile_json()
    if not profile:
        print("No career_profile.json yet — build it first:\n"
              "   python -m resume.profile --github <you> --include-private --certs <folder>")
        return 1

    feed = load_feed()
    inbox = [] if args.no_inbox else load_inbox_items()
    feed = feed + inbox  # inbox opportunities compete in the same honest shortlist
    if not feed:
        print("No opportunities found (data/feed.json, data/history.json, or data/inbox_items.json). "
              "Run a hunt (python main.py --now) or the Inbox Scout (python gmail_digest.py).")
        return 1
    if inbox:
        print(f"(including {len(inbox)} opportunit(y/ies) from your inbox)")

    rows = shortlist(feed, profile, args.top, args.min_score, args.include_expired)
    if not args.no_verdict:
        rows = add_verdicts(rows, profile)
    print(format_fit(rows, profile, len(feed)))

    # Inbox opportunities came directly TO you — never let them get buried under 100 scraped items
    # just because their email snippet is short. Always surface any that didn't make the shortlist.
    if inbox:
        shown = {r["item"].get("key") for r in rows}
        missed = sorted((it for it in inbox if it.get("key") not in shown),
                        key=lambda x: -(x.get("ai_score") or 0))
        if missed:
            print("\n📥 ALSO IN YOUR INBOX (came straight to you — don't miss these):")
            for it in missed:
                dl = it.get("deadline") or "—"
                print(f"   [{it.get('ai_score', '?')}/10] {str(it.get('title', ''))[:72]}  (deadline {dl})")
                if it.get("url"):
                    print(f"          {it['url']}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
