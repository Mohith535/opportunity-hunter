"""
RENDER — resume.md into a PDF an ATS can read and a recruiter understands in three seconds.

Why this exists: his best resume, the Claude Campus Ambassador PDF, contains NO TEXT. Zero
extractable characters, zero fonts, 3,273 vector paths per page — `Microsoft: Print To PDF` drew
every letter as a shape. A human sees a beautiful page; Workday, Greenhouse and Lever see three blank
ones. So this renderer is built around one rule: a PDF is not produced until reading it back proves
the text is really there.

Why Typst: `pip install typst` is one wheel with the compiler inside — no LaTeX, no browser, no system
libraries — so the laptop and the cloud run produce the same file. It embeds real font subsets with
proper Unicode maps (verified: Calibri and Georgia subsets, name extracted as the first line).

Three settings exist purely for ATS parsers, and each costs nothing visible:
  * ligatures OFF — a parser that mishandles the "fi" glyph turns "certification" into "certiﬁcation"
    and the keyword stops matching. (His profile was once corrupted by exactly that glyph.)
  * hyphenation OFF — "Kuber-/netes" split across a line break is two non-words to a keyword search.
  * no columns — multi-column PDFs scramble text order; dates are pushed right with inline spacing
    on the SAME line, which reads left-to-right like any sentence.

PAGE 1 IS THE WHOLE STORY; PAGE 2 IS THE REWARD. Research behind the layout:
  * TheLadders eye-tracking (2018): 7.4 s on the first pass, 80% of it on six data points. So the
    header carries name, headline and graduation year, and the most relevant projects come next.
  * Loewenstein (1994) information-gap theory: curiosity peaks when you know a little but not all.
    So page 1 ends on one small open line naming what page 2 holds, in HIS OWN taglines ("an agent
    memory that is allowed to say no") — an invitation, not a gimmick, and every word already true.
  * Peak-end rule: the page ends on his closing line.
How many projects fit on page 1 is not guessed: the page is rendered, read back, and re-rendered
with one fewer project until the teaser line genuinely sits on page 1.

Usage:
    py -m resume.render applications/<pack>/resume.md            # -> resume.pdf + resume.docx
    py -m resume.render resume.md --out K_Mohith_Kannan_Resume.pdf --no-docx
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ─── palette + type (his PDF's look: serif name and rust section heads, clean sans body) ──────────
# Three tones, so hierarchy reads before a word is read: names darkest, prose a step lighter,
# metadata lighter still. One flat colour for everything was part of why it read as a wall.
INK, BODY, INK2, SOFT, ACCENT, RULE = ("#111111", "#2E2E2E", "#3A3A3A", "#6E6E6E",
                                      "#A8452E", "#D9D2CC")
BODY_FONTS = ("Calibri", "Carlito", "Segoe UI", "Liberation Sans", "DejaVu Sans", "Libertinus Serif")
HEAD_FONTS = ("Georgia", "Gelasio", "Liberation Serif", "Libertinus Serif")


# ─── parse the generator's Markdown ───────────────────────────────────────────────────────────────
@dataclass
class Project:
    name: str
    tagline: str = ""
    when: str = ""
    bullets: list[str] = field(default_factory=list)
    techline: str = ""


@dataclass
class Doc:
    name: str = ""
    headline: str = ""
    links: list[str] = field(default_factory=list)
    eduline: list[str] = field(default_factory=list)
    sections: list[tuple[str, list]] = field(default_factory=list)   # (title, blocks)
    closing: str = ""

    def projects(self) -> list[Project]:
        return [b for _, blocks in self.sections for b in blocks if isinstance(b, Project)]


_PROJECT = re.compile(r"^\*\*(?P<name>[^*]+)\*\*\s+—\s+(?P<rest>.+)$")
_ITALIC_LINE = re.compile(r"^\*(?P<body>[^*].*?)\*(?:\s+·\s+(?P<link>\S+))?$")


def parse(md: str) -> Doc:
    md = re.sub(r"(?s)^\s*<!--.*?-->\s*", "", md or "")          # the header note is for him, not them
    doc, section, blocks, proj = Doc(), None, None, None
    lines = md.splitlines()

    for raw in lines:
        line = raw.rstrip()
        s = line.strip()
        if s.startswith("## "):
            section, blocks, proj = s[3:].strip(), [], None
            doc.sections.append((section, blocks))
            continue
        if section is None:                                        # ── header ──
            if s.startswith("# "):
                doc.name = s[2:].strip()
            elif s.startswith("**") and s.endswith("**") and not doc.headline:
                doc.headline = s.strip("*").strip()
            elif s and ("@" in s or "github" in s.lower()):
                doc.links = [p.strip() for p in s.split("·") if p.strip()]
            elif s:
                doc.eduline.append(s)
            continue
        if not s:
            proj = None
            continue
        m = _PROJECT.match(s)
        if m and re.search(r"work|project", section.lower()):
            rest = m.group("rest")
            when = ""
            wm = re.search(r"\s+·\s+\*([^*]+)\*\s*$", rest)
            if wm:
                when, rest = wm.group(1).strip(), rest[:wm.start()].strip()
            proj = Project(m.group("name").strip(), rest, when)
            blocks.append(proj)
            continue
        if s.startswith("- "):
            (proj.bullets if proj else blocks).append(s[2:].strip() if proj else ("bullet", s[2:].strip()))
            continue
        im = _ITALIC_LINE.match(s)
        if im and proj:
            proj.techline = im.group("body").strip() + (f" · {im.group('link')}" if im.group("link") else "")
            continue
        if im and "education" in section.lower():
            doc.closing = im.group("body").strip()
            continue
        blocks.append(("para", s))
    return doc


# ─── Markdown inline -> Typst (every character of content goes in a string literal) ──────────────
def _lit(text: str) -> str:
    """A Typst string literal. Content never passes through Typst MARKUP, where #, *, _, $, @, <, [, ]
    and a leading - or = all mean something — so a bullet containing "C#" or "add()" cannot break."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _inline(text: str) -> str:
    out = []
    for tok in re.split(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)", text or ""):
        if not tok:
            continue
        if tok.startswith("**") and tok.endswith("**") and len(tok) > 4:
            out.append(f"#strong({_lit(tok[2:-2])})")
        elif tok.startswith("*") and tok.endswith("*") and len(tok) > 2:
            out.append(f"#emph({_lit(tok[1:-1])})")
        else:
            out.append(f"#{_lit(tok)}")
    return "".join(out)


def _href(item: str) -> str:
    item = item.strip()
    if "@" in item and " " not in item:
        return f"mailto:{item}"
    return item if item.startswith("http") else f"https://{item}"


# ─── Typst document ───────────────────────────────────────────────────────────────────────────────
def _is_skills(title: str) -> bool:
    return "skill" in title.lower()


def to_typst(doc: Doc, page1_projects: int | None = None, skills_on_p1: bool = False) -> tuple[str, str]:
    """(typst source, the teaser line or ''). With page1_projects=k, the first k projects end page 1,
    followed by a teaser naming the rest and a weak page break.

    skills_on_p1 lifts the Technical Skills block onto page 1, just before the teaser. TheLadders found
    recruiters spend the 20% of first-pass time that is NOT on the six data points scanning for
    keywords — and the skills block is the most keyword-dense thing on the page. The first render
    left a quarter of page 1 blank, and a half-empty first page reads as "not much to say"."""
    fonts = "(" + ", ".join(_lit(f) for f in BODY_FONTS) + ")"
    heads = "(" + ", ".join(_lit(f) for f in HEAD_FONTS) + ")"
    title = f"{doc.name.title()} — Resume" if doc.name else "Resume"
    T = [
        f"#set document(title: {_lit(title)}, author: {_lit(doc.name.title())})",
        '#set page(paper: "a4", margin: (x: 2.0cm, top: 1.7cm, bottom: 1.6cm))',
        f"#set text(font: {fonts}, size: 10pt, fill: rgb({_lit(BODY)}), lang: \"en\", "
        f"ligatures: false, hyphenate: false)",
        "#set par(justify: false, leading: 0.7em, spacing: 0.85em)",
        "#set list(marker: [•], indent: 0.2em, body-indent: 0.55em, spacing: 0.62em)",
        f"#show link: set text(fill: rgb({_lit(INK2)}))",
        f"#let sect(t) = block(above: 1.75em, below: 0.75em, breakable: false)["
        f"#text(font: {heads}, size: 10.5pt, weight: \"bold\", fill: rgb({_lit(ACCENT)}), "
        f"tracking: 0.07em)[#upper(t)] #v(-0.6em) "
        f"#line(length: 100%, stroke: 0.5pt + rgb({_lit(RULE)}))]",
    ]

    # ── the 3-second zone ──
    # Each header item is its OWN line, joined with Typst's explicit line break. In Typst markup a
    # single newline between two calls is only a space, so these were silently one paragraph — once
    # wider margins made the links wrap, "looplab.page" ran straight into the education line.
    # Order follows TheLadders' six fixation points: name, then headline (the "title" slot), then
    # education with the graduation year, and only then the contact links.
    head = [f"#text(font: {heads}, size: 23pt, weight: \"bold\")[#{_lit(doc.name)}]"]
    if doc.headline:
        head.append(f"#text(size: 10.5pt, weight: \"bold\", fill: rgb({_lit(INK)}))[#{_lit(doc.headline)}]")
    for e in doc.eduline:
        head.append(f"#text(size: 9.5pt, fill: rgb({_lit(INK2)}))[{_inline(e)}]")
    if doc.links:
        parts = [f"#link({_lit(_href(l))})[#{_lit(l)}]" for l in doc.links]
        head.append(f"#text(size: 8.8pt, fill: rgb({_lit(SOFT)}))[" + " #\" · \" ".join(parts) + "]")
    T.append("#block(below: 0.2em)[#set par(leading: 0.55em)\n" + " \\\n".join(head) + "\n]")

    teaser = ""
    shown = 0
    all_projects = doc.projects()
    skills = next(((t, bl) for t, bl in doc.sections if _is_skills(t)), None)

    def emit_plain(blocks):
        for b in blocks:
            if isinstance(b, tuple) and b[0] == "bullet":
                T.append(f"#list([{_inline(b[1])}])")
            elif isinstance(b, tuple):
                T.append(f"#par[{_inline(b[1])}]")

    for title_, blocks in doc.sections:
        if skills_on_p1 and page1_projects and skills and _is_skills(title_):
            continue                                   # already placed on page 1
        T.append(f"#sect({_lit(title_)})")
        for b in blocks:
            if isinstance(b, Project):
                head = (f"#text(size: 11.5pt, weight: \"bold\", fill: rgb({_lit(INK)}))[#{_lit(b.name)}]"
                        + (f"#text(fill: rgb({_lit(INK2)}))[#{_lit(' — ' + b.tagline)}]" if b.tagline else ""))
                if b.when:
                    head += f" #h(1fr) #text(size: 8.8pt, fill: rgb({_lit(SOFT)}), style: \"italic\")[#{_lit(b.when)}]"
                # Proximity decides what belongs together. The first render joined these with forced
                # line breaks, which left a blank line after the bullets and none before the next
                # project — so each tech line visually belonged to the project BELOW it. Now the tech
                # line is tucked under its own bullets and the gap goes between projects instead.
                body = [head]
                if b.bullets:
                    body.append("#list(" + ", ".join(f"[{_inline(x)}]" for x in b.bullets) + ")")
                if b.techline:
                    body.append(f"#v(-0.15em)#text(size: 8.8pt, fill: rgb({_lit(SOFT)}))[#{_lit(b.techline)}]")
                T.append("#block(breakable: false, above: 1.55em, below: 0em)[\n" + "\n".join(body) + "\n]")
                shown += 1
                rest = all_projects[shown:]
                if page1_projects and shown == page1_projects and rest:
                    if skills_on_p1 and skills:
                        T.append(f"#sect({_lit(skills[0])})")
                        emit_plain(skills[1])
                    # ONE line. The curiosity comes from one intriguing tagline, not an inventory —
                    # the first version listed every remaining project and wrapped, stranding a word.
                    first = rest[0]
                    teaser = f"Continued on page 2 → {first.name}" + (f": {first.tagline}" if first.tagline else "")
                    if len(rest) > 1:
                        teaser += f", and {len(rest) - 1} more"
                    T.append(f"#v(1.1em)#align(right)[#text(size: 9.5pt, fill: rgb({_lit(ACCENT)}), "
                             f"style: \"italic\")[#{_lit(teaser)}]]")
                    T.append("#pagebreak(weak: true)")
                    # Page 2 must not open mid-section with no label.
                    T.append(f"#sect({_lit(title_ + ' — continued')})")
            else:
                emit_plain([b])

    if doc.closing:
        T.append(f"#v(0.9em)#line(length: 100%, stroke: 0.4pt + rgb({_lit(RULE)}))")
        T.append(f"#align(center)[#text(size: 9pt, fill: rgb({_lit(SOFT)}))[#{_lit(doc.closing)}]]")
    return "\n".join(T) + "\n", teaser


def compile_pdf(src: str) -> bytes:
    import typst  # noqa: PLC0415
    return typst.compile(src.encode("utf-8"))


# ─── the read-back gate ───────────────────────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    s = (s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"\*+", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def pdf_text(pdf: bytes) -> list[str]:
    import fitz  # noqa: PLC0415
    d = fitz.open(stream=pdf, filetype="pdf")
    return [p.get_text() for p in d]


def readback(pdf: bytes, doc: Doc) -> list[str]:
    """Everything that must be true of the PDF before it is allowed to exist. [] = pass.

    This is the check his Claude Ambassador PDF would have failed in its first line."""
    import fitz  # noqa: PLC0415
    from .apply import corruption_warnings  # noqa: PLC0415

    pages = pdf_text(pdf)
    full = _norm(" ".join(pages))
    problems = []
    if len(full) < 400:
        problems.append(f"only {len(full)} characters of text could be extracted — no real text layer")
        return problems

    d = fitz.open(stream=pdf, filetype="pdf")
    unembedded = [i + 1 for i, p in enumerate(d) if not p.get_fonts()]
    if unembedded:
        problems.append(f"pages with no embedded fonts: {unembedded}")

    must = [("name", doc.name)] + [("headline", doc.headline)]
    must += [("contact", l) for l in doc.links if "@" in l]
    must += [("section", t) for t, _ in doc.sections]
    must += [("project", p.name) for p in doc.projects()]
    for kind, val in must:
        if val and _norm(val) not in full:
            problems.append(f"{kind} not found in the extracted text: {val!r}")

    # Skill lines: most items must come back as the words a recruiter's search would type.
    for title, blocks in doc.sections:
        for b in blocks:
            if isinstance(b, tuple) and b[0] == "para" and re.match(r"^\*\*[^*]+:\*\*", b[1]):
                items = [re.sub(r"\s*\(.*?\)", "", x).strip()
                         for x in re.sub(r"^\*\*[^*]+:\*\*", "", b[1]).split("·")]
                items = [x for x in items if x]
                missing = [x for x in items if _norm(x) not in full]
                if items and len(missing) > len(items) * 0.1:
                    problems.append(f"skills lost in extraction: {', '.join(missing[:5])}")

    # Reading order: the name must come first, and the summary before any project.
    first = _norm(pages[0])[:250]
    if doc.name and _norm(doc.name) not in first:
        problems.append("the name is not the first thing a parser reads")
    idx = lambda s: full.find(_norm(s)) if s else -1  # noqa: E731
    projs = doc.projects()
    if projs and idx("summary") > idx(projs[0].name) >= 0:
        problems.append("reading order: a project is extracted before the summary")

    raw = "\n".join(pages)
    for w in corruption_warnings(raw):
        problems.append(f"corrupted text in the PDF: {w}")
    # Only a hyphen the RENDERER inserted splits a keyword ("Kuber-/netes"). A line that wraps at a
    # hyphen already in his text — "hand-written", "prompt-injection" — is an ordinary line break, and
    # the first version of this gate refused a correct PDF over exactly those two.
    source = _norm(" ".join([doc.headline, *[x for p in doc.projects() for x in p.bullets],
                             *[b[1] for _, bl in doc.sections for b in bl if isinstance(b, tuple)]]))
    inserted = [f"{a}-{b}" for a, b in re.findall(r"([A-Za-z]{2,})-\n([a-z]{2,})", raw)
                if f"{a}-{b}".lower() not in source]
    if inserted:
        problems.append(f"renderer hyphenated words across lines (breaks keyword search): {inserted[:3]}")
    return problems


# ─── render with the page-1 layout ────────────────────────────────────────────────────────────────
@dataclass
class Rendered:
    pdf: bytes
    pages: int
    page1_projects: int | None
    teaser: str
    problems: list[str]


# Page 1 must END by this share of its height. A human is reading, and TheLadders found resumes lost
# attention to "cluttered layouts, a lack of white space". The first version maximised page-1 content
# and filled it to the bottom margin; he looked at it and called it congested. He was right.
PAGE1_MAX_FILL = 0.88


def _teaser_fill(pdf: bytes, teaser: str) -> float:
    """How far down page 1 the teaser line ends, as a share of page height (1.0 = off the page)."""
    import fitz  # noqa: PLC0415
    page = fitz.open(stream=pdf, filetype="pdf")[0]
    hits = page.search_for(teaser[:28])
    return (max(r.y1 for r in hits) / page.rect.height) if hits else 1.0


def render(md: str) -> Rendered:
    """Render, then prove it. Tries the most page-1 content first — k projects with the skills block,
    then without, then k-1 — and keeps the first layout whose teaser lands on page 1 with breathing
    room below it (PAGE1_MAX_FILL). Plain flow if nothing fits."""
    doc = parse(md)
    n = len(doc.projects())
    has_skills = any(_is_skills(t) for t, _ in doc.sections)
    attempts = [(k, s) for k in range(n - 1, 0, -1) for s in ((True, False) if has_skills else (False,))]
    best = fallback = None
    for k, s in attempts:
        src, teaser = to_typst(doc, k, s)
        pdf = compile_pdf(src)
        pages = pdf_text(pdf)
        if not teaser or _norm(teaser)[:40] not in _norm(pages[0]):
            continue                                  # overflowed: the teaser fell onto page 2
        cand = Rendered(pdf, len(pages), k, teaser, [])
        fallback = fallback or cand                   # densest layout that fits at all
        if _teaser_fill(pdf, teaser) <= PAGE1_MAX_FILL:
            best = cand
            break
    # Preference: breathing room > densest fit with a teaser > plain flow with no teaser.
    best = best or fallback
    if best is None:
        src, _ = to_typst(doc, None)
        pdf = compile_pdf(src)
        best = Rendered(pdf, len(pdf_text(pdf)), None, "", [])
    best.problems = readback(best.pdf, doc)
    return best


# ─── DOCX: the same content, for parsers that read Word best ─────────────────────────────────────
def render_docx(md: str, out: Path) -> list[str]:
    """Write the DOCX and read it back. DOCX gets no teaser or page break: Word decides pagination
    when the file is opened, so a forced break could strand half a page. It is the plain, maximally
    parseable copy — Taleo and iCIMS read DOCX most reliably."""
    from docx import Document  # noqa: PLC0415
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT  # noqa: PLC0415
    from docx.shared import Cm, Pt, RGBColor  # noqa: PLC0415

    doc = parse(md)
    D = Document()
    for s in D.sections:
        s.left_margin = s.right_margin = Cm(1.6)
        s.top_margin = s.bottom_margin = Cm(1.4)
    base = D.styles["Normal"]
    base.font.name, base.font.size = BODY_FONTS[0], Pt(10)
    rgb = lambda h: RGBColor.from_string(h.lstrip("#"))  # noqa: E731

    def runs(par, text, size=None, color=None):
        for tok in re.split(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)", text or ""):
            if not tok:
                continue
            bold = tok.startswith("**") and tok.endswith("**") and len(tok) > 4
            ital = not bold and tok.startswith("*") and tok.endswith("*") and len(tok) > 2
            r = par.add_run(tok[2:-2] if bold else tok[1:-1] if ital else tok)
            r.bold, r.italic = bold, ital
            if size:
                r.font.size = Pt(size)
            if color:
                r.font.color.rgb = rgb(color)
        par.paragraph_format.space_after = Pt(2)
        return par

    p = D.add_paragraph()
    r = p.add_run(doc.name)
    r.bold, r.font.size, r.font.name = True, Pt(22), HEAD_FONTS[0]
    if doc.headline:
        runs(D.add_paragraph(), f"**{doc.headline}**", 10.5)
    if doc.links:
        runs(D.add_paragraph(), "  |  ".join(doc.links), 9, SOFT)
    for e in doc.eduline:
        runs(D.add_paragraph(), e, 9.5, INK2)

    width = D.sections[0].page_width - D.sections[0].left_margin - D.sections[0].right_margin
    for title, blocks in doc.sections:
        h = D.add_heading(title.upper(), level=1)
        for run in h.runs:
            run.font.size, run.font.name, run.font.color.rgb = Pt(11), HEAD_FONTS[0], rgb(ACCENT)
        for b in blocks:
            if isinstance(b, Project):
                par = D.add_paragraph()
                par.paragraph_format.tab_stops.add_tab_stop(width, WD_TAB_ALIGNMENT.RIGHT)
                runs(par, f"**{b.name}**" + (f" — {b.tagline}" if b.tagline else ""))
                if b.when:
                    runs(par, f"\t*{b.when}*", 8.8, SOFT)
                for x in b.bullets:
                    runs(D.add_paragraph(style="List Bullet"), x)
                if b.techline:
                    runs(D.add_paragraph(), b.techline, 8.6, SOFT)
            elif b[0] == "bullet":
                runs(D.add_paragraph(style="List Bullet"), b[1])
            else:
                runs(D.add_paragraph(), b[1])
    if doc.closing:
        c = runs(D.add_paragraph(), doc.closing, 9, SOFT)
        c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    D.core_properties.title = f"{doc.name.title()} — Resume"
    D.core_properties.author = doc.name.title()
    D.save(str(out))

    text = _norm(" ".join(p.text for p in Document(str(out)).paragraphs))
    problems = []
    for kind, val in [("name", doc.name)] + [("section", t) for t, _ in doc.sections] + \
                     [("project", p.name) for p in doc.projects()]:
        if val and _norm(val) not in text:
            problems.append(f"{kind} missing from the DOCX: {val!r}")
    return problems


def file_stem(md: str, company: str = "") -> str:
    """K_Mohith_Kannan_Resume[_Company] — recruiters see the filename before they see the page, and
    'mohith_claude_campous_ambasidor1.pdf' carried two typos and a version number."""
    name = parse(md).name or "Resume"
    who = "_".join(w.capitalize() if len(w) > 1 else w.upper() for w in re.findall(r"[A-Za-z]+", name))
    co = re.sub(r"[^A-Za-z0-9]+", "", company.title())[:30]
    return f"{who}_Resume" + (f"_{co}" if co else "")


def write(md_path: Path, out_pdf: Path | None = None, docx: bool = True, company: str = "") -> dict:
    """Render next to the Markdown. The PDF is written ONLY if the read-back gate passes."""
    md = Path(md_path).read_text(encoding="utf-8")
    stem = file_stem(md, company)
    out_pdf = Path(out_pdf) if out_pdf else Path(md_path).with_name(stem + ".pdf")
    res = render(md)
    result = {"pdf": None, "docx": None, "pages": res.pages, "page1_projects": res.page1_projects,
              "teaser": res.teaser, "problems": list(res.problems), "docx_problems": []}
    if not res.problems:
        out_pdf.write_bytes(res.pdf)
        result["pdf"] = out_pdf
    if docx:
        out_docx = out_pdf.with_suffix(".docx")
        result["docx_problems"] = render_docx(md, out_docx)
        if not result["docx_problems"]:
            result["docx"] = out_docx
        else:
            out_docx.unlink(missing_ok=True)
    return result


def main() -> int:
    import argparse  # noqa: PLC0415
    ap = argparse.ArgumentParser(description="Render resume.md to a verified PDF (+ DOCX).")
    ap.add_argument("md", help="path to a resume.md")
    ap.add_argument("--out", default="", help="PDF path (default: K_Mohith_Kannan_Resume.pdf beside it)")
    ap.add_argument("--no-docx", action="store_true")
    ap.add_argument("--company", default="", help="adds _Company to the file name")
    a = ap.parse_args()
    r = write(Path(a.md), Path(a.out) if a.out else None, not a.no_docx, a.company)
    if r["pdf"]:
        print(f"  PDF   {r['pdf']}  ({r['pages']} page{'s' if r['pages'] != 1 else ''}, "
              f"{r['page1_projects'] or 'all'} project(s) on page 1) — text layer verified")
        if r["teaser"]:
            print(f"        page 1 ends: {r['teaser'][:90]}")
    else:
        print("  PDF NOT WRITTEN — it failed the read-back gate:")
        for p in r["problems"]:
            print(f"    - {p}")
    if r["docx"]:
        print(f"  DOCX  {r['docx']} — read back clean")
    elif r["docx_problems"]:
        print("  DOCX NOT WRITTEN:", "; ".join(r["docx_problems"]))
    return 0 if r["pdf"] else 1


if __name__ == "__main__":
    sys.exit(main())
