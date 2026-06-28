"""
Opportunity Hunter — central configuration.

Single source of truth for the developer profile, keyword lists, thresholds,
source toggles, and paths. Secrets come from the environment / .env (never
hardcoded), so this file is safe to commit.
"""

import os
from pathlib import Path

# Load .env if python-dotenv is installed; silently skip if it isn't.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean from the environment so cloud runs can override defaults
    (e.g. GitHub Actions disables desktop + TaskFlow, keeps phone)."""
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# ─── DEVELOPER PROFILE ───────────────────────────────────────────────
DEVELOPER_NAME = "Mohith"
CAREER_STAGE = "student"
DEGREE = "CSE"

# Anything matching an INTEREST keyword is a candidate; anything matching an
# EXCLUDE keyword is rejected. Matching is case-insensitive and word-boundary
# aware (see filters/relevance.py) so "sports" no longer kills "esports".
INTERESTS = [
    "artificial intelligence", "machine learning", "deep learning",
    "computer vision", "nlp", "large language models", "llm", "python",
    "open source", "hackathon", "internship", "research",
    "startup", "entrepreneurship", "fellowship", "scholarship",
    "gsoc", "mlh", "ssoc", "outreachy", "google", "microsoft",
    "anthropic", "nvidia", "aws", "competitive programming",
    "kaggle", "devpost", "devfolio",
]

EXCLUDE_KEYWORDS = [
    "civil engineering", "mechanical", "fashion", "celebrity",
    "politics", "gossip", "cooking", "travel", "automobile",
    "real estate",
]

LOCATION_PREFERENCE = ["remote", "online", "india", "worldwide", "global"]

# Used by the scorer for the "from a known company" bonus.
KNOWN_COMPANIES = [
    "google", "microsoft", "anthropic", "nvidia", "aws", "amazon",
    "openai", "meta", "deepmind", "apple", "ibm",
]


# ─── NOTIFICATION SETTINGS ───────────────────────────────────────────
# Topic is read from the environment so the secret stays out of source control.
# The default is a non-functional placeholder — set your own private topic in .env.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "opportunity-hunter-set-your-own-topic")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"
# Cloud runs set OH_DESKTOP=false (headless) and keep OH_PHONE=true.
DESKTOP_NOTIFICATIONS = _env_bool("OH_DESKTOP", True)
PHONE_NOTIFICATIONS = _env_bool("OH_PHONE", True)


# ─── TASKFLOW SETTINGS ───────────────────────────────────────────────
# Phase 2 decision: "propose, never auto" — opportunities are surfaced (phone +
# Nova's Scout), and YOU confirm them into TaskFlow. So auto-dump now defaults
# OFF. Set OH_TASKFLOW=true to bring back the old auto-create behaviour.
TASKFLOW_AUTO_DUMP = _env_bool("OH_TASKFLOW", False)
TASKFLOW_MIN_SCORE = 7      # only dump items scoring this or higher
TASKFLOW_TITLE_LIMIT = 80   # README: no hard limit, 80 is a safe cap

# Where TaskFlow / Nova keep their data — the Hunter READS the profile from here
# (~/.taskflow/user_profile.json) to score against the real Mohith. Overridable
# (Nova uses the same TASKFLOW_DATA_PATH env) so tests can point at a temp dir.
TASKFLOW_DATA_DIR = Path(os.environ.get("TASKFLOW_DATA_PATH", Path.home() / ".taskflow"))


# ─── SCHEDULER ───────────────────────────────────────────────────────
DAILY_RUN_TIME = "08:00"    # 24hr local time
TIMEZONE = "Asia/Kolkata"


# ─── SCORING THRESHOLDS ──────────────────────────────────────────────
CRITICAL_SCORE = 9   # 9-10  -> !c  CRITICAL
HIGH_SCORE = 7       # 7-8   -> !h  HIGH
MEDIUM_SCORE = 5     # 5-6   -> review
NOTIFY_MIN_SCORE = 5 # below this: log only, no notification


# ─── SOURCE TOGGLES ──────────────────────────────────────────────────
# Keys must match the source module names registered in sources/__init__.py.
SOURCES = {
    "research": True,    # ArXiv  (built — vertical slice)
    "github": True,      # added later
    "news": True,        # added later
    "hackathons": True,  # added later
}


# ─── NETWORK ─────────────────────────────────────────────────────────
REQUEST_TIMEOUT = 10  # seconds, applied to every outbound request
USER_AGENT = "OpportunityHunter/1.0 (personal bot)"


# ─── SOURCE CREDENTIALS ──────────────────────────────────────────────
# clist.by competitive-programming contests API (free key, required).
# Register at https://clist.by, then find your key at https://clist.by/api/v4/doc/
CLIST_USERNAME = os.environ.get("CLIST_USERNAME", "")
CLIST_API_KEY = os.environ.get("CLIST_API_KEY", "")

# GitHub API token — optional locally, auto-provided in GitHub Actions.
# Lifts the Search API rate limit (avoids 403s from shared runner IPs).
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")


# ─── PHASE 2 — LLM INTELLIGENCE (provider-agnostic chain) ────────────
# The scorer speaks the OpenAI-compatible chat format, so we keep a CHAIN of free
# providers and fall through them on quota/error. Gemini is deliberately NOT here:
# it's reserved for Nova's Kaggle x Google capstone (must keep that quota free).
#
# Free, no-card keys:
#   Groq       -> https://console.groq.com      (primary — ~1,000 req/day, fastest)
#   Cerebras   -> https://cloud.cerebras.ai     (backup  — ~1M tokens/day)
#   OpenRouter -> https://openrouter.ai/keys    (backup  — many free models, 1 key)
#
# Master toggle. When True AND at least one provider key is set, the LLM scorer
# runs; otherwise the system falls back to rule-based scoring (never crashes).
USE_LLM_SCORING = _env_bool("OH_LLM", True)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
CEREBRAS_API_KEY = os.environ.get("CEREBRAS_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# Tried in order; a provider is used only when its key is present. Each entry is
# OpenAI-compatible (POST {base_url}/chat/completions), so ONE code path serves all.
LLM_PROVIDERS = [
    {"name": "groq", "base_url": "https://api.groq.com/openai/v1",
     "api_key": GROQ_API_KEY,
     "model": os.environ.get("OH_GROQ_MODEL", "llama-3.3-70b-versatile")},
    {"name": "cerebras", "base_url": "https://api.cerebras.ai/v1",
     "api_key": CEREBRAS_API_KEY,
     "model": os.environ.get("OH_CEREBRAS_MODEL", "llama-3.3-70b")},
    {"name": "openrouter", "base_url": "https://openrouter.ai/api/v1",
     "api_key": OPENROUTER_API_KEY,
     "model": os.environ.get("OH_OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")},
]


def active_llm_providers() -> list:
    """The provider chain, in order, limited to those with a key configured."""
    return [p for p in LLM_PROVIDERS if p["api_key"]]


LLM_TIMEOUT = 60       # seconds per LLM call (longer than the 10s web default)
LLM_BATCH_SIZE = 8     # opportunities scored per call (quota-frugal)
LLM_MAX_ITEMS = 40     # hard cap on items scored per run (protects daily quota)

# Dimension weights (sum = 1.0). The model returns per-dimension scores; the final
# 0-10 is recomputed HERE so the weighting stays under our control, not the model's.
SCORE_WEIGHTS = {
    "career": 0.35, "interest": 0.25, "prestige": 0.15,
    "deadline": 0.10, "skill": 0.10, "time": 0.05,
}

# Legacy / reserved — read but unused here, so old .env files never break.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")  # reserved for Nova; not used here


# ─── PATHS ───────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
SEEN_FILE = DATA_DIR / "seen_items.json"
HISTORY_FILE = DATA_DIR / "history.json"
RUNS_LOG = LOGS_DIR / "runs.log"
DUMPS_LOG = LOGS_DIR / "dumps.log"

# Auto-create local storage so no source has to worry about it.
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
