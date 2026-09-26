"""
ELIGIBILITY — "can I even apply?", answered before anything else.

Why this exists. A live sample of 20 student roles from the company career boards OPHunter reads found
18 stating a rule a candidate is checked against — and nearly all of them excluded him:
    "Must be planning on graduating in 2028"
    "Graduating between December 2027 and Summer 2028 (required)"
    "Currently in your junior year of an undergraduate program (rising senior in summer 2027)"
    "must be authorized to work in the United States; visa sponsorship is not available"
    "Currently pursuing a degree in Computer Science … from a university in Mexico (required)"
He graduates in 2029, is in 2nd year, and lives in India. OPHunter had
been ranking these roles highly and never said so. A resume tailored to a job you cannot take is wasted
effort, and 70 days to an offer letter is not enough time to waste.

Deterministic — no LLM — because a verdict that silently disappears when the free models are down is
worse than none. Three levels, deliberately:
    NO     a stated rule excludes you (grad year, year of study, PhD-only, a country you cannot work in)
    CHECK  a rule you should read yourself (a restricted field of study, a gender restriction, a
           city-restricted listing). It is NEVER inferred from your name or anything else not stated.
    YES    every rule the posting states is met      NOT_STATED  the posting states no rules at all
A verdict is only as good as the posting: "YES" means "nothing it says rules you out", not "you
qualify", and the reasons are always shown so a wrong call is visible.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date

NO, CHECK, YES, NOT_STATED = "NO", "CHECK", "YES", "NOT_STATED"

# Where a role can be held from India without a visa, in the listing's own words.
_HOME = re.compile(r"\b(india|mumbai|bombay|bengaluru|bangalore|chennai|hyderabad|pune|delhi|new delhi|"
                   r"noida|gurgaon|gurugram|kolkata|ahmedabad|jaipur|kochi|chandigarh|remote|anywhere|"
                   r"work from home|wfh|online)\b", re.I)
# Places that need a right to work he does not have. US state codes are matched as ", XX" to avoid
# eating ordinary two-letter words.
_ABROAD = re.compile(
    r"(,\s*(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|"
    r"NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\b)|\b(united states|usa|u\.s\.|"
    r"united kingdom|\buk\b|london|england|canada|toronto|vancouver|mexico|qatar|doha|singapore|"
    r"germany|berlin|france|paris|netherlands|amsterdam|ireland|dublin|switzerland|zurich|zürich|"
    r"japan|tokyo|australia|sydney|israel|tel aviv|poland|warsaw|spain|madrid|brazil|são paulo|"
    r"sao paulo|argentina|uae|dubai|hong kong|korea|seoul|china|taiwan|sweden|denmark|norway|"
    r"new york|san francisco|seattle|menlo park|palo alto|mountain view|chicago|austin|boston|"
    r"los angeles|denver|atlanta|washington)\b", re.I)

# \bgraduat, not graduat: "undergraduate program (rising senior in summer 2027)" is about the
# internship summer, and without the boundary it produced "wants graduation in 2027" — right verdict,
# wrong reason, and a wrong reason is how a person learns not to trust the verdict.
_GRAD_CTX = re.compile(r"\bgraduat|class of|grad date|degree completion|completion of (?:your|the) degree", re.I)
_YEAR = re.compile(r"\b(20[2-3]\d)\b")
_OLD_CAP = 6        # how many courses / years the Unstop source kept before it stopped truncating


@dataclass
class Candidate:
    grad_year: int = 2029
    start_year: int = 2025
    degree: str = "bachelor"            # bachelor | master | phd
    course: str = "btech"               # Unstop's course key
    country: str = "India"

    @property
    def study_year(self) -> int:
        """Academic year of study today. The year turns over in July (Indian academic calendar)."""
        t = date.today()
        return max(1, (t.year - self.start_year) + (1 if t.month >= 7 else 0))


@dataclass
class Verdict:
    level: str
    reasons: list[tuple[str, str]] = field(default_factory=list)     # (level, why)

    @property
    def icon(self) -> str:
        return {NO: "⛔", CHECK: "⚠", YES: "✅", NOT_STATED: "❔"}[self.level]

    @property
    def label(self) -> str:
        return {NO: "NOT ELIGIBLE", CHECK: "CHECK BEFORE APPLYING", YES: "ELIGIBLE",
                NOT_STATED: "RULES NOT STATED"}[self.level]

    def line(self) -> str:
        head = f"{self.icon} {self.label}"
        return head + (" — " + "; ".join(w for _, w in self.reasons[:3]) if self.reasons else "")


def candidate_from(profile: dict | None, target: dict | None = None) -> Candidate:
    """His facts, read from the profile rather than hard-coded — the graduation year is exactly the
    fact that was wrong once, and it must change in ONE place."""
    c = Candidate()
    for e in (profile or {}).get("education", []):
        inst = (e.get("institution") or "").lower()
        if any(w in inst for w in ("school",)) and "technology" not in inst:
            continue
        try:
            c.grad_year = int(str(e.get("endDate"))[:4])
            c.start_year = int(str(e.get("startDate"))[:4])
        except (TypeError, ValueError):
            pass
        break
    if target and target.get("country"):
        c.country = str(target["country"])
    return c


# ─── rules from free text (career boards, any description) ────────────────────────────────────
def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.;!?])\s+|\n+", text or "") if s.strip()]


def text_rules(text: str, c: Candidate) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    low = (text or "").lower()

    for s in _sentences(text):
        sl = s.lower()
        if _GRAD_CTX.search(sl):
            years = sorted({int(y) for y in _YEAR.findall(s)})
            if years and "later" not in sl and "beyond" not in sl and "after" not in sl:
                if c.grad_year not in years and max(years) < c.grad_year:
                    rng = f"{years[0]}" if len(years) == 1 else f"{years[0]}–{years[-1]}"
                    out.append((NO, f"wants graduation in {rng}; you graduate {c.grad_year}"))
                elif c.grad_year in years:
                    out.append((YES, f"graduation {c.grad_year} is accepted"))

    if re.search(r"\b(junior year|rising senior|senior year|final[- ]year|penultimate year|"
                 r"final internship before graduating)\b", low) and c.study_year <= 2:
        out.append((NO, f"wants a junior/final-year student; you are in year {c.study_year}"))
    if re.search(r"\b(first[- ]or second[- ]year|freshman|sophomore|1st or 2nd year|first[- ]year or "
                 r"second[- ]year|early[- ]career students?|pre-final year)\b", low) and c.study_year <= 2:
        out.append((YES, f"open to early-year students like you (year {c.study_year})"))

    if re.search(r"\b(pursuing a ph\.?d|phd (student|candidate|intern)|doctoral)\b", low) and \
            not re.search(r"bachelor|undergraduate|b\.?tech|master", low):
        out.append((NO, "PhD students only"))

    if re.search(r"authori[sz]ed to work in the (united states|us|u\.s\.)|us work authori[sz]ation", low) and \
            re.search(r"sponsorship is not|no (visa )?sponsorship|not (be )?able to sponsor|without sponsorship", low):
        out.append((NO, "needs US work authorisation, and sponsorship is not offered"))
    m = re.search(r"from a university in ([a-z ]+?)\s*\(required\)", low)
    if m and m.group(1).strip() != c.country.lower():
        out.append((NO, f"must be enrolled at a university in {m.group(1).strip().title()}"))

    fm = re.search(r"degree in ([^.;]{5,160})", low)
    if fm and not re.search(r"computer|software|engineering|informatics|information|data|math|"
                            r"electr|stem|technical|related field|equivalent", fm.group(1)):
        out.append((CHECK, f"asks for a degree in {fm.group(1).strip()[:70]}"))
    return out


def location_rules(location: str, remote: bool | None, c: Candidate) -> list[tuple[str, str]]:
    loc = (location or "").strip()
    if not loc:
        return []
    if remote or _HOME.search(loc):
        return [(YES, f"location works from {c.country}: {loc[:40]}")]
    if _ABROAD.search(loc):
        return [(NO, f"based in {loc[:40]} — you would need the right to work there")]
    return [(CHECK, f"location: {loc[:40]}")]


_SENIOR = re.compile(r"\b(senior|sr\.?|principal|staff engineer|director|head of|vice president|vp)\b", re.I)
_STUDENT_TITLE = re.compile(r"\b(intern|internship|trainee|student|fresher|graduate|apprentice|co-?op)\b", re.I)


def title_rules(title: str, c: Candidate) -> list[tuple[str, str]]:
    """A "Senior .Net Developer" posting was listed to a 2nd-year student as a 10/10 remote fit. The
    title is where seniority is stated, and a senior title on a non-student role is a years-of-experience
    rule in everything but name."""
    t = title or ""
    if _SENIOR.search(t) and not _STUDENT_TITLE.search(t):
        return [(NO, f"a senior role ({_SENIOR.search(t).group(1)}) — it expects years of experience")]
    return []


# ─── rules from Unstop's structured eligibility ───────────────────────────────────────────────
def unstop_rules(detail: dict, c: Candidate) -> list[tuple[str, str]]:
    """Unstop states eligibility as data: allowed courses, each with its passout years."""
    out: list[tuple[str, str]] = []
    reg = detail.get("regnRequirements") or {}
    el = reg.get("eligibility")
    if isinstance(el, str):
        try:
            el = json.loads(el)
        except ValueError:
            el = None

    if isinstance(el, dict):
        courses = []
        for group, entries in el.items():
            if not isinstance(entries, list):
                continue
            for e in entries:
                if isinstance(e, dict) and e.get("course"):
                    courses.append((group, str(e["course"]).lower(), [str(y) for y in e.get("passoutYear") or []]))
                elif e == "allCourses":
                    courses.append((group, "all", ["all"]))
        if courses:
            mine = [x for x in courses if x[1] in (c.course, "all") and x[0] in ("engineering", "others")]
            mine = mine or [x for x in courses if x[1] == c.course]
            if not mine:
                names = sorted({x[1] for x in courses})[:6]
                eng_listed = any(g == "engineering" for g, _, _ in courses)
                if eng_listed or "all" not in [str(o).lower() for o in el.get("others") or []]:
                    out.append((NO, f"open to courses {', '.join(names)} — not B.Tech"))
                else:
                    # Engineering left empty beside "others: all" — the commonest shape on Unstop, and
                    # not a clear exclusion. Say so and send him to the page instead of hiding the job.
                    out.append((CHECK, f"courses listed: {', '.join(names)} — B.Tech not named, "
                                       f"though 'others' is open to all"))
            else:
                years = {y for _, _, ys in mine for y in ys}
                if years and "all" not in years and str(c.grad_year) not in years:
                    out.append((NO, f"passout years {', '.join(sorted(years))}; you graduate {c.grad_year}"))
                else:
                    out.append((YES, f"B.Tech, passout {c.grad_year} accepted"))
        exp = [e for e in el.get("experience") or [] if str(e).lower() != "all"]
        out += who_rules(el.get("sector") or [], exp)

    # Unstop codes gender as single letters in a list: ['A'] means All. The first version iterated a
    # string and reported "restricted to: a". A restriction is reported as a CHECK for him to read —
    # never inferred from his name or anything else not stated.
    raw_g = reg.get("gender") or []
    raw_g = [raw_g] if isinstance(raw_g, str) else raw_g
    names = {"a": "all", "f": "women", "m": "men", "o": "other", "t": "transgender"}
    genders = [names.get(str(g).strip().lower(), str(g).strip().lower()) for g in raw_g if str(g).strip()]
    if genders and not any(g in ("all", "any") for g in genders):
        out.append((CHECK, f"registration restricted to: {', '.join(genders)}"))
    if reg.get("allow_specific_cities"):
        out.append((CHECK, "registration limited to specific cities"))

    filters = [str(f.get("name", "")).lower() for f in detail.get("filters") or [] if isinstance(f, dict)]
    if filters and all(f in ("postgraduate", "mba", "management") for f in filters):
        out.append((NO, f"for {', '.join(filters)} only"))
    return out


def team_note(detail: dict) -> str:
    reg = detail.get("regnRequirements") or {}
    lo, hi = reg.get("min_team_size"), reg.get("max_team_size")
    try:
        lo, hi = int(lo or 1), int(hi or lo or 1)
    except (TypeError, ValueError):
        return ""
    return f"needs a team of {lo}–{hi}" if lo > 1 else ""


# ─── the verdict ──────────────────────────────────────────────────────────────────────────────
def assess(c: Candidate, text: str = "", location: str = "", remote: bool | None = None,
           unstop: dict | None = None) -> Verdict:
    reasons = text_rules(text, c) + location_rules(location, remote, c)
    if unstop:
        reasons += unstop_rules(unstop, c)
    seen, uniq = set(), []
    for lvl, why in reasons:
        if why not in seen:
            seen.add(why)
            uniq.append((lvl, why))
    order = {NO: 0, CHECK: 1, YES: 2}
    uniq.sort(key=lambda r: order.get(r[0], 3))
    if any(l == NO for l, _ in uniq):
        level = NO
    elif any(l == CHECK for l, _ in uniq):
        level = CHECK
    elif uniq:
        level = YES
    else:
        level = NOT_STATED
    return Verdict(level, uniq)


def from_description(text: str, c: Candidate) -> Verdict:
    """Cheap, offline verdict from a stored description — for ranking lists without a network call.
    Understands the "Eligibility: …; courses: …; passout: …" line Unstop items carry."""
    reasons = text_rules(text, c)
    m = re.search(r"courses:\s*([^;|]+)", text or "", re.I)
    if m:
        body = m.group(1)
        cut = bool(re.search(r"\+\d+ more", body))
        courses = [x.strip().lower() for x in re.sub(r"\(\+\d+ more\)", "", body).split(",") if x.strip()]
        # Items stored before 2026-09-27 kept only the first SIX courses alphabetically, which cut btech
        # from nearly every list; a list that may have been cut cannot prove "not open to B.Tech".
        cut = cut or len(courses) >= _OLD_CAP
        if courses and any(x in (c.course, "allcourses", "allengineering", "all") or c.course in x
                           for x in courses):
            reasons.append((YES, "open to B.Tech"))
        elif courses and not cut:
            # CHECK, not NO: 65 of 76 live Unstop listings leave the engineering group EMPTY, usually
            # beside "others: all", and this one line cannot tell that apart from a real exclusion.
            # The full listing (unstop_rules) can, and the pack shows its verdict.
            reasons.append((CHECK, f"courses listed: {', '.join(courses[:5])} — B.Tech not named"))
    p = re.search(r"passout:\s*([^;|]+)", text or "", re.I)
    if p:
        years = sorted({int(y) for y in _YEAR.findall(p.group(1))})
        # The same old cap kept the EARLIEST six years, so a missing late year proves nothing.
        if years and c.grad_year in years:
            reasons.append((YES, f"passout {c.grad_year} accepted"))
        elif years and (c.grad_year < years[0] or len(years) < _OLD_CAP):
            reasons.append((NO, f"passout years {', '.join(map(str, years))}; you graduate {c.grad_year}"))
    reasons += _stored_who_rules(text)
    loc = re.search(r"Location:\s*([^|]+)", text or "")
    if loc:
        reasons += location_rules(loc.group(1), "remote/wfh" in (text or "").lower(), c)
    return assess(c, "", "", None, None) if not reasons else _verdict(reasons)


_SECTORS = {"students", "student", "fresher", "freshers", "corporates", "professionals", "school",
            "college", "all"}


def _stored_who_rules(text: str) -> list[tuple[str, str]]:
    """Who may apply and how much experience, from the stored "Eligibility:" field — in both shapes the
    source has written: "open to: corporates; experience: 2 years" (labelled, from 2026-09-27) and the
    older "corporates; 1 year, 2 years, 3 years". The same two rules unstop_rules applies to the full
    listing; without them a job for people with 2–3 years of work was listed to him as a 10/10 fit."""
    m = re.search(r"Eligibility:\s*([^|]+)", text or "")
    if not m:
        return []
    sectors, exp = [], []
    for seg in (s.strip().lower() for s in m.group(1).split(";")):
        body = re.sub(r"^(open to|experience):\s*", "", seg)
        toks = [t.strip() for t in body.split(",") if t.strip()]
        if toks and (seg.startswith("open to:") or all(t in _SECTORS for t in toks)):
            sectors = toks
        elif toks and (seg.startswith("experience:") or all(re.fullmatch(r"\d+ years?", t) for t in toks)):
            exp = toks
    return who_rules(sectors, exp)


def who_rules(sectors: list, experience: list) -> list[tuple[str, str]]:
    """Unstop's `sector` and `experience` — ONE implementation for the stored line and the full listing,
    because the two drifted: the full-listing path read `regnRequirements.experience`, which is empty in
    88 of 88 live listings, while the real field is `eligibility.experience` (["1 year", "2 years"]).
    "fresher" there means already graduated, so it does not cover a 2nd-year student."""
    sec = [str(s).strip().lower() for s in sectors or [] if str(s).strip()]
    yrs = [int(m.group()) for m in (re.match(r"\d+", str(e).strip()) for e in experience or []) if m]
    students_ok = not sec or any(s in ("students", "student", "all") for s in sec)
    out: list[tuple[str, str]] = []
    if not students_ok:
        out.append((NO, f"open to {', '.join(sec)}, not students"))
    if yrs and min(yrs) > 0:
        need = f"{min(yrs)}+ year{'s' if min(yrs) > 1 else ''} of experience"
        # With students also allowed, the experience line most likely applies to the others.
        out.append((CHECK, f"lists {need}, though students may apply") if students_ok and sec
                   else (NO, f"needs {need}"))
    return out


def _verdict(reasons):
    order = {NO: 0, CHECK: 1, YES: 2}
    reasons = sorted(dict.fromkeys(reasons), key=lambda r: order.get(r[0], 3))
    level = NO if any(l == NO for l, _ in reasons) else CHECK if any(l == CHECK for l, _ in reasons) \
        else YES if reasons else NOT_STATED
    return Verdict(level, list(reasons))
