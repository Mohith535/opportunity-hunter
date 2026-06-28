"""
LLM scorer (Phase 2) — the intelligence upgrade.

Replaces "does the text contain a keyword?" with "would Mohith REGRET missing
this?". For each opportunity the model returns a 6-dimension score, a one-line
reason, and a tiny action plan. We recompute the final 0-10 score from the
dimensions here (so the weighting stays under our control, not the model's).

PROVIDER-AGNOSTIC: talks the OpenAI-compatible chat format over plain HTTP, so it
works with any provider in config.LLM_PROVIDERS. It walks the chain (Groq ->
Cerebras -> OpenRouter -> ...) and falls through to the next on any quota/error.
No vendor SDK — just `requests` (already a dependency). Gemini is intentionally
absent: that quota is reserved for Nova's Kaggle x Google capstone.

Design rules (consistent with the rest of the project):
  * QUOTA-FRUGAL — items are scored in batches (one call per LLM_BATCH_SIZE),
    capped at LLM_MAX_ITEMS per run.
  * NEVER CRASHES — no key, quota exhausted, bad JSON, network error: we log it,
    fall to the next provider, and if all fail leave ai_score = -1 so
    policy.effective_score() falls back to the rule score. The run always finishes.
  * MUTATES IN PLACE — sets ai_score / ai_summary / action_plan / dimensions on
    each Opportunity. Returns the count it successfully scored.
"""

from __future__ import annotations

import json
import re

import requests

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

Return ONLY a JSON object of the form {{"results": [ ... ]}} with one element per
input opportunity, no prose. Each element:
{{"i": <input index int>,
  "dim": {{"career":int,"interest":int,"prestige":int,"deadline":int,"skill":int,"time":int}},
  "reason": "<<=90 chars, why it matters for {name} SPECIFICALLY>",
  "plan": ["<step with rough time, tiny first step first>", "...", "..."],
  "regret": <true if he'd genuinely regret missing it, else false>}}

Opportunities to score (JSON):
{items}
"""


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _item_payload(idx: int, it) -> dict:
    """The minimal, safe view of an opportunity we send to the model."""
    return {
        "i": idx,
        "title": it.title[:200],
        "source": it.source,
        "deadline": it.deadline.isoformat() if it.deadline else None,
        "tags": it.tags,
        "description": (it.description or "")[:500],
    }


def _parse_results(text: str) -> list[dict]:
    """Tolerant JSON extraction: handles raw JSON, ```json fences, and either a
    {"results": [...]} object or a bare [...] array."""
    if not text:
        return []
    raw = text.strip()
    # Strip a ```json ... ``` (or ``` ... ```) fence if the model added one.
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Last resort: grab the first {...} or [...] block in the text.
        m = re.search(r"(\{.*\}|\[.*\])", raw, re.DOTALL)
        if not m:
            return []
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return []
    if isinstance(data, dict):
        data = data.get("results") or data.get("items") or []
    return data if isinstance(data, list) else []


def _final_from_dims(dim: dict) -> int:
    """Weighted 0-10 final score, computed HERE from the model's dimensions."""
    total = 0.0
    for key, weight in config.SCORE_WEIGHTS.items():
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
    it.ai_score = _final_from_dims(dim)
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


def _call(provider: dict, prompt: str) -> str:
    """One OpenAI-compatible chat completion. Returns the message content string.
    Raises on HTTP/network error (the caller handles fall-through)."""
    url = f"{provider['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {provider['api_key']}",
        "Content-Type": "application/json",
    }
    body = {
        "model": provider["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 3000,
        "response_format": {"type": "json_object"},
    }
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=config.LLM_TIMEOUT)
        resp.raise_for_status()
    except requests.HTTPError:
        # Some providers/models reject response_format — retry once without it.
        body.pop("response_format", None)
        resp = requests.post(url, headers=headers, json=body, timeout=config.LLM_TIMEOUT)
        resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _score_chunk(chunk, profile) -> tuple[list[dict], str]:
    """Score one batch by walking the provider chain. Returns (results, provider_name).
    Empty results means every provider failed for this batch."""
    payload = [_item_payload(i, it) for i, it in enumerate(chunk)]
    prompt = _INSTRUCTION.format(
        name=profile.name,
        profile=profile.to_prompt_block(),
        items=json.dumps(payload, ensure_ascii=False),
    )
    for provider in config.active_llm_providers():
        try:
            content = _call(provider, prompt)
            results = _parse_results(content)
            if results:
                return results, provider["name"]
            log(f"[llm] {provider['name']} returned no parseable results, trying next.")
        except Exception as e:
            log(f"[llm] {provider['name']} failed: {e}")
            continue
    return [], ""


def score_items(items, profile) -> int:
    """LLM-score `items` in place. Returns how many were successfully scored."""
    if not items or not config.USE_LLM_SCORING:
        return 0
    providers = config.active_llm_providers()
    if not providers:
        log("[llm] no LLM provider key set (GROQ/CEREBRAS/OPENROUTER) — using rule scores.")
        return 0

    # Quota guard: only the most promising items (by cheap rule score) get an LLM
    # call; the rest keep their rule score. Protects the daily free quota.
    targets = sorted(items, key=lambda it: it.score, reverse=True)[:config.LLM_MAX_ITEMS]

    scored, used = 0, set()
    for chunk in _chunks(targets, config.LLM_BATCH_SIZE):
        results, provider_name = _score_chunk(chunk, profile)
        if not results:
            continue  # this batch keeps rule scores; the run goes on
        used.add(provider_name)
        by_index = {r.get("i"): r for r in results if isinstance(r, dict)}
        for idx, it in enumerate(chunk):
            r = by_index.get(idx)
            if r and _apply(it, r):
                scored += 1

    log(f"[llm] scored {scored}/{len(targets)} items via {', '.join(sorted(used)) or 'none'}.")
    return scored


if __name__ == "__main__":
    from datetime import date, timedelta

    from filters.scorer import score_item
    from models import Opportunity
    from user_profile import load_profile

    print("active providers:", [p["name"] for p in config.active_llm_providers()] or "NONE")
    samples = [
        Opportunity("Google Summer of Code 2026", "https://g.co/gsoc", "devpost",
                    "Open-source internship, remote, stipend for students.",
                    deadline=date.today() + timedelta(days=4)),
        Opportunity("Local cooking webinar", "https://x.com/cook", "reddit",
                    "Learn to cook pasta online, anytime."),
    ]
    for s in samples:
        s.score = score_item(s)
    n = score_items(samples, load_profile())
    print(f"\nLLM scored {n} item(s):\n")
    for s in samples:
        print(f"  ai_score={s.ai_score}  {s.title}")
        print(f"    why: {s.ai_summary}")
        print(f"    plan: {s.action_plan}\n")
