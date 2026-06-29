"""
Draft Generator (Phase C+) — kills the blank-page friction.

Tap ✍️ Draft on an opportunity and the LLM writes a short, tailored "why me"
application paragraph using Mohith's real profile — ready to adapt and send. Free
text, via the same Groq->Cerebras->OpenRouter chain the scorer uses.
"""

from filters import llm_scorer
from user_profile import load_profile

_PROMPT = """You are helping {name} write a short application note for an opportunity.

OPPORTUNITY:
{title}
{description}

{name}'s profile:
{profile}

Write a first-person application paragraph (120-160 words) that {name} can adapt and send.
Rules:
- Specific to THIS opportunity (reference what it actually is) — not generic.
- Lead with genuine fit: why it matches his goals and what he concretely brings
  (e.g. building TaskFlow and Nova, AI agents, the strengths in his profile).
- Confident but honest. No clichés like "I am passionate", no invented achievements.
- End with one clear line of intent.
Return ONLY the paragraph — no preamble, no greeting, no sign-off block.
"""


def generate_draft(item, profile=None) -> str:
    """A tailored application paragraph for `item`. '' if the LLM is unavailable."""
    profile = profile or load_profile()
    prompt = _PROMPT.format(
        name=profile.name,
        title=item.title,
        description=(item.description or "")[:600],
        profile=profile.to_prompt_block(),
    )
    return llm_scorer.complete(prompt, max_tokens=400, temperature=0.6)


if __name__ == "__main__":
    from datetime import date, timedelta

    from models import Opportunity

    demo = Opportunity(
        "Google Summer of Code 2026", "https://summerofcode.withgoogle.com/",
        "programs", "Remote open-source internship with a stipend; contribute to a major org.",
        deadline=date.today() + timedelta(days=10), tags=["program", "internship"],
    )
    print("active providers:", [p["name"] for p in __import__("config").active_llm_providers()])
    print("\n--- DRAFT ---\n")
    print(generate_draft(demo) or "(no draft — LLM unavailable)")
