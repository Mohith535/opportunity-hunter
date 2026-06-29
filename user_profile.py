"""
The "real Mohith" — the profile the LLM scorer judges every opportunity against.

This is the heart of the "filter by Mohith, not by keywords" upgrade. Instead of
asking "is this an AI hackathon?", the scorer asks "would Mohith regret missing
this?" — and to answer that it needs to actually know him.

The profile is built in LAYERS, each one overlaying the last (later wins):

    1. DEFAULT_PROFILE      baked-in professional layer (interests / companies /
                            opportunity types / geography) — always present, so the
                            system works even with nothing else configured.
    2. ~/.taskflow/...      the HUMAN layer from Nova — verbatim 90-day purpose,
                            drive type, accountability style, identity. This is what
                            makes the scoring *personal*, not generic.
    3. profile.local.json   a local override file you can hand-edit (gitignored).
    4. OH_PROFILE_JSON       a JSON string from the environment (a GitHub secret in the
                            cloud run, because the repo is PUBLIC and the real profile
                            must never be committed in plaintext).

Every layer is optional. Missing/!malformed layers are skipped, never fatal — same
"never crash the run" philosophy as the rest of the project.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import config
from util import log


# ─── LAYER 1 — baked-in professional defaults ────────────────────────
# Sourced from CLAUDE.md's INTERESTS + the priority tables Mohith refined.
# Weights are 0–10 (10 = "would crawl over glass for this").
DEFAULT_PROFILE: dict = {
    "name": "Mohith",
    "identity": (
        "2nd-year B.Tech CSE (AI & ML) student in India. Builder over consumer. "
        "Author of TaskFlow and Nova. Wants Google/Microsoft-level and international "
        "(esp. Japan) opportunities."
    ),
    "long_term_goal": (
        "Become an exceptional AI engineer, builder, and entrepreneur before graduation."
    ),
    "personal_purpose": "",  # filled from Nova (verbatim) when available
    "interests": {
        "ai agents": 10, "llms": 10, "generative ai": 10, "ai engineering": 10,
        "machine learning": 9.8, "deep learning": 9.5, "python": 9.5,
        "software engineering": 9.2, "cloud (gcp/azure/aws)": 9,
        "backend development": 8.8, "open source": 8.7, "robotics ai": 8,
        "data science": 8, "cybersecurity ai": 7, "mobile development": 6,
        "game development": 3, "blockchain": 2,
    },
    "companies": {
        "google": 10, "deepmind": 10, "google cloud": 10, "microsoft": 9.8,
        "nvidia": 9.5, "anthropic": 9.4, "openai": 9.4, "hugging face": 9.2,
        "meta ai": 9, "github": 9, "kaggle": 9, "ibm": 8.8, "aws": 8.5,
        "intel": 8, "qualcomm": 8, "adobe": 7.5, "oracle": 7, "cisco": 7,
    },
    "opportunity_types": {
        "international internship": 10, "research internship": 10,
        "google program": 10, "microsoft program": 10, "ai fellowship": 10,
        "student ambassador": 9.8, "ai residency": 9.8,
        "free ai certification": 9.5, "cloud credits": 9,
        "international conference": 9, "ai hackathon": 8.8,
        "startup accelerator": 8.5, "coding contest": 7, "webinar": 4,
    },
    # Geography weights are 1–5 (Mohith is actively chasing international + Japan).
    "geo": {
        "global": 5, "remote": 5, "japan": 5, "india": 4, "us": 4,
        "europe": 4, "local college event": 2,
    },
    "values": [
        "Portfolio and resume value matter far more than cash prizes or swag.",
        "Builder over consumer — prefers making things to attending things.",
        "Hungry for international exposure and elite-credential signal.",
        "Startup / entrepreneur mindset.",
    ],
    # The human/behavioural layer (defaults; overlaid from Nova when present).
    "drivers": {
        "drive_type": "promotion",       # chases gains, not avoids losses
        "accountability": "deadline",
        "work_style": "step_by_step",
        "energy_state": "momentum",
    },
}


@dataclass
class MohithProfile:
    """The normalized profile, ready to be rendered into an LLM prompt."""

    name: str
    identity: str
    long_term_goal: str
    personal_purpose: str
    interests: dict
    companies: dict
    opportunity_types: dict
    geo: dict
    values: list
    drivers: dict
    learned: str = ""                            # taste learned from behaviour
    sources: list = field(default_factory=list)  # which layers actually loaded

    def to_prompt_block(self) -> str:
        """A compact, token-cheap text block describing Mohith for the scorer."""
        def _top(d: dict, n: int) -> str:
            items = sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:n]
            return ", ".join(f"{k} ({v})" for k, v in items)

        lines = [
            f"NAME: {self.name}",
            f"IDENTITY: {self.identity}",
            f"LONG-TERM GOAL: {self.long_term_goal}",
        ]
        if self.personal_purpose:
            lines.append(f'PERSONAL PURPOSE (his own words): "{self.personal_purpose}"')
        lines += [
            f"TOP INTERESTS: {_top(self.interests, 8)}",
            f"HIGH-VALUE COMPANIES: {_top(self.companies, 10)}",
            f"OPPORTUNITY TYPES HE CHASES: {_top(self.opportunity_types, 8)}",
            f"GEOGRAPHY (weight 1-5): {_top(self.geo, 7)}",
            "VALUES: " + " ".join(self.values),
            (
                "PSYCHOLOGY: drive="
                f"{self.drivers.get('drive_type','?')}, "
                f"accountability={self.drivers.get('accountability','?')}, "
                f"work_style={self.drivers.get('work_style','?')}, "
                f"energy={self.drivers.get('energy_state','?')}."
            ),
        ]
        if self.learned:
            lines.append(self.learned)
        return "\n".join(lines)


# ─── overlay helpers ─────────────────────────────────────────────────
def _deep_overlay(base: dict, override: dict) -> dict:
    """Merge `override` onto `base`. Nested dicts merge key-by-key; everything
    else is replaced. Used to stack the profile layers."""
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_overlay(out[k], v)
        else:
            out[k] = v
    return out


def _from_nova(merged: dict) -> dict:
    """LAYER 2 — pull the human layer out of Nova's ~/.taskflow/user_profile.json.

    Nova's profile is psychological, not a keyword list, so we extract exactly the
    fields that make scoring personal: the verbatim purpose and the behavioural
    drivers. Interests/companies stay from DEFAULT_PROFILE (Nova doesn't store them)."""
    path = config.TASKFLOW_DATA_DIR / "user_profile.json"
    if not path.exists():
        return merged
    try:
        prof = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log(f"[profile] Nova profile present but unreadable: {e}")
        return merged

    patch: dict = {}
    basics = prof.get("basics") or {}
    if basics.get("name"):
        patch["name"] = basics["name"]
    nova = prof.get("nova") or {}
    if nova.get("purpose_90d"):
        patch["personal_purpose"] = nova["purpose_90d"].strip()
    drivers = {k: nova[k] for k in
               ("drive_type", "accountability", "work_style", "energy_state")
               if nova.get(k)}
    if drivers:
        patch["drivers"] = drivers

    if patch:
        merged = _deep_overlay(merged, patch)
        merged.setdefault("_sources", []).append("nova")
    return merged


def _from_json_blob(merged: dict, blob: str, label: str) -> dict:
    """LAYERS 3 & 4 — overlay a JSON dict (from a local file or an env secret)."""
    if not blob:
        return merged
    try:
        patch = json.loads(blob)
    except json.JSONDecodeError as e:
        log(f"[profile] {label} is not valid JSON, ignoring: {e}")
        return merged
    if isinstance(patch, dict) and patch:
        merged = _deep_overlay(merged, patch)
        merged.setdefault("_sources", []).append(label)
    return merged


def load_profile() -> MohithProfile:
    """Build the layered profile. Always returns a usable profile."""
    merged = dict(DEFAULT_PROFILE)
    merged["_sources"] = ["default"]

    # 2. Nova's human layer (local machine only).
    merged = _from_nova(merged)

    # 3. local override file (gitignored).
    local_path = Path(config.BASE_DIR) / "profile.local.json"
    if local_path.exists():
        try:
            merged = _from_json_blob(merged, local_path.read_text(encoding="utf-8"),
                                     "profile.local.json")
        except OSError as e:
            log(f"[profile] could not read profile.local.json: {e}")

    # 4. env secret (cloud run).
    merged = _from_json_blob(merged, os.environ.get("OH_PROFILE_JSON", ""),
                             "OH_PROFILE_JSON")

    sources = merged.pop("_sources", ["default"])
    # Taste learned from behaviour (local; empty until there's enough evidence).
    try:
        import taste
        learned = taste.summary_line()
        if learned:
            sources.append("taste")
    except Exception:
        learned = ""
    return MohithProfile(
        name=merged["name"],
        identity=merged["identity"],
        long_term_goal=merged["long_term_goal"],
        personal_purpose=merged.get("personal_purpose", ""),
        interests=merged["interests"],
        companies=merged["companies"],
        opportunity_types=merged["opportunity_types"],
        geo=merged["geo"],
        values=merged["values"],
        drivers=merged["drivers"],
        learned=learned,
        sources=sources,
    )


if __name__ == "__main__":
    p = load_profile()
    print(f"Profile loaded from layers: {', '.join(p.sources)}\n")
    print(p.to_prompt_block())
