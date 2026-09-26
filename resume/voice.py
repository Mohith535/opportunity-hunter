"""
HIS VOICE — one definition, used everywhere a model writes on his behalf.

Why this module exists: the voice rules were first added to tailor.py, but the resume summary is
written by generate.py's own prompt, so the rules never reached the resume. A live pack still said
"Proven ability to design…" and "Seeking SEO internship…" — the exact phrasing the rules ban. Rules
that live in one prompt and not the other are rules that do not exist. Now every prompt imports
VOICE_RULES from here, and lint() checks the output whether or not the model listened.

Two layers, deliberately:
  * VOICE_RULES — what we ASK the model to do. Helps, guarantees nothing.
  * lint() / drop_banned() — deterministic, run on every output. This is what actually holds.

The banned list is not taste. It is what recruiters report flagging as AI-written:
  - Stanford research named "realm, intricate, showcasing, pivotal" as tell-tale model words;
    recruiters add "delve", "leverage", "synergize", "results-driven" (Enhancv, 2026).
  - Oppenheimer (2006, Applied Cognitive Psychology): needlessly complex words make an author
    judged LESS intelligent, mediated by processing fluency. Plain words are the smart choice.
  - blader/humanizer (MIT) catalogues these from Wikipedia's "Signs of AI writing".

Where his confirmed voice and generic humanizer advice disagree, HIS VOICE WINS. He uses em-dash
asides and "not X, it is Y" on purpose; those get a budget, never a ban.
"""

from __future__ import annotations

import re

VOICE_RULES = """HIS VOICE — derived from his own resume and repo descriptions, and confirmed by him. Generic
prose is what gets a fresher's resume binned; specificity is the only thing that reads as a person.
- Open on the PROBLEM, never on himself. "Connecting an agent to an MCP server is all-or-nothing"
  beats "Passionate about AI safety".
- State the turn flatly, no build-up: "That is not a permission model, it is a light switch."
- Always a measured number, and ONLY his real ones (3200+ lines, 17 typed MCP tools, 190 tests,
  ~12 ms vs 250 ms, ~92% of the model's accuracy at a quarter of its calls). Never invent one.
- Name what broke, including his own work. A benchmark that refuted his own thesis is a STRENGTH
  and he has explicitly sanctioned saying so.
- Plain words. Short sentences. No hedging, no "I'm excited to", no "seeking to", no "proven ability",
  no "passionate", no "leverage", no "delve", no "results-driven".
- Em-dash asides are his, used sparingly. No emoji. No exclamation marks. No buzzword stacking."""

# HARD: a sentence containing one of these is dropped from model-written text. Every one is a phrase
# recruiters name as an AI tell or as empty filler, and none carries information.
HARD_BANNED = [
    "delve", "tapestry", "realm", "showcasing", "showcases", "synergy", "synergize",
    "results-driven", "results driven", "passionate", "proven ability", "proven track record",
    "seeking to", "seeking a ", "seeking an ", "seeking the ", "go-getter", "team player",
    "hardworking", "hard-working", "detail-oriented", "i am excited", "i'm excited", "thrilled",
    "in today's", "ever-evolving", "fast-paced", "game-changer", "game changer", "spearheaded",
    "strong background in", "excellent communication skills", "testament to",
    "here is a resume", "here's a resume", "as an ai", "tailored to the role",
]

# SOFT: reported as findings, never auto-removed. Each has a legitimate technical use ("a robust
# parser") often enough that dropping the sentence would destroy true content.
SOFT_BANNED = [
    "leverage", "leveraged", "leveraging", "intricate", "pivotal", "dynamic", "cutting-edge",
    "cutting edge", "seamless", "seamlessly", "robust", "utilize", "utilized", "honed", "adept at",
    "harness", "empower", "elevate", "unlock", "landscape", "innovative", "furthermore", "moreover",
    "meticulous", "comprehensive", "various", "a wide range of",
]

# Placeholder and meta-commentary leftovers. Our OWN "[add metric: …]" placeholder is intentional and
# allowed — it is the honest alternative to inventing a number — so it is excluded explicitly.
_PLACEHOLDER = re.compile(r"\[(?!add\b)[^\]]{1,40}\]|<[^>]{1,40}>|lorem ipsum", re.I)

# Per-document budgets for devices that are his voice in moderation and an AI tell in bulk.
BOLD_PER_BLOCK = 1      # von Restorff: one isolated item is remembered; bold everything, none is
BOLD_PER_DOC = 7
DASH_SENTENCE_SHARE = 0.60   # warn when more than 60% of sentences carry an em-dash


def _has(text_low: str, phrase: str) -> bool:
    p = phrase.lower()
    if p.endswith(" "):          # "seeking a " style — trailing space is part of the phrase
        return p in text_low
    return re.search(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", text_low) is not None


def _sentences(text: str) -> list[str]:
    """Split on sentence punctuation followed by whitespace. "B.Tech" and "v1.0" survive because
    there is no space after their dot.

    ponytail: "e.g. Python" would split early. Rare in a summary, and the failure mode is a sentence
    judged in two halves, not a crash. Upgrade to a proper tokenizer if it ever matters."""
    return [s for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s.strip()]


def drop_banned(text: str) -> tuple[str, list[str]]:
    """Remove every sentence that contains a HARD-banned phrase.

    Returns (clean_text, the phrases that caused a drop). Sentence-level, not word-level: deleting
    "passionate" from "Passionate about AI and building" leaves broken grammar, and broken grammar is
    its own tell."""
    kept, hits = [], []
    for s in _sentences(text):
        low = s.lower()
        found = [p.strip() for p in HARD_BANNED if _has(low, p)]
        if found:
            hits += found
        else:
            kept.append(s)
    return " ".join(kept), sorted(set(hits))


def lint(text: str) -> list[str]:
    """Every voice problem in a finished document, as human-readable lines. [] = clean."""
    out: list[str] = []
    low = (text or "").lower()

    hard = sorted({p.strip() for p in HARD_BANNED if _has(low, p)})
    if hard:
        out.append("AI-tell phrases: " + ", ".join(hard))
    soft = sorted({p.strip() for p in SOFT_BANNED if _has(low, p)})
    if soft:
        out.append("worth rewording (common in AI text): " + ", ".join(soft))

    ph = sorted({m.group(0) for m in _PLACEHOLDER.finditer(text or "")})
    if ph:
        out.append("placeholder or template text left in: " + ", ".join(ph[:4]))
    if "!" in (text or ""):
        out.append("exclamation mark — not his voice")

    emphasis = emphasis_bold(text)
    if len(emphasis) > BOLD_PER_DOC:
        out.append(f"{len(emphasis)} emphasised phrases — cap is {BOLD_PER_DOC}; when everything "
                   f"stands out, nothing does")

    sents = [s for s in _sentences(re.sub(r"(?m)^[#\-*].*$", "", text or "")) if len(s) > 25]
    if sents:
        dashed = sum(1 for s in sents if "—" in s)
        if dashed / len(sents) > DASH_SENTENCE_SHARE:
            out.append(f"em-dash in {dashed}/{len(sents)} sentences — his voice uses them, but at "
                       f"this density it reads as a model")
    return out


def emphasis_bold(text: str) -> list[str]:
    """Bold used for EMPHASIS, as opposed to bold used as a LABEL.

    His resume uses both, and they do different jobs. A bold lead-in at the start of a line —
    "**Languages:**", a project name, a programme title — is structure: Nielsen Norman Group's
    layer-cake finding is that scanners read exactly those line openings. Bold in the MIDDLE of a
    sentence is emphasis, and that is what the von Restorff budget is about. Counting both would
    flag his own well-structured resume as over-bolded."""
    out = []
    for line in (text or "").splitlines():
        body = re.sub(r"^\s*(?:[-*]\s+|#+\s+)?", "", line)
        for m in re.finditer(r"\*\*([^*]+)\*\*", body):
            if m.start() == 0:
                continue                      # a label: the line opens with it
            out.append(m.group(1))
    return out


def bold_budget(block: str, limit: int = BOLD_PER_BLOCK) -> str:
    """Keep the first `limit` bold phrases in a block and un-bold the rest.

    The von Restorff (isolation) effect is why bold works at all: the one item that differs is the
    one remembered. It also means a second bold phrase in the same block halves the effect of the
    first. So the budget is enforced, not suggested."""
    seen = 0

    def keep(m):
        nonlocal seen
        seen += 1
        return m.group(0) if seen <= limit else m.group(1)

    return re.sub(r"\*\*([^*]+)\*\*", keep, block or "")
