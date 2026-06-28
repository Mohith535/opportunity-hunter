"""
LLM scorer (Phase 2) — the intelligence upgrade.

Replaces "does the text contain a keyword?" with "would Mohith REGRET missing
this?". For each opportunity Gemini returns a 6-dimension score, a one-line reason,
and a tiny action plan. We recompute the final 0-10 score from the dimensions here
(so the weighting stays under our control, not the model's).

Design rules (consistent with the rest of the project):
  * QUOTA-FRUGAL — items are scored in batches (one call per LLM_BATCH_SIZE),
    capped at LLM_MAX_ITEMS per run. The free Gemini tier is 1,500 calls/day.
  * NEVER CRASHES — no key, quota exhausted, bad JSON, network error: we log it
    and leave ai_score = -1, so policy.effective_score() falls back to the rule
    score. The run always finishes.
  * MUTATES IN PLACE — sets ai_score / ai_summary / action_plan / dimensions on
    each Opportunity. Returns the count it successfully scored.
"""

from __future__ import annotations

import json

import config
from util import log

# The 0-10 scale is shared with the rule scorer, so policy thresholds
# (CRITICAL=9, HIGH=7, MEDIUM=5) keep working unchanged.

_INSTRUCTION = """You are the opportunity-evaluation brain for {name}.

Your single job: for each opportunity, decide how much {name} would REGRET missing it.
Regret is NOT "is this relevant?" — it is career_leverage x urgency x irreversibility.
A prestigious, hard-to-reverse opportunity closing soon outranks a generic one he can
do anytime. Things he can always redo later (webinars, evergreen tutorials) score low
even if on-topic.

Here is who {name} actually is — score against THIS person, not a generic student:
{profile}

Score each opportunity on six dimensions, each 0-10:
  career   — does it move him toward his long-term goal / purpose?
  interest — match to his real interests (AI agents, LLMs, GenAI, building), not just any CS
  prestige — resume/credential signal (his high-value companies, top labs, international)
  deadline — urgency & irreversibility of missing it (no deadline / evergreen = low)
  skill    — portfolio / real-skill growth (he values this far above cash or swag)
  time     — effort-vs-payoff (a month-long low-value commitment should score LOW here)

Be a harsh, honest judge. MOST items are 4-6. Reserve 9-10 for genuinely elite,
high-leverage, hard-to-reverse opportunities he'd truly regret missing.

Return ONLY a JSON array, same length and order as the input, no prose. Each element:
{{"i": <input index int>,
  "dim": {{"career":int,"interest":int,"prestige":int,"deadline":int,"skill":int,"time":int}},
  "reason": "<<=90 chars, why it matters for {name} SPECIFICALLY>",
  "plan": ["<step with rough time, tiny first step first>", "...", "..."],
  "regret": <true if he'd genuinely regret missing it, else false>}}

Opportunities to score:
{items}
"""


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _item_payload(idx: int, it) -> dict:
    """The minimal, safe view of an opportunity we send to the model."""
    deadline = it.deadline.isoformat() if it.deadline else None
    desc = (it.description or "")[:500]
    return {
        "i": idx,
        "title": it.title[:200],
        "source": it.source,
        "deadline": deadline,
        "tags": it.tags,
        "description": desc,
    }


def _final_from_dims(dim: dict) -> int:
    """Weighted 0-10 final score, computed HERE from the model's dimensions."""
    w = config.SCORE_WEIGHTS
    total = 0.0
    for key, weight in w.items():
        try:
            total += float(dim.get(key, 0)) * weight
        except (TypeError, ValueError):
            pass
    return max(0, min(10, round(total)))


def _apply(it, result: dict) -> bool:
    """Write one model result onto an Opportunity. Returns True if it stuck."""
    dim = result.get("dim") or {}
    if not isinstance(dim, dict):
        return False
    final = _final_from_dims(dim)
    it.ai_score = final
    it.dimensions = {k: dim.get(k) for k in config.SCORE_WEIGHTS}
    reason = (result.get("reason") or "").strip()
    if reason:
        it.ai_summary = reason[:140]
    plan = result.get("plan")
    if isinstance(plan, list):
        it.action_plan = [str(s).strip() for s in plan if str(s).strip()][:5]
    if result.get("regret"):
        it.dimensions["regret"] = True
    return True


def _build_model():
    """Configure the Gemini client. Returns the genai module or None if the SDK
    isn't installed (in which case we cleanly fall back to rule scoring)."""
    try:
        import google.generativeai as genai
    except ImportError:
        log("[llm] google-generativeai not installed — using rule scores. "
            "(pip install -r requirements.txt)")
        return None
    genai.configure(api_key=config.GEMINI_API_KEY)
    return genai


def _score_chunk(genai, model_name: str, chunk, profile) -> list[dict]:
    """One Gemini call for a batch. Raises on failure (caller handles)."""
    payload = [_item_payload(i, it) for i, it in enumerate(chunk)]
    prompt = _INSTRUCTION.format(
        name=profile.name,
        profile=profile.to_prompt_block(),
        items=json.dumps(payload, ensure_ascii=False),
    )
    model = genai.GenerativeModel(model_name)
    resp = model.generate_content(
        prompt,
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0.2,
            "max_output_tokens": 2048,
        },
    )
    data = json.loads(resp.text)
    if isinstance(data, dict):                      # tolerate {"results":[...]}
        data = data.get("results") or data.get("items") or []
    return data if isinstance(data, list) else []


def score_items(items, profile) -> int:
    """LLM-score `items` in place. Returns how many were successfully scored."""
    if not items:
        return 0
    if not config.USE_LLM_SCORING:
        return 0
    if not config.GEMINI_API_KEY:
        log("[llm] no GEMINI_API_KEY — falling back to rule scores.")
        return 0

    genai = _build_model()
    if genai is None:
        return 0

    # Quota guard: only the most promising items (by the cheap rule score) get an
    # LLM call; the rest keep their rule score. Protects the daily free quota.
    ranked = sorted(items, key=lambda it: it.score, reverse=True)
    targets = ranked[:config.LLM_MAX_ITEMS]

    model_name = config.GEMINI_MODEL
    scored = 0
    for chunk in _chunks(targets, config.LLM_BATCH_SIZE):
        results = None
        for attempt_model in (model_name, config.GEMINI_FALLBACK_MODEL):
            try:
                results = _score_chunk(genai, attempt_model, chunk, profile)
                model_name = attempt_model  # stick with whatever worked
                break
            except Exception as e:           # quota / network / parse — try fallback
                log(f"[llm] {attempt_model} failed on a batch: {e}")
                continue
        if not results:
            continue  # this batch keeps rule scores; the run goes on

        by_index = {r.get("i"): r for r in results if isinstance(r, dict)}
        for idx, it in enumerate(chunk):
            r = by_index.get(idx)
            if r and _apply(it, r):
                scored += 1

    log(f"[llm] scored {scored}/{len(targets)} items with Gemini ({model_name}).")
    return scored


if __name__ == "__main__":
    from datetime import date, timedelta

    from models import Opportunity
    from user_profile import load_profile

    samples = [
        Opportunity("Google Summer of Code 2026", "https://g.co/gsoc", "devpost",
                    "Open-source internship, remote, stipend for students.",
                    deadline=date.today() + timedelta(days=4)),
        Opportunity("Local cooking webinar", "https://x.com/cook", "reddit",
                    "Learn to cook pasta online, anytime."),
    ]
    for s in samples:
        from filters.scorer import score_item
        s.score = score_item(s)
    n = score_items(samples, load_profile())
    print(f"\nLLM scored {n} item(s):\n")
    for s in samples:
        print(f"  ai_score={s.ai_score}  {s.title}")
        print(f"    why: {s.ai_summary}")
        print(f"    plan: {s.action_plan}\n")
