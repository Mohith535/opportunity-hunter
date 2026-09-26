"""
THE APPLICATION PACK — two files per opportunity, written for a human who applies by hand.

Most ATS forbid bots, and an application is a thing you have to stand behind. So this module
deliberately stops one step short of applying: it prepares, it never submits. What it produces
is the pack you would want open in two tabs while you fill the form yourself.

    applications/<company>-<role>-<date>/
        job.md      Everything known about the job, with nothing dropped: the real apply link,
                    the FULL description straight from the employer's own API, the
                    requirements as the employer listed them, pay, location, deadline, why
                    OPHunter ranked it where it did, and what you must verify before applying.
        resume.md   That job's resume — your real evidence, reordered and reworded for this
                    specific posting, with every claim traceable to career_profile.json.

Where the full description comes from: the same public ATS APIs the `ats` source already reads.
Verified live (Sep 2026) — Greenhouse `?content=true` returns the whole posting (about 6,000
characters), Lever returns `descriptionPlain` plus `lists`, which is the requirements already
broken into "what you will do" and "you should apply if", and Ashby returns `descriptionPlain`
with a compensation block. No scraping, no browser, no credits.

The honesty rule is the same one the rest of this package runs on and it is not negotiable:
nothing is invented. The resume reorders and rephrases what is already in your profile. Where a
bullet would be stronger with a number your profile does not contain, it leaves a visible
`[add metric: ...]` for you to fill rather than making one up. A fabricated resume is a much
worse outcome than a plain one, and it is the kind of thing that ends a career rather than
starting one.

Usage:
    py -m resume.apply --list           # the top opportunities OPHunter currently has
    py -m resume.apply 3                # build the pack for #3 in that list
    py -m resume.apply <url>            # ...or for a specific opportunity URL
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import requests

import config
from util import log

APPLICATIONS_DIR = config.BASE_DIR / "applications"
_HEADERS = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
_FETCH_TIMEOUT = 25


# ─── plain text ───────────────────────────────────────────────────────────────────────────
def _text(raw: str) -> str:
    """HTML -> readable text, keeping the paragraph and bullet structure an ATS description
    carries. A job description flattened into one wall of prose is technically complete and
    practically useless."""
    if not raw:
        return ""
    s = html.unescape(str(raw))
    if "&lt;" in s or "&gt;" in s:      # Greenhouse double-escapes its content
        s = html.unescape(s)
    s = re.sub(r"(?i)<\s*(br|/p|/div|/h[1-6]|/li)\s*/?>", "\n", s)
    s = re.sub(r"(?i)<\s*li[^>]*>", "\n- ", s)
    s = re.sub(r"(?i)<\s*(h[1-6])[^>]*>", "\n\n**", s)
    s = re.sub(r"(?i)</\s*h[1-6]\s*>", "**\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    # One more unescape AFTER the tags are gone. Greenhouse escapes its markup once and its
    # entities twice, so a single pass turns `&lt;div&gt;` into a tag but leaves `&amp;nbsp;`
    # as a literal `&nbsp;` in the middle of the prose.
    s = html.unescape(s).replace(" ", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return s.strip()


# ─── the full posting, from the employer's own API ────────────────────────────────────────
def _greenhouse_detail(slug: str, job_id: str) -> dict:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}?questions=false"
    j = requests.get(url, headers=_HEADERS, timeout=_FETCH_TIMEOUT).json()
    return {
        "description": _text(j.get("content")),
        "apply_url": j.get("absolute_url", ""),
        "company": j.get("company_name", ""),
        "location": (j.get("location") or {}).get("name", ""),
        "posted": j.get("first_published") or j.get("updated_at"),
        "closes": j.get("application_deadline"),
        "departments": [d.get("name") for d in (j.get("departments") or []) if d.get("name")],
        "offices": [o.get("name") for o in (j.get("offices") or []) if o.get("name")],
    }


def _ashby_detail(slug: str, job_id: str) -> dict:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
    jobs = requests.get(url, headers=_HEADERS, timeout=_FETCH_TIMEOUT).json().get("jobs", [])
    j = next((x for x in jobs if str(x.get("id")) == str(job_id)), None) or {}
    comp = j.get("compensation") or {}
    return {
        "description": j.get("descriptionPlain") or _text(j.get("descriptionHtml")),
        "apply_url": j.get("applyUrl") or j.get("jobUrl", ""),
        "location": j.get("location", ""),
        "posted": j.get("publishedAt"),
        "employment_type": j.get("employmentType", ""),
        "remote": j.get("isRemote"),
        "team": j.get("team") or j.get("department", ""),
        "other_locations": [str(x) for x in (j.get("secondaryLocations") or [])],
        "pay_note": comp.get("compensationTierSummary")
                    or comp.get("scrapeableCompensationSalarySummary") or "",
    }


def _lever_detail(slug: str, job_id: str) -> dict:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    jobs = requests.get(url, headers=_HEADERS, timeout=_FETCH_TIMEOUT).json()
    j = next((x for x in jobs if str(x.get("id")) == str(job_id)), None) or {}
    cats = j.get("categories") or {}
    # Lever's `lists` is the single best requirements source any of these APIs gives: the
    # employer has already split it into "what will you do" / "you should apply if you have".
    sections = []
    for block in j.get("lists") or []:
        head = (block.get("text") or "").strip().rstrip(":")
        body = _text(block.get("content"))
        if head or body:
            sections.append(f"**{head.title()}**\n{body}")
    return {
        "description": "\n\n".join(
            x for x in [j.get("descriptionPlain") or _text(j.get("description")),
                        "\n\n".join(sections),
                        j.get("additionalPlain") or _text(j.get("additional"))] if x),
        "apply_url": j.get("applyUrl") or j.get("hostedUrl", ""),
        "location": cats.get("location", ""),
        "team": cats.get("team") or cats.get("department", ""),
        "employment_type": cats.get("commitment", ""),
        "workplace": j.get("workplaceType", ""),
        "posted": j.get("createdAt"),
    }


_ATS = {"gh": _greenhouse_detail, "ashby": _ashby_detail, "lever": _lever_detail}


def fetch_full_jd(item: dict) -> dict:
    """Everything the employer publishes about this role, or {} when we cannot get more.

    Never raises: a pack built from the listing alone is worth far more than a crash, and the
    pack says plainly which of the two it got."""
    native = str(item.get("native_id") or "")
    parts = native.split(":", 2)
    if len(parts) == 3 and parts[0] in _ATS:
        try:
            got = _ATS[parts[0]](parts[1], parts[2])
            if got.get("description"):
                return got
        except (requests.RequestException, ValueError, KeyError, TypeError) as e:
            log(f"[apply] could not fetch full JD ({native}): {type(e).__name__}")
    return {}


# ─── finding the opportunity ──────────────────────────────────────────────────────────────
def recent_items(limit: int = 40) -> list[dict]:
    """The most recent run's items, best first — the same feed the brief and Nova read."""
    try:
        data = json.loads(config.HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    runs = data.get("runs") if isinstance(data, dict) else data
    if not runs:
        return []
    items = list(runs[-1].get("items", []) if isinstance(runs[-1], dict) else [])
    if len(items) < limit:                       # top up from the previous run
        for prev in reversed(runs[:-1]):
            items += list(prev.get("items", []))
            if len(items) >= limit * 2:
                break

    def score(i):
        s = i.get("ai_score", -1)
        return s if s >= 0 else i.get("score", 0)

    seen, out = set(), []
    for i in sorted(items, key=score, reverse=True):
        k = i.get("url") or i.get("title")
        if k and k not in seen:
            seen.add(k)
            out.append(i)
    return out[:limit]


def resolve(ref: str) -> dict | None:
    """An opportunity by list position, dedup key, URL, or a distinctive bit of its title."""
    items = recent_items(60)
    ref = (ref or "").strip()
    if ref.isdigit():
        n = int(ref)
        return items[n - 1] if 1 <= n <= len(items) else None
    low = ref.lower()
    for i in items:
        if ref in (i.get("key", ""), i.get("native_id", "")) or low == (i.get("url", "") or "").lower():
            return i
    for i in items:
        if low and low in (i.get("title", "") or "").lower():
            return i
    return None


# ─── writing the pack ─────────────────────────────────────────────────────────────────────
def _slug(*bits: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", " ".join(b for b in bits if b).lower()).strip("-")
    return (s[:60] or "opportunity").rstrip("-")


def _fmt(v) -> str:
    if v in (None, "", [], {}):
        return "_not stated_"
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v if x) or "_not stated_"
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v)


def build_job_md(item: dict, full: dict, report: dict | None = None) -> str:
    """job.md — everything known, and honest about what is missing."""
    from filters import focus, target

    title = item.get("title", "Untitled")
    src = item.get("source", "?")
    listing_url = item.get("url", "")
    apply_url = full.get("apply_url") or listing_url
    score = item.get("ai_score", -1)
    score = score if score >= 0 else item.get("score", 0)

    L = [f"# {title}", ""]
    L += [f"> Pack built {date.today().isoformat()} by Opportunity Hunter. "
          f"**Nothing here was submitted anywhere** — you apply by hand.", ""]

    L += ["## Apply", "",
          f"- **Apply link** — {apply_url or '_none found_'}",
          f"- Listing — {listing_url or '_n/a_'}",
          f"- Source — `{src}`" + (f" · company **{full['company']}**" if full.get("company") else ""),
          ""]

    L += ["## The facts", "", "| | |", "|---|---|"]
    rows = [
        ("Kind", focus.kind_of(_Obj(item))),
        ("Location", full.get("location") or _fmt(item.get("raw", {}).get("cities"))),
        ("Other locations", full.get("other_locations")),
        ("Remote", full.get("remote") if full.get("remote") is not None else full.get("workplace")),
        ("Employment type", full.get("employment_type")),
        ("Team / department", full.get("team") or full.get("departments")),
        ("Pay", full.get("pay_note") or _pay_line(item)),
        ("Deadline", item.get("deadline") or full.get("closes")),
        ("Posted", full.get("posted")),
        ("Tags", item.get("tags")),
    ]
    L += [f"| {k} | {_fmt(v)} |" for k, v in rows]
    L.append("")

    L += ["## Why OPHunter surfaced this", "",
          f"- Score **{score}/10**"]
    if item.get("ai_summary"):
        L.append(f"- {item['ai_summary']}")
    for why, delta in target.reasons(_Obj(item)):
        L.append(f"- {'+' if delta > 0 else ''}{delta} — {why}")
    dims = item.get("dimensions") or {}
    if dims:
        L.append("- Dimensions — " + ", ".join(f"{k} {v}" for k, v in dims.items()
                                               if isinstance(v, int)))
    L.append("")

    L += ["## Full description", ""]
    if full.get("description"):
        L += [f"_Straight from the employer's own API — this is the complete posting._", "",
              full["description"], ""]
    else:
        L += ["_The employer's API did not give us the full text, so this is what the listing "
              "carried. **Open the apply link and read the real posting before you write "
              "anything.**_", "", item.get("description") or "_no description_", ""]

    gaps = sorted(set((report or {}).get("gaps") or []) | set((report or {}).get("unverified_terms") or []))
    L += ["## Gaps you could close", ""]
    if gaps:
        L += ["This job asks for these, and your profile has no evidence of them. **They are not on "
              "your resume** — putting them there is what gets caught in the first interview "
              "question. Learn one, build something small with it, and it becomes true.", "",
              *[f"- `{g}`" for g in gaps], ""]
    else:
        L += ["_None found — every skill this listing names is backed by your profile._", ""]

    L += ["## Before you apply — verify these yourself", "",
          "OPHunter reads feeds and APIs. It cannot tell you whether a listing is real, current, "
          "or worth your time. These are the checks it genuinely cannot do for you:", "",
          "- [ ] The apply link opens a real application form on the employer's own domain",
          "- [ ] The role is still open (aggregators keep dead listings for weeks)",
          "- [ ] You meet the hard requirements — degree year, location, work authorisation",
          "- [ ] The pay above matches what the posting actually says",
          "- [ ] The company is real: website, LinkedIn, employees, funding",
          "- [ ] **No application fee, no deposit, no 'training charge'** — a real employer never asks",
          "- [ ] Every line of the resume in this folder is true and you can defend it in an interview",
          "",
          "## Notes", "", "_Your notes — what you sent, who you spoke to, what they said._", ""]
    return "\n".join(L)


def _pay_line(item: dict) -> str:
    from filters import target
    pay = target.pay_of(_Obj(item))
    return f"about Rs {pay:,}/month" if pay else ""


class _Obj:
    """Adapts a history dict to the attribute access filters/ expect."""

    def __init__(self, d: dict):
        self._d = d
        self.title = d.get("title", "")
        self.description = d.get("description", "") or d.get("ai_summary", "")
        self.source = d.get("source", "")
        self.tags = d.get("tags") or []
        self.raw = d.get("raw") or {}
        self.score = d.get("score", 0)
        self.ai_score = d.get("ai_score", -1)
        dl = d.get("deadline")
        self.deadline = None
        if dl:
            try:
                self.deadline = date.fromisoformat(str(dl)[:10])
            except ValueError:
                pass


# Text damage that must never reach an employer. Found the hard way: career_profile.json was
# rebuilt from a PDF, and PDF extraction had mapped the arrow glyph to the "fi" ligature — so a
# real generated resume read "TaskFlow v1.0 fi v8.5" and "blue fi amber fi red deadline urgency".
# The generator was working perfectly and faithfully reproducing corrupt input.
#
# A resume is the one document where a silent defect is most expensive, so this shouts instead.
_CORRUPTION = [
    (re.compile(r"�"), "replacement characters (U+FFFD) — text decoded with the wrong codec"),
    (re.compile(r"ﬀ|ﬁ|ﬂ|ﬃ|ﬄ"), "ligature glyphs left in by a PDF extractor"),
    (re.compile(r"â€|Ã¢|Ã©|Ã¼|â€™|Ã"), "mojibake — UTF-8 bytes read as Latin-1"),
    (re.compile(r"&(nbsp|amp|lt|gt|quot|#\d+);"), "raw HTML entities"),
    (re.compile(r"<[a-z/][^>]*>", re.I), "raw HTML tags"),
    (re.compile(r"\bTODO\b|\bFIXME\b|\blorem ipsum\b", re.I), "placeholder text"),
]

def _lost_arrow(word: str) -> bool:
    """Is this word a mangled arrow rather than an ordinary word containing 'fi'?

    A word list was the first attempt and it was the wrong shape — "Pacific" and "file" are
    perfectly good words, and the list would have to grow forever. The damage has a much
    narrower signature than "contains fi":
      * the word IS "fi"                    -> "TaskFlow v1.0 fi v8.5"
      * it contains "fi" more than once     -> "bluefiamberfired" (blue/amber/red)
      * "fi" sits against a digit           -> "v1.0fiv8.5"
    Every real English word fails all three."""
    w = word.lower()
    if w == "fi":
        return True
    if w.count("fi") > 1:
        return True
    return bool(re.search(r"\dfi|fi\d", w))


def corruption_warnings(text: str) -> list[str]:
    """Human-readable problems found in generated resume text. Empty list = clean."""
    out = []
    for pat, why in _CORRUPTION:
        hits = {m.group(0).strip()[:24] for m in pat.finditer(text)}
        if hits:
            out.append(f"{why} — e.g. {', '.join(sorted(hits)[:4])}")

    # The lost-arrow check runs per WORD, not per fragment: "certifications" contains "fi" and
    # is perfectly fine, so testing the matched substring alone cries wolf on half a resume.
    bad = {w for w in re.findall(r"\b[\w.+-]*fi[\w.+-]*\b", text, re.I) if _lost_arrow(w)}
    if bad:
        out.append("a stray 'fi' that is probably a lost arrow — e.g. "
                   + ", ".join(sorted(bad)[:4]))
    return out


def build_resume(item: dict, full: dict) -> tuple[str, dict]:
    """(resume.md, report) — this job's resume from career_profile.json, every claim verified.

    The report comes back to build() so job.md can list the job's skills you do not have yet as
    GAPS YOU COULD CLOSE. That is where those terms belong. The first version of this pipeline put
    three of them on the resume as skills you already had."""
    from .generate import generate_resume_ex

    jd = "\n".join(x for x in [full.get("description", ""), item.get("description", "")] if x)
    try:
        profile = json.loads((config.DATA_DIR / "career_profile.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ("# Resume\n\n_No `data/career_profile.json` yet._\n\n"
                "Build it first (a rebuild now keeps your curated layers):\n\n"
                "    py -m resume.profile --github Mohith535 --certs \"E:/certificates\" "
                "--linkedin \"E:/linkedin-agent/data/linkedin-export\"\n"), {}

    body, report = generate_resume_ex(profile, jd, role=item.get("title", ""))

    problems = corruption_warnings(body)
    placeholders = len(re.findall(r"\[add [^\]]+\]", body))
    notes = [f"Tailored for: {item.get('title','')} — {date.today().isoformat()}",
             "Every claim was checked against data/career_profile.json before it got here."]
    if report.get("removed"):
        notes.append(f"VERIFIER removed {len(report['removed'])} model-written sentence(s) your "
                     f"profile could not back:")
        notes += [f"     - {s[:110]}" for s in report["removed"]]
    if report.get("banned"):
        notes.append("VOICE removed sentences using: " + ", ".join(report["banned"]))
    if report.get("drift"):
        notes.append("facts.yml has moved on from your profile — update it:")
        notes += [f"     - {d}" for d in report["drift"]]
    if report.get("lint"):
        notes.append("Voice notes:")
        notes += [f"     - {d}" for d in report["lint"]]
    if placeholders:
        notes.append(f"{placeholders} [add ...] placeholder(s) to fill in — a real number beats a "
                     f"vague claim, and an invented one ends the interview.")
    if problems:
        notes.append("!! TEXT PROBLEMS FOUND — fix these in data/career_profile.json before "
                     "sending, they came in with the source data:")
        notes += [f"     - {p}" for p in problems]
    notes.append("Delete this comment before you send it.")
    head = "<!--\n" + "\n".join(f"  {n}" for n in notes) + "\n-->\n\n"

    if report.get("removed"):
        print(f"\n  verifier removed {len(report['removed'])} unbacked sentence(s): "
              f"{', '.join(report.get('unverified_terms') or []) or 'numbers'}")
    if report.get("drift"):
        print(f"  facts.yml drift: {len(report['drift'])} item(s) — see resume.md header")
    if problems:
        print("\n  !! resume.md has text problems inherited from career_profile.json:")
        for p in problems:
            print(f"       - {p}")
    if placeholders:
        print(f"  {placeholders} [add ...] placeholder(s) in resume.md — fill them in, never invent them.")
    return head + body, report


def build_resume_md(item: dict, full: dict) -> str:
    """Backwards-compatible: only the Markdown."""
    return build_resume(item, full)[0]


def build(ref: str) -> Path | None:
    item = resolve(ref)
    if not item:
        print(f"No opportunity matching {ref!r}. Try `py -m resume.apply --list`.")
        return None

    full = fetch_full_jd(item)
    company = (full.get("company") or (item.get("raw") or {}).get("company") or "")
    out = APPLICATIONS_DIR / _slug(company, item.get("title", ""), date.today().isoformat())
    out.mkdir(parents=True, exist_ok=True)

    resume_md, report = build_resume(item, full)
    (out / "job.md").write_text(build_job_md(item, full, report), encoding="utf-8")
    (out / "resume.md").write_text(resume_md, encoding="utf-8")

    got = "full posting from the employer API" if full.get("description") else "listing text only"
    print(f"\n  {item.get('title','')[:70]}")
    print(f"  {out}")
    print(f"    job.md     {got}")
    print(f"    resume.md  tailored from career_profile.json")
    print(f"\n  Read job.md first — the verification checklist at the bottom is the part "
          f"OPHunter cannot do for you.\n")
    return out


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if args[0] == "--list":
        items = recent_items(25)
        if not items:
            print("No opportunities yet — run `py main.py --now` first.")
            return 1
        from filters import focus
        print(f"\nTop {len(items)} from the latest hunt:\n")
        for n, i in enumerate(items, 1):
            s = i.get("ai_score", -1)
            s = s if s >= 0 else i.get("score", 0)
            print(f"  {n:>2}. [{s}/10] {(i.get('title') or '')[:64]}")
            print(f"      {focus.kind_of(_Obj(i)):10} {i.get('source',''):11} "
                  f"{i.get('deadline') or ''}")
        print(f"\n  py -m resume.apply <number>\n")
        return 0
    return 0 if build(args[0]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
