"""
THE CLAIM VERIFIER — nothing reaches a resume unless the profile can back it.

Why this exists, specifically: a generated pack for an SEO internship said "Skilled in HTML, meta
tags, content creation, and SEO fundamentals". "SEO", "meta tags" and "content creation" appear
ZERO times in career_profile.json. The prompt already said "mirror the job's terms wherever they are
TRUE" — a free-tier model ignored the qualifier and copied the job ad. A prompt rule is a request,
not a guarantee. This module is the guarantee.

It is fully deterministic. It must NOT depend on the LLM (analyzer.extract_jd_keywords does, and it
returns [] exactly when the models are down — which is exactly when a fallback most needs checking).

What counts as a claim, three independent nets:
  1. A known skill/tool/domain term (the lexicon below) appearing in the text.
  2. Any keyword extracted from the job ad, when the caller has them — the terms most likely to be
     smuggled in, since that is precisely where the SEO claims came from.
  3. Every item enumerated after a claim phrase ("skilled in X, Y and Z", "proficient in …",
     "experience with …") — catches an invented skill the lexicon has never heard of.
Plus every NUMBER, which must appear in the evidence. A suspiciously round invented metric
("increased productivity by 312%") is one of the red flags recruiters name.

The unit of removal is the SENTENCE. Deleting one word from "Skilled in HTML, meta tags and SEO"
leaves broken grammar; dropping the sentence leaves a shorter, true summary. A shorter true resume
beats a longer false one every time — and what was removed is reported, so job.md can list it as a
gap you could close rather than hiding it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# Skill, tool and domain terms a model is likely to assert. Deliberately broad on NON-technical terms,
# because those are what a job ad for the wrong role injects (the SEO case), and deliberately
# including his real stack so the check is exercised on terms that DO verify, not only on failures.
LEXICON = [
    # marketing / sales / ops — the usual injections from an off-domain ad
    "seo", "sem", "meta tags", "content creation", "content marketing", "content writing",
    "copywriting", "social media", "email marketing", "digital marketing", "lead generation",
    "cold calling", "crm", "salesforce", "hubspot", "google analytics", "wordpress", "canva",
    "photoshop", "illustrator", "video editing", "graphic design", "recruitment", "payroll",
    "accounting", "tally", "excel", "power bi", "tableau", "customer support", "negotiation",
    # languages and frameworks
    "python", "java", "javascript", "typescript", "c++", "c#", "golang", "rust", "kotlin",
    "swift", "php", "ruby", "scala", "matlab", "sql", "html", "css", "react", "angular", "vue",
    "next.js", "node.js", "express", "django", "flask", "fastapi", "spring", "spring boot",
    "flutter", "react native", "android", "ios", "unity", "unreal",
    # data / ml
    "machine learning", "deep learning", "pytorch", "tensorflow", "keras", "scikit-learn",
    "pandas", "numpy", "opencv", "computer vision", "nlp", "llm", "rag", "langchain",
    "fine-tuning", "reinforcement learning", "data science", "data analysis", "data analytics",
    "data visualization", "statistics", "hadoop", "spark", "kafka", "airflow", "snowflake",
    "bigquery", "mlops",
    # infra
    "aws", "azure", "gcp", "google cloud", "docker", "kubernetes", "terraform", "ansible",
    "jenkins", "ci/cd", "linux", "bash", "graphql", "rest api", "microservices", "mongodb",
    "postgresql", "mysql", "redis", "elasticsearch", "cockroachdb", "cloudflare",
    # other domains
    "cybersecurity", "penetration testing", "blockchain", "solidity", "web3", "embedded",
    "verilog", "vlsi", "iot", "arduino", "autocad", "solidworks", "blender", "figma",
    "ux research", "ui design", "product management", "agile", "scrum", "jira",
]

# Different spellings of the same claim. The evidence may say one and the model write the other.
ALIASES = {
    "js": "javascript", "ts": "typescript", "ml": "machine learning", "postgres": "postgresql",
    "k8s": "kubernetes", "genai": "generative ai", "gen ai": "generative ai", "llms": "llm",
    "large language models": "llm", "node": "node.js", "nextjs": "next.js", "sklearn":
    "scikit-learn", "ci-cd": "ci/cd", "rest apis": "rest api", "restful": "rest api",
    "search engine optimization": "seo", "golang": "go", "gcp": "google cloud",
    # Same skill, different noun. A live DS/ML pack listed "data analysis" as a GAP for someone
    # with a Cisco Data Analytics certificate and a completed EDA-to-modelling pipeline — a false
    # gap tells him to go learn what he already has.
    "data analysis": "data analytics", "analytics": "data analytics", "eda": "data analytics",
    "exploratory data analysis": "data analytics", "ml engineering": "machine learning",
    "genai": "generative ai", "prompt design": "prompt engineering",
}

# A claim phrase, then a list. "skilled in HTML, meta tags, content creation, and SEO fundamentals"
_CLAIM_TRIGGER = re.compile(
    r"\b(skilled in|skills in|proficient in|proficiency in|experienced (?:in|with)|experience (?:in|with)"
    r"|expertise in|expert in|knowledge of|familiar with|fluent in|versed in|hands-on with"
    r"|competent in|strong in|background in)\s+([^.;:]{3,160})", re.I)

_NUMBER = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)(?:\s?(?:%|ms|k|x|\+))?(?![\w])", re.I)
_ORDINAL = re.compile(r"\b(\d+)(?:st|nd|rd|th)\b", re.I)
_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "fifteen": "15",
    "twenty": "20", "second": "2", "third": "3", "first": "1", "quarter": "4",
}


@dataclass
class Verdict:
    text: str                                   # the text with unbacked sentences removed
    removed: list[str] = field(default_factory=list)          # the sentences dropped
    unverified_terms: list[str] = field(default_factory=list)  # claims the profile cannot back
    unverified_numbers: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.removed


# ─── evidence ─────────────────────────────────────────────────────────────────────────────
def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k != "meta":              # provenance notes are ABOUT the data, not evidence
                yield from _strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _strings(v)


def evidence_text(profile: dict, extra: str = "") -> str:
    """Everything the profile says, lowercased, with number-words also written as digits so
    "five working systems" backs a model's "5 systems"."""
    blob = " ".join(_strings(profile or {})) + " " + (extra or "")
    low = blob.lower()
    for word, digit in _NUMBER_WORDS.items():
        low += f" {digit}" if re.search(rf"\b{word}\b", low) else ""
    return low


def _norm(term: str) -> str:
    t = re.sub(r"\s+", " ", term.lower().strip().strip(".,;:()\"'"))
    return ALIASES.get(t, t)


def _present(term: str, low: str) -> bool:
    t = _norm(term)
    if not t:
        return True
    variants = {t, ALIASES.get(t, t)}
    variants |= {k for k, v in ALIASES.items() if v == t}
    if t.endswith("s") and len(t) > 4:
        variants.add(t[:-1])                      # "meta tags" backed by "meta tag"
    for v in variants:
        if re.search(r"(?<![a-z0-9])" + re.escape(v) + r"(?![a-z0-9])", low):
            return True
    return False


# ─── claims ───────────────────────────────────────────────────────────────────────────────
def _enumerated(sentence: str) -> list[str]:
    """Items listed after a claim phrase: 'skilled in A, B and C' -> [A, B, C]."""
    items = []
    for m in _CLAIM_TRIGGER.finditer(sentence):
        tail = re.split(r"\b(?:to|for|while|which|that|so|because|in order)\b", m.group(2), 1)[0]
        for part in re.split(r",|\band\b|\bor\b|&|/", tail):
            part = re.sub(r"^\s*(?:the|a|an|basic|strong|solid|deep|good|core)\s+", "", part.strip(),
                          flags=re.I)
            part = re.sub(r"\s+(?:fundamentals|basics|concepts|principles|skills?)$", "", part,
                          flags=re.I).strip()
            if 2 <= len(part) <= 40:
                items.append(part)
    return items


def _direct_claims(sentence: str, jd_keywords: list[str]) -> list[str]:
    """Known skill/tool terms (lexicon + the job's own keywords) named anywhere in the sentence."""
    low = sentence.lower()
    found = [t for t in LEXICON if _present(t, low)]
    found += [k for k in (jd_keywords or []) if k and _present(k, low)]
    seen, out = set(), []
    for f in found:
        n = _norm(f)
        if n and n not in seen:
            seen.add(n)
            out.append(f.strip())
    return out


_NAMED_THING = re.compile(r"\b[A-Z][A-Za-z0-9]+|\d|\.js\b|\+\+|#")


def _item_unbacked(item: str, low: str) -> list[str]:
    """What, if anything, is unbacked in one item of a 'skilled in A, B and C' list. [] = fine.

    Judged by the KNOWN terms inside the item, not the item as a whole: the first version rejected
    "with HTML on the side" and "Postgres-backed services" wholesale, though each names a skill he
    has — and a verifier that deletes true sentences gets switched off within a day. An item with
    no known term at all is flagged only if it NAMES something (a capitalised word, a version, a
    .js / ++ / # shape), which is how an invented tool looks ("Zorblax"); a plain phrase such as
    "building reliable systems" is vague, not a claim."""
    if _present(item, low):
        return []
    item_low = item.lower()
    known = [t for t in (*LEXICON, *ALIASES) if _present(t, item_low)]
    unbacked = [t for t in known if not _present(t, low)]
    if unbacked:
        return unbacked
    if known:
        return []
    return [item] if _NAMED_THING.search(item) else []


def _numbers(sentence: str) -> list[str]:
    nums = [m.group(1).replace(",", "") for m in _NUMBER.finditer(sentence)]
    nums += [m.group(1) for m in _ORDINAL.finditer(sentence)]
    return [n for n in nums if n]


def _number_backed(n: str, low: str) -> bool:
    core = n.rstrip("0").rstrip(".") if "." in n else n
    for v in {n, core}:
        if re.search(r"(?<![0-9])" + re.escape(v) + r"(?![0-9])", low.replace(",", "")):
            return True
    return False


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s.strip()]


def verify(text: str, profile: dict, jd_keywords: list[str] | None = None,
           extra_evidence: str = "") -> Verdict:
    """Keep only the sentences whose every claim and number the profile can back."""
    low = evidence_text(profile, extra_evidence)
    kept, removed, bad_terms, bad_nums = [], [], [], []
    for s in _sentences(text):
        terms = [t for t in _direct_claims(s, jd_keywords or []) if not _present(t, low)]
        for item in _enumerated(s):
            terms += _item_unbacked(item, low)
        nums = [n for n in _numbers(s) if not _number_backed(n, low)]
        if terms or nums:
            removed.append(s)
            bad_terms += terms
            bad_nums += nums
        else:
            kept.append(s)
    return Verdict(" ".join(kept), removed,
                   sorted({_norm(t) for t in bad_terms}), sorted(set(bad_nums)))


def jd_gaps(jd_text: str, profile: dict, jd_keywords: list[str] | None = None) -> list[str]:
    """Skills the JOB names that the PROFILE cannot back — the honest version of what the model
    tried to smuggle into the resume. These belong in job.md as things you could learn or build,
    never on the resume as things you already have."""
    low = evidence_text(profile)
    jd_low = (jd_text or "").lower()
    asked = [t for t in LEXICON if _present(t, jd_low)] + list(jd_keywords or [])
    seen, out = set(), []
    for t in asked:
        n = _norm(t)
        if n and n not in seen and not _present(t, low):
            seen.add(n)
            out.append(n)
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from .profile import load_profile_json

    prof = load_profile_json() or {}
    seo = ("2nd-year B.Tech CSE (AI & ML) student, author of TaskFlow. Skilled in HTML, meta tags, "
           "content creation, and SEO fundamentals. Built NitroWatch in TypeScript.")
    v = verify(seo, prof)
    print("kept   :", v.text)
    print("removed:", v.removed)
    print("terms  :", v.unverified_terms, " numbers:", v.unverified_numbers)
    print(json.dumps({"clean": v.clean}))
