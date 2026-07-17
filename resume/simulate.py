"""
Career Simulation (Slice 4) — an honest, grounded answer to "how do I get from where I ACTUALLY am
to <target> in N months?"

This extends the shipped `/coach` idea, but with three things that make it trustworthy instead of
motivational fluff:

  1. It starts from your VERIFIED profile (Slice 3's harvest — real repos + certs, with evidence),
     so "where you are now" is never inflated or invented.
  2. It is grounded in real career-development frameworks, not vibes:
       * IDP shape        — current state → target → gap → time-boxed actions.
       * 70-20-10         — ~70% learning-by-building, ~20% from others (OSS/community), ~10% formal.
       * SMART milestones — every phase has a specific, measurable, time-bound outcome.
       * Work backwards   — from the target's real requirements to today.
  3. It cites REAL opportunities already in your OPHunter feed (data/feed.json) at the phase where
     they fit — so the plan connects to things you can actually apply to. This respects the project's
     one-organ boundary: it consumes the discover→rank output; it does not become a planner. Execution
     lives in TaskFlow, memory in Nova.

Honesty is enforced in the prompt: no guarantees, controllable vs uncontrollable factors named
plainly, and a thin profile is called thin. Free (reuses filters.llm_scorer.complete). Output is a
simulated PATH the human decides to act on — nothing is applied or scheduled automatically.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from filters.llm_scorer import complete
from .harvest import harvest

_BASE = Path(__file__).resolve().parent.parent
_STOP = {"the", "and", "for", "with", "role", "job", "intern", "internship", "position",
         "engineer", "developer", "at", "in", "of", "a", "an", "to", "as", "want", "get"}


# ─── real opportunities from your own feed ───────────────────────────
def load_feed(base_dir: Path = _BASE) -> list[dict]:
    """Items from data/feed.json (flat) or data/history.json (runs). [] if neither is present."""
    for name, pick in (("feed.json", lambda d: d.get("items", [])),
                       ("history.json", lambda d: (d.get("runs") or [{}])[-1].get("items", []))):
        f = base_dir / "data" / name
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            items = pick(data) if isinstance(data, dict) else data
            if items:
                return items
        except Exception:
            continue
    return []


def relevant_opportunities(feed: list[dict], target: str, limit: int = 10) -> list[dict]:
    """Feed items most relevant to the target — real anchors for the plan (title, deadline, score)."""
    target_tokens = {t for t in re.findall(r"[a-z0-9+#]+", target.lower())
                     if len(t) >= 3 and t not in _STOP}

    def overlap(item: dict) -> int:
        hay = (str(item.get("title", "")) + " " + " ".join(item.get("tags") or [])
               + " " + str(item.get("description", ""))).lower()
        return sum(1 for tok in target_tokens if tok in hay)

    scored = [(overlap(it), it.get("ai_score", it.get("score", 0)) or 0, it) for it in feed]
    # Prefer target-relevant items; fall back to the highest-value items so there's always context.
    relevant = sorted([s for s in scored if s[0] > 0], key=lambda s: (-s[0], -s[1]))
    if len(relevant) < limit:
        extra = sorted([s for s in scored if s[0] == 0], key=lambda s: -s[1])
        relevant += extra[: limit - len(relevant)]
    return [it for _, _, it in relevant[:limit]]


# ─── formatting for the prompt ───────────────────────────────────────
def _profile_block(harvested: dict) -> str:
    skills = harvested.get("skills", {})
    if not skills:
        return "(no verified skills found — pass --github and/or --certs, or the profile is genuinely thin)"
    lines = [f"- {sk} (×{len(ev)} evidence)"
             for sk, ev in sorted(skills.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
    certs = harvested.get("certifications", [])
    if certs:
        lines.append(f"- certifications on file: {len(certs)} (e.g. {', '.join(certs[:5])})")
    return "\n".join(lines)


def _feed_block(items: list[dict]) -> str:
    if not items:
        return "(no live opportunities available right now)"
    out = []
    for it in items:
        dl = it.get("deadline") or "rolling / none"
        score = it.get("ai_score", it.get("score", "?"))
        out.append(f"- {str(it.get('title',''))[:80]} | deadline: {dl} | relevance: {score}")
    return "\n".join(out)


_SIM_PROMPT = """You are a rigorous, honest career strategist for a computer-science student. Build a
realistic {months}-month plan to reach the TARGET, grounded ONLY in the candidate's VERIFIED profile.
This is a simulation of a realistic path — NOT a promise.

HONESTY RULES (non-negotiable):
- Describe "where they are now" using ONLY the verified skills/evidence below. Do NOT inflate, assume,
  or invent current experience. If the profile is thin for this target, say so plainly.
- Give an HONEST read of the odds. No guarantees. Separate what they CONTROL (skills they build,
  projects they ship, applications they send) from what they DON'T (competition, timing, luck). Use
  "realistic", "a stretch", or "a long shot" truthfully.
- Every action must be concrete and doable by a student with no budget.

METHOD (use these real frameworks):
- Work BACKWARDS from the target: what does it actually require, and what is the true gap vs the
  verified profile?
- 70-20-10: about 70% learning-by-building (ship real projects that mirror the target's actual work),
  ~20% learning from others (open source, community, mentorship), ~10% formal (a course/cert ONLY if
  it fills a real gap — they already hold many certs, so favour BUILDING over more courses).
- SMART milestones: each phase has a specific, measurable, time-bound outcome.
- Where a REAL opportunity from the feed fits a phase, name it and its deadline so the plan connects
  to things they can actually apply to.

Output plain text in EXACTLY this structure:

WHERE YOU ARE (verified):
<2-4 lines, only from the profile>

THE TARGET & WHAT IT REALLY REQUIRES:
<the honest bar for this target>

THE GAP:
<✅ already have ... / ⚠️ need to build ... — the real distance>

HONEST READ:
<realistic? a stretch? what is and isn't in your control>

THE {months}-MONTH PLAN (backward-planned):
<Phase blocks covering the whole horizon. Each: months covered, what to build/learn, a measurable
milestone, and [fit: <real feed opportunity + deadline>] where one applies.>

CHECKPOINTS:
<2-3 measurable "you're on track if..." markers>

--- VERIFIED PROFILE ---
{profile}

--- TARGET ---
{target}

--- REAL OPPORTUNITIES CURRENTLY IN YOUR FEED ---
{feed}
"""


def simulate(target: str, harvested: dict, feed_items: list[dict], months: int = 6) -> str:
    """The honest, grounded {months}-month simulation toward `target`. '' if the LLM is unavailable."""
    prompt = _SIM_PROMPT.format(
        months=months, target=target.strip(),
        profile=_profile_block(harvested), feed=_feed_block(feed_items))
    return complete(prompt, max_tokens=1200, temperature=0.5)


# ─── CLI ─────────────────────────────────────────────────────────────
def _token() -> str | None:
    tok = os.environ.get("GITHUB_TOKEN")
    try:
        import config  # noqa: PLC0415
        tok = getattr(config, "GITHUB_TOKEN", None) or tok
    except Exception:
        pass
    return tok


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Career Simulation — an honest, grounded path from your VERIFIED profile to a target.")
    ap.add_argument("--target", required=True,
                    help='the goal, e.g. "Machine Learning Engineer intern" or "Google STEP 2027"')
    ap.add_argument("--months", type=int, default=6, help="planning horizon in months (default 6)")
    ap.add_argument("--github", default="", help="your GitHub username (verifies skills from repos)")
    ap.add_argument("--certs", default="", help="path to your certificates folder (verifies skills)")
    args = ap.parse_args()

    harvested = harvest(args.github or None, args.certs or None, token=_token())
    feed_items = relevant_opportunities(load_feed(), args.target)

    out = simulate(args.target, harvested, feed_items, args.months)
    print("=" * 64)
    print(f"CAREER SIMULATION — {args.target}  ({args.months} months)")
    print("grounded in your VERIFIED profile — a realistic path, not a promise")
    print("=" * 64)
    print(out or "(simulation unavailable — set an LLM key in .env)")
    print("\n" + "-" * 64)
    print("This is a simulated path from your real evidence. You decide what to act on;")
    print("milestones can go to TaskFlow on your say-so — nothing is scheduled automatically. 🧭")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
