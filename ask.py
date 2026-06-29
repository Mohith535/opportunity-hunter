"""
Conversational answers (Phase C+) — just message the bot a question.

"any AI internships closing this week?" / "what's the highest-value thing right now?"
→ a grounded answer over YOUR actual opportunity feed (history), via the same
provider chain as everything else. It answers only from the data it's given and
says so when it doesn't know — no inventing.
"""

from datetime import date

from filters import llm_scorer, policy
from user_profile import load_profile

_PROMPT = """You are {name}'s personal opportunity assistant. Answer the question using
ONLY the opportunities listed below (his current feed). Be concise and specific, and
cite opportunity titles. If the answer isn't in the data, say so honestly — never invent
opportunities, deadlines, or details.

{name}'s profile (for judging relevance):
{profile}

Today is {today}.

Opportunities (title | score/10 | deadline | source):
{context}

Question: {question}

Answer concisely, citing specific titles:"""

MAX_CONTEXT = 30


def answer(question: str, history_items: dict) -> str:
    """Answer `question` grounded in the history feed. '' if the LLM is unavailable."""
    prof = load_profile()
    items = sorted((it for it in history_items.values()
                    if policy.effective_score(it) > 0),
                   key=policy.effective_score, reverse=True)[:MAX_CONTEXT]
    lines = []
    for it in items:
        dl = it.deadline.isoformat() if it.deadline else "rolling"
        lines.append(f"- {it.title[:72]} | {policy.effective_score(it)} | {dl} | {it.source}")
    context = "\n".join(lines) or "(no opportunities tracked yet)"
    prompt = _PROMPT.format(
        name=prof.name, profile=prof.to_prompt_block()[:700],
        today=date.today().isoformat(), context=context, question=question[:300],
    )
    return llm_scorer.complete(prompt, max_tokens=450, temperature=0.4)


if __name__ == "__main__":
    from datetime import timedelta

    from models import Opportunity

    def mk(t, s, src, days=None):
        o = Opportunity(t, "https://x/" + t, src, "d"); o.ai_score = s
        if days is not None:
            o.deadline = date.today() + timedelta(days=days)
        return o

    hist = {x.dedup_key(): x for x in [
        mk("Google AI Builder Program", 9, "programs", 4),
        mk("Xaira Vision-AI Intern", 8, "internships", 12),
        mk("Random Web3 Hackathon", 4, "devpost", 6),
        mk("Amazon ML Summer School", 9, "programs", 2),
    ]}
    print(answer("what AI things are closing in the next week?", hist)
          or "(no answer — LLM unavailable)")
