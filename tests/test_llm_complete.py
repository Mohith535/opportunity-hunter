"""Tests for filters/llm_scorer.complete() — the free-text call every resume line goes through.

Measured 4 Oct 2026: Groq's openai/gpt-oss-120b is a reasoning model, and on the resume's tailoring
prompt at max_tokens=160 it spent 158 tokens thinking and returned an EMPTY answer with
finish_reason "length". complete() returned that '' as a success, so all 8 resume packs it had built
got no tailoring and nothing said so. These tests replay that exact response.

Run:  python tests/test_llm_complete.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
from filters import llm_scorer as L

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

class _Resp:
    def __init__(self, content, finish):
        self._j = {"choices": [{"message": {"content": content}, "finish_reason": finish}]}
    def raise_for_status(self): pass
    def json(self): return self._j

PROVIDERS = [{"name": "groq", "base_url": "https://g", "api_key": "k", "model": "openai/gpt-oss-120b"},
             {"name": "openrouter", "base_url": "https://o", "api_key": "k", "model": "some/model"}]
sent = []
def chain(*answers):
    it = iter(answers)
    def post(url, headers=None, json=None, timeout=None):
        sent.append((url, json))
        return _Resp(*next(it))
    return post

_old_post, _old_prov, _old_use = L.requests.post, config.active_llm_providers, config.USE_LLM_SCORING
config.active_llm_providers = lambda: PROVIDERS
config.USE_LLM_SCORING = True
L.log = lambda *a, **k: None
try:
    L.requests.post = chain(("", "length"), ("LINE: a real sentence.", "stop"))
    check("1. an EMPTY answer cut off by the token limit is a failure — the next provider answers",
          L.complete("p", max_tokens=160) == "LINE: a real sentence.")

    sent.clear()
    L.requests.post = chain(("LINE: Built an always-on bot on Cloud", "length"), ("LINE: whole.", "stop"))
    check("2. a CUT-OFF answer never reaches a resume", L.complete("p", max_tokens=160) == "LINE: whole.")

    sent.clear()
    L.requests.post = chain(("LINE: fine.", "stop"))
    out = L.complete("p", max_tokens=160)
    body = sent[0][1]
    check("3. a finished answer is returned", out == "LINE: fine.")
    check("4. thinking room is added on top of the asked budget",
          body["max_tokens"] == 160 + L.REASONING_HEADROOM, body["max_tokens"])
    check("5. gpt-oss is asked to reason briefly", body.get("reasoning_effort") == "low")

    sent.clear()
    L.requests.post = chain(("x", "stop"))
    L.complete("p")
    sent.clear()
    config.active_llm_providers = lambda: PROVIDERS[1:]
    L.requests.post = chain(("x", "stop"))
    L.complete("p")
    check("6. other models are not sent reasoning_effort", "reasoning_effort" not in sent[0][1])

    config.active_llm_providers = lambda: PROVIDERS
    L.requests.post = chain(("", "length"), ("", "stop"))
    check("7. every provider empty -> '' (the caller then says tailoring failed)", L.complete("p") == "")
finally:
    L.requests.post, config.active_llm_providers, config.USE_LLM_SCORING = _old_post, _old_prov, _old_use

print("=" * 72)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 72)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
