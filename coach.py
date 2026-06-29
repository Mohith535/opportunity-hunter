"""
Gap-Analysis Coach (Phase C+) — bridges you to the elite opportunities.

Looks at the high-value opportunities you're actually seeing and your profile, then
does an honest gap analysis: what do these repeatedly require that you don't have
yet, and what 2-3 concrete things should you build in the next few weeks to qualify.

This is where the agent stops being a feed and becomes a career brain — every
opportunity ladders back to the long-term goal. On-demand via /coach. Grounded in
the real feed + profile via the same provider chain.
"""

import config
from filters import llm_scorer, policy
from user_profile import load_profile

_PROMPT = """You are {name}'s career coach — a senior mentor who is direct and honest,
not a cheerleader. Look at the ELITE opportunities he's currently seeing (below) and
his profile, and coach him:

1. GAP: What do these high-value opportunities repeatedly REQUIRE that he most likely
   doesn't have yet? (e.g. a published paper, real open-source contributions, a
   standout portfolio project, a specific skill, competition results.) Be specific
   and honest — name the actual gap.
2. PLAN: Give 2-3 CONCRETE things to build or do over the next 4-6 weeks to close that
   gap, each tied to what these opportunities actually want. Real actions, not "study
   more". Lead with the highest-leverage one.

Ground everything in his REAL profile and these specific opportunities. No clichés,
no fluff, no invented facts. Speak plainly, like a mentor who's read the research.

{name}'s long-term goal: {goal}

{name}'s profile:
{profile}

Elite opportunities he's seeing right now:
{context}

Coaching (GAP, then PLAN):"""

MIN_ITEMS = 3


def analyze(history_items: dict, profile=None) -> str:
    """Gap analysis + concrete plan from the elite items in the feed. '' if the LLM
    is unavailable; a gentle note if there isn't enough signal yet."""
    profile = profile or load_profile()
    elite = sorted((it for it in history_items.values()
                    if policy.effective_score(it) >= config.HIGH_SCORE),
                   key=policy.effective_score, reverse=True)[:15]
    if len(elite) < MIN_ITEMS:
        return ("🧭 Not enough high-value opportunities in your feed yet to coach on. "
                "Let the hunter run a few days, then ask me again.")
    context = "\n".join(f"- {it.title[:74]} ({it.source})" for it in elite)
    prompt = _PROMPT.format(
        name=profile.name, goal=profile.long_term_goal,
        profile=profile.to_prompt_block()[:800], context=context,
    )
    return llm_scorer.complete(prompt, max_tokens=650, temperature=0.5)


if __name__ == "__main__":
    from models import Opportunity

    def mk(t, s, src):
        o = Opportunity(t, "https://x/" + t, src, "d"); o.ai_score = s
        return o

    hist = {x.dedup_key(): x for x in [
        mk("OpenAI Residency", 9, "programs"),
        mk("Google Summer of Code", 9, "programs"),
        mk("Anthropic Research Programs", 9, "programs"),
        mk("Outreachy Internship", 8, "programs"),
        mk("NeurIPS Student Research", 8, "programs"),
    ]}
    print(analyze(hist) or "(no coaching — LLM unavailable)")
