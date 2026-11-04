"""
Referral outreach — prepared for him to send by hand (4 Nov 2026). Research: docs/PLAN-referrals.md.

A referred candidate was hired 1 in 16 times, against 1 in 152 who applied through a careers site
(Lever's data, via SHRM, 2016). LinkedIn gives a free account three personalised connection notes a
month, 200 characters each (its help page, read 4 Nov). So every pack gets outreach.md: the contacts
the employer published, who to look for and links he opens himself, and the messages — a note for one
of his three, the ask after they accept, one follow-up — from the same evidence rows as the resume.

It never contacts anyone, never fetches LinkedIn or a search engine, and never looks up a person's
phone number or personal mail: LinkedIn's User Agreement bans bots and scraping, and his account is
how his posts reach people. Relationships are tracked in the linkedin-agent's connect.py, not here.
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import quote_plus

from .apply import _clip

NOTE_LIMIT = 200            # LinkedIn help, answer 46662: "up to 200 characters" (it names no Premium length)
NOTES_A_MONTH = 3
# Phrases that make a note read as a mass invite — the same list as the linkedin-agent's connect.py.
FILLER = re.compile(r"\b(I'd love to connect|love to connect|expand my network|touch base|reach out to you|"
                    r"as a fellow|I hope this finds you|circle back|synergy|pick your brain)\b", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_NOREPLY = re.compile(r"no-?reply|donotreply|do-not-reply|^notifications?@|mailer-daemon", re.I)
# (in the job title, the people on that team, the role in a few words for the 200-character note)
_ROLE = [(r"machine learning|\bml\b|\bai\b|artificial intelligence|llm|genai|deep learning",
          "Machine Learning Engineer", "ML"),
         (r"data scien", "Data Scientist", "data science"), (r"data analy", "Data Analyst", "data"),
         (r"back-?end", "Backend Engineer", "backend"), (r"front-?end", "Frontend Engineer", "frontend"),
         (r"full[- ]?stack", "Software Engineer", "full-stack"), (r"devops|cloud|sre\b", "DevOps Engineer", "DevOps"),
         (r"security", "Security Engineer", "security"), (r"research", "Research Engineer", "research")]


def published_emails(text: str) -> list[str]:
    """Addresses the employer itself put in the posting ("send your CV to careers@…"), no-reply ones
    dropped. The only email OPH ever offers him: one somebody chose to publish for applicants."""
    out = []
    for m in _EMAIL.finditer(text or ""):
        e = m.group(0).rstrip(".").lower()
        if not _NOREPLY.search(e) and e not in out and not e.endswith((".png", ".jpg", ".jpeg", ".gif")):
            out.append(e)
    return out[:3]


def role_title(job_title: str) -> str:
    """The title of the people on that team — the ones who refer."""
    return _role(job_title)[0]


def _role(job_title: str) -> tuple[str, str]:
    low = (job_title or "").lower()
    return next(((r, s) for rx, r, s in _ROLE if re.search(rx, low)), ("Software Engineer", "software"))


def plain_title(title: str) -> str:
    """"Software Engineer Intern — ArangoDB" → "Software Engineer Intern" (the board adds the company)."""
    return re.split(r"\s+[—–]\s+", title or "")[0].strip() or "this role"


def people_to_find(company: str, job_title: str) -> list[tuple[str, str, str]]:
    """(who, why them, the search words), warmest first."""
    r = role_title(job_title)
    return [(f"SRM alumni at {company}", "a shared college is the warmest cold contact there is",
             f"{company} SRM Institute of Science and Technology"),
            (f"A {r} at {company}", "people on the team are the ones who refer — and many companies pay "
             "them a bonus for it", f"{company} {r}"),
            ("The engineering manager or tech lead", "they decide who gets interviewed",
             f"{company} engineering manager"),
            ("A technical recruiter", "they route referrals and know the timeline", f"{company} technical recruiter")]


def links(words: str, google: str) -> dict[str, str]:
    """Search pages HE opens. OPH never fetches them."""
    return {"LinkedIn": "https://www.linkedin.com/search/results/people/?keywords=" + quote_plus(words),
            "Google": "https://www.google.com/search?q=" + quote_plus(f"site:linkedin.com/in {google}")}


def hiring_posts(city: str = "") -> list[tuple[str, str]]:
    """(label, url) — the last 24 h of "hiring intern" POSTS, newest first (4 Nov). Many startups post a
    role before, or instead of, a listing; the tip is to search Posts, not the Jobs tab, and comment or
    DM the poster. Links he opens on his phone; OPH never fetches them."""
    li = lambda q: ("https://www.linkedin.com/search/results/content/?keywords=" + quote_plus(q)
                    + "&datePosted=%22past-24h%22&sortBy=%22date_posted%22")
    out = [("AI/ML", li("hiring intern AI ML")), ("software", li("hiring software intern India")),
           ("remote", li("hiring remote intern developer"))]
    if city:
        out.append((city, li(f"hiring intern {city}")))
    return out + [("on X", "https://x.com/search?f=live&q=" + quote_plus("hiring intern (AI OR ML OR developer) India"))]


def jobs_link(company: str, job_title: str) -> str:
    """The same role on LinkedIn Jobs, where the posting may show "Meet the hiring team"."""
    return "https://www.linkedin.com/jobs/search/?keywords=" + quote_plus(f"{company} {plain_title(job_title)}")


def _desc(profile: dict) -> dict[str, str]:
    """Project name → its one-line description, ready to follow a comma ("an agent memory…"); an
    acronym first ("MCP permission layer…") keeps its case."""
    out = {}
    for p in profile.get("projects") or []:
        d = (p.get("description") or "").strip().rstrip(".")
        first = d.split(" ", 1)[0] if d else ""
        out[(p.get("name") or "").lower()] = d if (len(first) > 1 and first.isupper()) else d[:1].lower() + d[1:]
    return out


def _lead(profile: dict, rows: list) -> tuple[str, str]:
    """(project, its one-line description): the described project that answers the earliest ask, else
    his first described project. "LeetCode solutions" answers asks but is not a thing he built."""
    desc = _desc(profile)
    answered = [proj for _, _, ev, proj in rows or [] if proj and ev]
    for proj in answered:
        if desc.get(proj.lower()) and not _NOT_BUILT.search(proj):
            return proj, desc[proj.lower()]
    if answered:
        return answered[0], ""
    p = next((p for p in profile.get("projects") or [] if p.get("description")), {})
    return p.get("name", ""), desc.get((p.get("name") or "").lower(), "")


def _on_github(profile: dict, names: list[str]) -> bool:
    """Every named project has a GitHub repo the profile says is public. nova-cortex is private: "the code
    is on his GitHub" was a 404 for the referrer who checked (5 Nov). Unknown (None) counts as private."""
    by = {(p.get(k) or "").lower(): p for p in profile.get("projects") or [] for k in ("name", "x_resume_name")}
    return bool(names) and all("github.com/" in (by.get(n.lower()) or {}).get("url", "")
                               and by[n.lower()].get("private") is False for n in names)


def _short(ev: str, n: int = 130) -> str:
    """His sentence up to its first clause break, when that leaves enough to stand on its own; a long
    list is cut at its last comma, never mid-item ("…Merge k…")."""
    for sep in (" — ", "; "):
        head = ev.split(sep, 1)[0]
        if 40 <= len(head) < len(ev):
            ev = head.rstrip(".") + "."
            break
    if len(ev) > n:
        head = ev[:n].rsplit(", ", 1)[0]
        if len(head) >= 40:
            return head.rstrip(".") + "."
    return _clip(ev, n)


_NOT_BUILT = re.compile(r"leetcode|solutions|practice|exercises|course", re.I)   # answers asks, not a thing he built


def note(profile: dict, rows: list, company: str, job_title: str) -> str:
    """The connection note, under NOTE_LIMIT: who he is, the role, one thing he built, one small ask."""
    proj, d = _lead(profile, rows)
    abbr = _role(job_title)[1]
    full, short = plain_title(job_title), abbr + (" internship" if "intern" in job_title.lower() else " role")
    # What he built says the most in 200 characters, so the role's wording is shortened before it goes.
    for dd, r in ((d, full), (d, short), ("", full), ("", short)):
        built = f" I built {proj}" + (f", {dd}" if dd else "") + "." if proj else ""
        text = (f"Hi [Name], I'm a 2nd-year CSE student at SRM, applying to {company}'s {r}.{built} "
                f"Could I ask you one question about the team?")
        if len(text) <= NOTE_LIMIT:
            return text
    return text[:NOTE_LIMIT]


def referral_ask(rows: list, company: str, job_title: str, url: str) -> str:
    """After they accept: a message to a connection, which no monthly limit counts."""
    from .cover import joined  # noqa: PLC0415 — the cover letter's way of joining a project to his sentence
    hits = [(line, ev, proj) for _, line, ev, proj in rows or [] if proj and ev][:2]
    L = ["Hi [Name], thanks for connecting.", "",
         f"I'm applying for the {plain_title(job_title)} at {company}" + (f": {url}" if url else ".")]
    if hits:
        L += ["Two things from my own work that match what it asks for:"]
        for line, ev, proj in hits:
            s = _short(ev)          # "34 LeetCode problems…" already names it: no "LeetCode solutions: 34 LeetCode…"
            L += [f"- “{_clip(line.rstrip('.'), 70)}”: "
                  + (s if proj.split()[0].lower() in s[:40].lower() else joined(proj, s))]
    L += ["", "If you're comfortable referring me, I'll send my resume and two lines you can paste into "
          "the referral form. If it's not something you do, no problem, and one line on what the team "
          "looks for would still help.", "", "Thanks,", "K Mohith Kannan"]
    return "\n".join(L).replace("**", "")


def follow_up(company: str, job_title: str) -> str:
    return (f"Hi [Name], a short follow-up about the {plain_title(job_title)} at {company}. I can send "
            f"anything that makes a referral easier. Thanks either way.")


def blurb(profile: dict, rows: list, job_title: str) -> str:
    """Two lines the employee pastes into their company's referral form."""
    srm = next((e for e in profile.get("education", []) if "srm" in (e.get("institution") or "").lower()), {})
    desc = _desc(profile)
    proj, d = _lead(profile, rows)
    # Only things he built: a second answered project with a description, never "LeetCode solutions".
    rest = [p for _, _, ev, p in rows or [] if p and ev and p != proj and desc.get(p.lower())
            and not _NOT_BUILT.search(p)][:1]
    built = (f"Built {proj}" + (f", {d}" if d else "") + (f", and {rest[0]}, {desc[rest[0].lower()]}" if rest else "")
             + "." + (" The code is on his GitHub." if _on_github(profile, [proj, *rest]) else "")) if proj else ""
    # The referrer writes about him, so his own descriptions ("finds internships … for me") turn third-person.
    built = re.sub(r"\bmy\b", "his", re.sub(r"\bme\b", "him", re.sub(r"\bI\b", "he", built)))
    return (f"K Mohith Kannan, second-year B.Tech CSE (AI & ML) at SRM Institute of Science and Technology"
            + (f", graduating {srm.get('endDate')}" if srm.get("endDate") else "")
            + f", applying for the {plain_title(job_title)}. " + built).strip()


def email(profile: dict, rows: list, company: str, job_title: str, to: str) -> str:
    """Only for an address the posting published."""
    mail = (profile.get("basics") or {}).get("email", "")
    body = referral_ask(rows, company, job_title, "").split("\n", 2)[2]     # drop the "thanks for connecting"
    body = body.replace("If you're comfortable referring me, I'll send my resume and two lines you can paste "
                        "into the referral form. If it's not something you do, no problem, and one line on "
                        "what the team looks for would still help.",
                        "My resume is attached. I'd be glad to answer anything about this work.")
    return (f"To: {to}\nSubject: {plain_title(job_title)} — K Mohith Kannan, SRM (CSE, AI & ML)\n\n"
            f"Hello,\n\n{body}" + (f"\n{mail}" if mail else ""))


def problems(text: str) -> list[str]:
    """Reasons a message would read as a template. [] = fine."""
    from .voice import lint  # noqa: PLC0415
    out = [f"template filler: {m}" for m in sorted({m.group(0) for m in FILLER.finditer(text)})]
    return out + [p for p in lint(text.replace("[Name]", "them")) if not p.startswith("em-dash")]


def outreach_md(item: dict, full: dict | None, profile: dict, rows: list | None, company: str) -> str:
    full = full or {}
    title = item.get("title", "")
    co = company or "the company"
    url = full.get("apply_url") or item.get("url", "")
    n = note(profile, rows, co, title)
    L = [f"# Ask for a referral — {plain_title(title)} at {co}", "",
         "_Prepared, never sent. A referred candidate was hired 1 in 16 times, against 1 in 152 who applied "
         "through a careers site (Lever's data, via SHRM, 2016). Send these yourself, by hand._", ""]
    mails = published_emails(f"{full.get('description', '')}\n{item.get('description', '')}")
    if mails:
        L += ["## Contacts the employer published", "",
              *[f"- {m} — from the posting itself" for m in mails], ""]
    L += ["## Who to look for, in this order", "",
          f"First, check whether this role is on LinkedIn too — [LinkedIn Jobs]({jobs_link(co, title)}). If the "
          "posting shows **Meet the hiring team**, those are the people to message, from the job page.", ""]
    for who, why, words in people_to_find(co, title):
        g = f'"{co}" ' + (f'"{words[len(co):].strip()}"' if words.startswith(co) else f'"{words}"')
        L += [f"**{who}** — {why}. " + " · ".join(f"[{k}]({v})" for k, v in links(words, g).items()), ""]
    L += ["## The messages", "",
          f"**Your notes: {NOTES_A_MONTH} a month on a free account, {NOTE_LIMIT} characters each.** Spend one "
          "on the person who matters most for this job (the hiring team, if LinkedIn shows one). Send everyone "
          "else a request with no note, then write after they accept: a message to a connection is not a note.",
          "", f"### 1. The connection note ({len(n)} of {NOTE_LIMIT} characters)", "", "```", n, "```", "",
          "### 2. After they accept: the referral ask", "", "```", referral_ask(rows, co, title, url), "```", "",
          "### 3. A week later, once: the follow-up", "", "```", follow_up(co, title), "```", "",
          "### 4. What they can paste into the referral form", "", "```", blurb(profile, rows, title), "```", ""]
    if mails:
        L += ["### Email, to the address the posting gave", "", "```", email(profile, rows, co, title, mails[0]),
              "```", ""]
    slug_title = plain_title(title).replace('"', "'")
    # connect.py's own three headings (linkedin-agent, 4 Nov), so the blocks below are a straight copy over
    # its template; `connect.py check` refuses a file that still has the template's text.
    L += ["## Track it (in the linkedin-agent)", "", "```",
          f'python connect.py add "[Their name]" --role "[their role]" --org "{co}" '
          f'--why "OPH pack: {slug_title}, {date.today().isoformat()}"', "```",
          "In the file it makes, replace everything under `## Who` with these three blocks, fill the brackets "
          "with what you can check on their profile, then `python connect.py check <slug>`.", "",
          "~~~markdown", "## Who", "",
          f"[Their name], [their role] at {co}. [One thing from their profile or posts you can check.]", "",
          "## Why reach out", "",
          f"I'm applying for the {plain_title(title)} at {co}. [The part of their work this role touches.]", "",
          "## The note (send this by hand)", "", "```", n, "```", "~~~", "",
          "Then `python connect.py status <slug> sent` when you send, `replied` when they answer.", "",
          "## Never", "",
          "- Never pay anyone for a referral. Paid \"referrals\" are a known scam.",
          "- Never send requests or messages with a tool or extension. LinkedIn restricts accounts for it, "
          "and your account is how your posts reach people.",
          "- Never hunt for someone's personal phone number or personal email. If they share contact info "
          "with connections, you'll see it once they accept.", ""]
    return "\n".join(L)
