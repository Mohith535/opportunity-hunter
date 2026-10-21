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

# Where a role can be held from India without a visa, in the listing's own words. "Remote" is NOT in
# here: until 21 Oct it was, so "Remote in Canada" read as "works from India" and a Canadian co-op
# (StackAdapt) reached him as a 10/10 — remote only means "from home" for someone allowed to work there.
_INDIA = re.compile(r"\b(india|mumbai|bombay|bengaluru|bangalore|chennai|hyderabad|pune|delhi|new delhi|"
                    r"noida|gurgaon|gurugram|kolkata|ahmedabad|jaipur|kochi|chandigarh|coimbatore|indore|"
                    r"thiruvananthapuram|trivandrum|visakhapatnam|bhubaneswar|nagpur|lucknow|mysuru|mysore|"
                    r"mangaluru|madurai|vellore)\b", re.I)
_WORLD = re.compile(r"\b(worldwide|anywhere|global(?:ly)?|any country|all countries)\b", re.I)
_REMOTE = re.compile(r"\b(remote|work from home|wfh|online|distributed)\b", re.I)
_CODES = re.compile(r"\b(US|USA|UK|EU|EMEA|UAE|NYC)\b")      # case-sensitive, location strings only
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
    # His rule (21 Oct): "I am really okay to work in other countries and states, if they accept."
    # So a place abroad is a CHECK for him, never a NO by itself — only a stated restriction is.
    open_to_relocate: bool = False
    work_rights: tuple = ("India",)

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
                NOT_STATED: "RULES NOT STATED — VERIFY"}[self.level]

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
    if target and target.get("open_to_relocate") is not None:
        c.open_to_relocate = bool(target["open_to_relocate"])
    if target and target.get("work_rights"):
        c.work_rights = tuple(str(x) for x in target["work_rights"])
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

    # "Currently pursuing an MBA with a specialization in Operations…" (EA Hyderabad, 21 Oct) — the
    # listing said "Intern", the posting says MBA. A bachelor's student is out unless it says "or".
    if c.degree == "bachelor":
        for s in _sentences(text):
            sl = s.lower()
            g = re.search(r"\b(?:pursuing|enrolled in|studying)\s+(?:an?\s+)?(mba|master'?s(?: degree)?|masters|"
                          r"m\.?\s?tech|ph\.?\s?d)\b", sl)
            if g and not re.search(r"\bor\s+(?:an?\s+)?(?:bachelor|undergrad|b\.?\s?tech)|"
                                   r"(?:bachelor'?s?|undergraduate|b\.?\s?tech)\s+or\b", sl):
                out.append((NO, f"for students pursuing {'an MBA' if g.group(1) == 'mba' else 'a ' + g.group(1)}"))
                break

    no_sponsor = _NO_SPONSOR.search(low)
    if re.search(r"authori[sz]ed to work in the (united states|us|u\.s\.)|us work authori[sz]ation", low) and no_sponsor:
        out.append((NO, "needs US work authorisation, and sponsorship is not offered"))
    else:
        a = _AUTH.search(text or "")
        place = (a.group(1).strip(" .") if a else "")
        if a and no_sponsor and not _INDIA.search(place) and place.lower() not in [w.lower() for w in c.work_rights]:
            out.append((NO, f"needs the right to work in {place[:30]}, and it does not sponsor visas"))
        elif no_sponsor:
            out.append((CHECK, "says it does not sponsor visas — fine only if the role is in India or remote from India"))
    if not no_sponsor and _SPONSOR.search(low):
        out.append((YES, "offers visa sponsorship or relocation support"))
    for rx, why in ((_CITIZEN, "needs citizenship or a security clearance"),
                    (_COOP, "needs enrolment in a co-op program at a university in that country")):
        hit = rx.search(text or "")
        if hit:
            out.append((NO, f"{why} (\"{hit.group(0)[:40]}\")"))
    r = _RESIDE.search(text or "")
    if r and (_ABROAD.search(r.group(1)) or _CODES.search(r.group(1))) and not _INDIA.search(r.group(1)):
        out.append((NO, f"you must live in {r.group(1).strip()[:30]}"))
    m = re.search(r"from a university in ([a-z ]+?)\s*\(required\)", low)
    if m and m.group(1).strip() != c.country.lower():
        out.append((NO, f"must be enrolled at a university in {m.group(1).strip().title()}"))

    fm = re.search(r"degree in ([^.;]{5,160})", low)
    if fm and not re.search(r"computer|software|engineering|informatics|information|data|math|"
                            r"electr|stem|technical|related field|equivalent", fm.group(1)):
        out.append((CHECK, f"asks for a degree in {fm.group(1).strip()[:70]}"))
    return out


def location_rules(location: str, remote: bool | None, c: Candidate) -> list[tuple[str, str]]:
    """Where the job is, against where he can work. A listing may name several places ("Bengaluru;
    Remote in USA"): the best one decides, because he only needs one he can take.

    Abroad is a NO only for someone who would not move. He would (21 Oct), so for him it is a CHECK
    that says what to look for — the restriction that hides a job is a STATED one (text_rules)."""
    loc = (location or "").strip()
    if not loc:
        return []
    found: list[tuple[str, str]] = []
    for p in [x.strip() for x in re.split(r"[;|]|\s+or\s+|\s+/\s+", loc) if x.strip()] or [loc]:
        far = _ABROAD.search(p) or _CODES.search(p)
        if _INDIA.search(p) or _WORLD.search(p):
            return [(YES, f"location works from {c.country}: {p[:40]}")]
        if far and _REMOTE.search(p):
            where = far.group(0).strip(" ,")
            found.append((CHECK, f"remote only from inside {where} — needs them to hire from abroad")
                         if c.open_to_relocate else
                         (NO, f"remote only from inside {where} — you would need to live there with the right to work"))
        elif far:
            found.append((CHECK, f"abroad ({p[:40]}) — you are open to moving; check they accept international applicants")
                         if c.open_to_relocate else
                         (NO, f"based in {p[:40]} — you would need the right to work there"))
        elif _REMOTE.search(p) or remote:
            # A structured remote flag comes from Unstop's work-from-home field (an India-only site);
            # the bare word in prose does not say from where.
            found.append((YES, f"location works from {c.country}: {p[:40]}") if remote else
                         (CHECK, f"remote, country not stated: {p[:40]} — check you may work from {c.country}"))
        else:
            found.append((CHECK, f"location: {p[:40]}"))
    best = min((_RANK[lvl] for lvl, _ in found), default=None)
    return [r for r in found if _RANK[r[0]] == best]


_RANK = {YES: 0, CHECK: 1, NO: 2}


def remote_abroad(text: str) -> str:
    """The foreign place a "remote" is tied to — "Remote in Canada", "Remote - US", "USA (Remote)" — or
    "". A window around the word, not the whole text: "offices in London and Bengaluru, remote OK"
    must not turn into remote-only-from-London."""
    for m in _REMOTE.finditer(text or ""):
        window = text[max(0, m.start() - 25): m.end() + 30]
        far = _ABROAD.search(window) or _CODES.search(window)
        if far and not _INDIA.search(window) and not _WORLD.search(window):
            return far.group(0).strip(" ,")
    return ""

# Stated restrictions. Asking "are you authorised to work here / do you need sponsorship?" is on nearly
# every form and is NOT a restriction by itself (career-ops draws the same line); refusing to sponsor,
# demanding citizenship, a clearance, a local co-op or local residence is.
_NO_SPONSOR = re.compile(
    r"sponsorship is not (?:available|offered|provided)|\bno (?:visa |immigration |employment )?sponsorship|"
    r"\b(?:unable|not able) to (?:offer |provide )?(?:visa |immigration )?sponsor|"
    r"\b(?:do|does|will|can) not (?:offer |provide )?(?:visa |immigration |employment )?sponsor|"
    r"\bcannot (?:offer |provide )?(?:visa |immigration )?sponsor|"
    r"without (?:the need for |requiring |needing )?(?:current or future )?(?:visa |employer |employment )?sponsorship",
    re.I)
_SPONSOR = re.compile(r"(?:visa |immigration )?sponsorship (?:is )?(?:available|provided|offered)|"
                      r"\b(?:we|will|can) sponsor\b|\boffers? (?:visa )?sponsorship|"
                      r"relocation (?:assistance|support|package|bonus|stipend)", re.I)
_AUTH = re.compile(r"(?:authori[sz]ed|eligible|permitted) to work (?:in|for) (?:the )?([A-Za-z .]{2,30}?)"
                   r"(?=[.;,)\n]| without| on | and | for |$)", re.I)
_CITIZEN = re.compile(r"u\.?s\.? citizenship (?:is )?required|citizenship (?:is )?required|\bcitizens only\b|"
                      r"must be an? (?:u\.?s\.?|us|american|canadian|uk|british|australian|eu) citizen|"
                      r"security clearance|\bitar\b|u\.?s\.? persons? only", re.I)
_COOP = re.compile(r"(?:enrolled|registered|participating) in (?:an? )?(?:accredited |recognized |recognised |"
                   r"post-secondary )?co-?op(?:erative)?(?: education)? program|accredited co-?op|"
                   r"(?:official|mandatory|required) co-?op (?:work )?term", re.I)
_RESIDE = re.compile(r"must (?:currently )?(?:be (?:based|located|residing)|reside|live) in (?:the )?"
                     r"([A-Za-z .]{2,40}?)(?=[.;,)\n]|$| to | and | for | with )", re.I)


def form_rules(questions: list[str], c: Candidate) -> list[tuple[str, str]]:
    """Rules hidden in the application form, which Greenhouse publishes with `?questions=true`. The
    StackAdapt form asked about an accredited co-op and the province he would work from — none of it in
    the posting text, all of it visible to a program that reads the form."""
    out: list[tuple[str, str]] = []
    for q in questions or []:
        low = q.lower()
        if re.search(r"co-?op", low) and re.search(r"enrol|accredit|program|term", low):
            out.append((NO, "its application form asks if you are in a local co-op program"))
        elif re.search(r"province|territory", low) and re.search(r"work|reside|live|located", low):
            out.append((CHECK, "its form asks which province/territory you will work from — it expects you inside that country"))
        elif re.search(r"citizen|security clearance|\bitar\b", low):
            out.append((CHECK, "its form asks about citizenship or a security clearance"))
    return list(dict.fromkeys(out))


def _escalate(reasons: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Two soft signals that together are a hard one: abroad + "we do not sponsor" is a closed door,
    and abroad + "we sponsor / relocate" is an open one."""
    abroad = [r for r in reasons if r[1].startswith(("abroad (", "remote only from inside"))]
    if abroad and any("does not sponsor" in w for _, w in reasons):
        return reasons + [(NO, "abroad, and it does not sponsor visas")]
    if abroad and any(w.startswith("offers visa sponsorship") for _, w in reasons):
        return [r for r in reasons if (r not in abroad or r[1].startswith("remote only"))
                and not r[1].startswith("offers visa sponsorship")] + \
               [(YES, "abroad, and it offers sponsorship or relocation")]
    return reasons


_SENIOR = re.compile(r"\b(senior|sr\.?|principal|staff engineer|director|head of|vice president|vp)\b", re.I)
_STUDENT_TITLE = re.compile(r"\b(intern|internship|trainee|student|fresher|graduate|apprentice|co-?op)\b", re.I)


def title_rules(title: str, c: Candidate) -> list[tuple[str, str]]:
    """A "Senior .Net Developer" posting was listed to a 2nd-year student as a 10/10 remote fit. The
    title is where seniority is stated, and a senior title on a non-student role is a years-of-experience
    rule in everything but name."""
    t = title or ""
    if _SENIOR.search(t) and not _STUDENT_TITLE.search(t):
        return [(NO, f"a senior role ({_SENIOR.search(t).group(1)}) — it expects years of experience")]
    # The big-company boards (21 Oct) name the degree in the title: "Software Engineering PhD Intern"
    # (Google), "AI/ML Software Engineer Intern (… - Masters - …)" (EA). He is in a bachelor's.
    if c.degree == "bachelor" and not re.search(r"bachelor|undergrad|b\.?tech|b\.?s\.?\b|or master|/master", t, re.I):
        if re.search(r"\bph\.?\s?d\b|doctoral", t, re.I):
            return [(NO, "the title says PhD students")]
        if re.search(r"\bmasters\b|\bmaster'?s (?:student|degree|program)|\bmsc\b", t, re.I):
            return [(NO, "the title says master's students")]
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
# A listing that says remote while its own posting says otherwise (career-ops' geo-mismatch check). Only
# binding attendance counts: "onsite interviews" or "our office in Pune" alone is not.
_ATTEND = re.compile(
    r"\b(?:\d|one|two|three|four|five)\s+days?\s+(?:a|per|each)\s+week\s+(?:in|at|from)\s+(?:the\s+|our\s+)?office\b"
    r"|\bhybrid\s+(?:role|position|work|model|schedule|setup|arrangement|internship)\b"
    r"|\b(?:work|working|based)\s+(?:from\s+)?on-?site\b|\bin-office\s+(?:role|position|work|internship)\b"
    r"|\bmust\s+(?:be\s+(?:willing|able)\s+to\s+)?relocate\b", re.I)


def attendance_rule(text: str, location: str, remote: bool | None) -> list[tuple[str, str]]:
    if not (remote or _REMOTE.search(location or "")):
        return []
    m = _ATTEND.search(text or "")
    return [(CHECK, f"listed as remote, but the posting says \"{m.group(0)}\"")] if m else []


def assess(c: Candidate, text: str = "", location: str = "", remote: bool | None = None,
           unstop: dict | None = None) -> Verdict:
    reasons = text_rules(text, c) + location_rules(location, remote, c) + attendance_rule(text, location, remote)
    if unstop:
        reasons += unstop_rules(unstop, c)
    reasons = _escalate(reasons)
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


_BUCKETS = [
    ("senior role", r"senior role"),
    ("not for students", r"not students"),
    ("graduation year", r"graduat|passout"),
    ("course", r"courses|b\.tech"),
    ("experience", r"experience"),
    ("year of study", r"year \d|junior|final-year"),
    ("PhD only", r"phd"),
    ("work rights / country", r"authori[sz]|right to work|university in|based in|citizen|clearance|"
                              r"co-op|sponsor|live in|inside|abroad"),
]


def reason_bucket(why: str) -> str:
    """A NO reason as a category — "graduation year", never "you graduate 2029". The daily run logs
    these counts, and in the cloud that log is public."""
    low = (why or "").lower()
    return next((name for name, pat in _BUCKETS if re.search(pat, low)), "other rule")


def _verdict(reasons):
    order = {NO: 0, CHECK: 1, YES: 2}
    reasons = sorted(dict.fromkeys(_escalate(list(reasons))), key=lambda r: order.get(r[0], 3))
    level = NO if any(l == NO for l, _ in reasons) else CHECK if any(l == CHECK for l, _ in reasons) \
        else YES if reasons else NOT_STATED
    return Verdict(level, list(reasons))


VERIFY_CAP = 8


def capped(score: int, verdict: Verdict, employment: bool) -> int:
    """A 9–10 says "go". For a job that needs a verdict saying he can apply: "rules not stated" and
    "check before applying" stay visible, at most an 8. StackAdapt reached him as a 10/10 with
    "RULES NOT STATED" printed right beside the score."""
    return min(score, VERIFY_CAP) if employment and verdict.level in (CHECK, NOT_STATED) else score
