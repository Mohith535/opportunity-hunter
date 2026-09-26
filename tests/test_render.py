"""Tests for Phase 2 — the PDF/DOCX renderer (resume/render.py) and the ATS checker (resume/ats.py).

The regression behind all of it: his best resume PDF contained no text — 0 extractable characters,
every glyph drawn as a vector shape by Microsoft Print To PDF. So the two properties that matter most:
  1. The renderer NEVER writes a PDF it cannot read back.
  2. The ATS checker FAILS a text-less PDF, loudly, whatever it looks like.

Self-contained: builds its own resume from a fixture profile, with the model stubbed out.
Run:  python tests/test_render.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import fitz

import resume.generate  # noqa: F401
from resume import ats
from resume.apply import company_of
from resume.render import (_lit, compile_pdf, file_stem, parse, pdf_text, readback, render,
                           render_docx, to_typst, write)

GEN = sys.modules["resume.generate"]
R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

LONG = ("Every agent memory tool today is a bucket: add() always succeeds, so an agent can quietly store "
        "two contradictory facts and act on whichever it reads first. This one refuses the contradicting "
        "write and retires superseded facts. I benchmarked my own thesis and it was refuted — the LLM "
        "out-governed my hand-written rules. Roughly 92% of the model's accuracy at a quarter of its "
        "calls. 190 tests; seven prompt-injection attacks resisted.")
PROFILE = {
    "basics": {"name": "K MOHITH KANNAN", "email": "promohith535@gmail.com"},
    "skills": [{"name": "python"}, {"name": "typescript"}, {"name": "mcp"}],
    "education": [{"institution": "SRM Institute of Science and Technology",
                   "studyType": "B.Tech — Computer Science Engineering", "startDate": "2025", "endDate": "2029"},
                  {"institution": "Sainik School Amaravathinagar", "studyType": "Senior Secondary",
                   "startDate": "2017", "endDate": "2024", "note": "Ranked 2nd in class"}],
    "projects": [
        {"x_resume_name": n, "name": n, "x_source": "resume-2026-09", "x_tagline": t, "x_when": w,
         "x_techline": tech, "highlights": [LONG, LONG[:180] + " Shipped with **one emphasised phrase**."]}
        for n, t, w, tech in [
            ("NitroWatch", "a permission system for AI agents", "Aug 2026", "TypeScript · MCP · audit logging"),
            ("nova-cortex", "an agent memory that is allowed to say “no”", "Jul 2026", "Python · MCP · CockroachDB"),
            ("Nova", "a ten-agent coaching layer", "Jun 2026", "Python · Google ADK · MCP"),
            ("LoopLab", "send someone an exact moment of a video", "Aug 2026", "TypeScript · Web Audio"),
            ("TaskFlow", "a task manager built on behavioural science, not features", "Dec 2025", "Python · CLI"),
        ]],
    "x_resume": {
        "headline": "B.Tech CSE (AI & ML) @ SRM Chennai | MCP servers and clients",
        "summary_core": "Second-year CSE (AI & ML) student who ships what he builds. Five working systems so far.",
        "closing": "The thing on this page I am proudest of is a memory that knows how to refuse.",
        "links": ["promohith535@gmail.com", "github.com/Mohith535", "looplab.page"],
        "community": ["**Four hackathons in 2026:** NitroStack, Aaruush, Ossome Hacks, Bharath."],
        "skill_groups": {"Languages": ["Python (advanced)", "TypeScript", "C", "C++", "C#"],
                         "AI & agents": ["Model Context Protocol — servers and clients", "Google ADK"]},
    },
}
REAL = GEN.complete


def build(reply="", jd="Python, MCP, TypeScript, agents.", role="Software Engineer Intern", company=""):
    GEN.complete = lambda *a, **k: reply
    try:
        return GEN.generate_resume_ex(PROFILE, jd, role, company)
    finally:
        GEN.complete = REAL


MD, _ = build()

# ── Typst string safety ──────────────────────────────────────────────────────────────────
nasty = 'C# and C++, add() returns $5 @ 50% #1 "quoted" back\\slash <tag> [x] *not bold*'
src = f"#{_lit(nasty)}"
try:
    got = pdf_text(compile_pdf(src))[0]
    check("1. markup-significant characters survive as plain text", "C# and C++" in got and "add()" in got
          and '"quoted"' in got.replace("“", '"').replace("”", '"'), got[:80])
except Exception as e:  # noqa: BLE001
    check("1. markup-significant characters survive as plain text", False, repr(e))

# ── parsing our own Markdown ─────────────────────────────────────────────────────────────
doc = parse(MD)
check("2. header parsed (name, headline, links, education line)",
      doc.name == "K MOHITH KANNAN" and "MCP servers" in doc.headline and len(doc.links) == 3
      and any("2025–2029" in e for e in doc.eduline), f"{doc.name!r} {doc.headline!r} {doc.links}")
ps = doc.projects()
check("3. all five projects parsed with tagline, date, bullets and tech line",
      len(ps) == 5 and all(p.tagline and p.when and p.bullets and p.techline for p in ps),
      str([(p.name, bool(p.tagline), bool(p.when), len(p.bullets), bool(p.techline)) for p in ps]))
check("4. the closing line is parsed", "knows how to refuse" in doc.closing)
check("5. the section is headed 'Projects' (ATS-standard), not 'Selected Work'",
      any(t == "Projects" for t, _ in doc.sections), str([t for t, _ in doc.sections]))

# ── rendering + the page-1 story ─────────────────────────────────────────────────────────
res = render(MD)
p1 = res and pdf_text(res.pdf)[0]
check("6. a PDF is produced and passes its own read-back gate", res.pdf and not res.problems, str(res.problems))
check("7. the name is the first thing extracted", p1.strip().splitlines()[0].strip() == "K MOHITH KANNAN",
      p1.strip().splitlines()[0])
check("8. graduation year is on page 1 (knockout answered in 3 s)", "2025–2029" in p1)
check("9. the teaser sits on page 1 and names what page 2 holds",
      res.teaser and res.teaser[:30] in " ".join(p1.split()), res.teaser)
check("10. the skills block is lifted onto page 1", "TECHNICAL SKILLS" in p1)
if res.pages > 1:
    p2 = pdf_text(res.pdf)[1]
    check("11. page 2 opens with a 'continued' heading, not mid-section", "CONTINUED" in p2[:200].upper(), p2[:80])
    check("12. the last line is his closing line (peak-end)", "knows how to refuse" in p2[-200:].replace("\n", " "))
fitz_doc = fitz.open(stream=res.pdf, filetype="pdf")
check("13. every page embeds real fonts", all(p.get_fonts() for p in fitz_doc))
check("14. no ligature glyphs in the extracted text",
      not any(c in "".join(pdf_text(res.pdf)) for c in "ﬀﬁﬂﬃﬄ"))
check("15. one-letter skill 'C' is not promoted above Python", "Python (advanced)" in p1.split("C++")[0]
      if "C++" in p1 else True)

# ── the gate refuses what it cannot read ─────────────────────────────────────────────────
blank = compile_pdf('#rect(width: 5cm, height: 2cm, fill: black)')
check("16. read-back gate refuses a PDF with no text", readback(blank, doc) and "no real text layer" in readback(blank, doc)[0])
wrong = compile_pdf('#' + _lit("Somebody Else. " * 60))
check("17. read-back gate refuses a PDF missing the name and sections", any("name" in p for p in readback(wrong, doc)))

# ── files, names, DOCX ───────────────────────────────────────────────────────────────────
check("18. file name is recruiter-safe", file_stem(MD, "Coinbase Inc.") == "K_Mohith_Kannan_Resume_Coinbase",
      file_stem(MD, "Coinbase Inc."))
# The organiser's full legal name produced K_Mohith_Kannan_Resume_ShriVileParleKelavaniMandalSDw.pdf.
_DJ = "Shri Vile Parle Kelavani Mandal's Dwarkadas J. Sanghvi College of Engineering (DJSCE), Mumbai"
check("18b. a bracketed acronym is the short name", file_stem(MD, _DJ) == "K_Mohith_Kannan_Resume_DJSCE",
      file_stem(MD, _DJ))
from resume.render import short_company
check("18c. legal suffixes and a trailing city go",
      short_company("Mellow Vault Technologies Private Limited") == "Mellow Vault"
      and short_company("Seoczar IT Services Pvt. Ltd.") == "Seoczar IT"
      and short_company("Acme Labs, Mumbai") == "Acme Labs",
      [short_company(x) for x in ("Mellow Vault Technologies Private Limited", "Seoczar IT Services Pvt. Ltd.",
                                  "Acme Labs, Mumbai")])
check("18d. a short name is left alone", short_company("Scale AI") == "Scale AI" and short_company("") == "")
tmp = Path(tempfile.mkdtemp())
mdp = tmp / "resume.md"
mdp.write_text(MD, encoding="utf-8")
w = write(mdp, company="Microsoft")
check("19. write() produces PDF and DOCX with the right names",
      w["pdf"] and w["pdf"].name == "K_Mohith_Kannan_Resume_Microsoft.pdf" and w["docx"] and w["docx"].exists(), str(w))
check("20. the DOCX reads back with every section and project", not render_docx(MD, tmp / "x.docx"))

# ── the ATS checker ──────────────────────────────────────────────────────────────────────
ok = ats.check(w["pdf"])
check("21. ATS: our PDF passes", ok.verdict != ats.FAIL and ok.chars > 1000, ok.verdict + str([f.what for f in ok.findings]))
ok2 = ats.check(w["docx"])
check("22. ATS: our DOCX passes", ok2.verdict != ats.FAIL, ok2.verdict)

# A PDF built the way his was: lots of drawn shapes, no text, Microsoft Print To PDF as producer.
shapes = fitz.open()
for _ in range(2):
    pg = shapes.new_page()
    for i in range(400):
        pg.draw_rect(fitz.Rect(50 + (i % 40) * 12, 60 + (i // 40) * 20, 58 + (i % 40) * 12, 72 + (i // 40) * 20))
shapes.set_metadata({"producer": "Microsoft: Print To PDF", "title": "K Mohith Kannan \x14 Resume"})
outlined = tmp / "outlined.pdf"
shapes.save(str(outlined))
bad = ats.check(outlined)
whats = " | ".join(f.what for f in bad.findings)
check("23. ATS: a shapes-only PDF FAILS with 'no readable text'", bad.verdict == ats.FAIL and "NO READABLE TEXT" in whats, whats)
check("24. ATS: names Microsoft Print To PDF as the cause", "Print To PDF" in whats, whats)
check("25. ATS: a .txt resume is rejected", ats.check(mdp).verdict == ats.FAIL)
check("26. ATS: a missing file is reported, not crashed on", ats.check(tmp / "nope.pdf").verdict == ats.FAIL)
jd_rep = ats.check(w["pdf"], "We need Python, Kubernetes and React.")
check("27. ATS: --jd reports keyword coverage honestly",
      any("job keywords found" in f.what and "kubernetes" in f.what for f in jd_rep.findings))

# ── company + role section ───────────────────────────────────────────────────────────────
check("28. company from 'Company — Role'", company_of({"title": "Microsoft — Software Engineer Intern"}, {}) == "Microsoft")
check("29. company from 'Role — Company'", company_of({"title": "Software Engineer Intern — Coinbase"}, {}) == "Coinbase")
check("30. no company invented from a plain title", company_of({"title": "Data Analyst Internship"}, {}) == "")

JD = ("We build developer tooling for AI agents. You will design governance and permission systems, "
      "write Python and TypeScript services, and evaluate model behaviour with rigorous benchmarks. "
      "Experience with MCP is a plus. You care about safety and about shipping. ") * 2
three = ("- Permission systems for agents — NitroWatch sorts every MCP tool into three risk tiers.\n"
         "- Rigorous benchmarks — nova-cortex reached roughly 92% of the model's accuracy at a quarter of its calls.\n"
         "- SEO and content marketing — I grew organic traffic with meta tags.")
md3, rep3 = build(three, JD, "AI Tooling Intern", "Anthropic")
check("31. role section kept with the 2 true bullets; the lying one is removed",
      "## What I would bring to Anthropic" in md3 and len(rep3["role_section"]) == 2
      and "SEO" not in md3.split("## What I would bring")[1].split("##")[0], str(rep3["role_section"]))
md1, rep1 = build("- Permission systems — NitroWatch sorts tools into three risk tiers.\n- SEO — meta tags.", JD, "X", "Y")
check("32. one surviving bullet is not enough — section omitted", "What I would bring" not in md1)
md0, rep0 = build(three, "Short blurb.", "X", "Y")
check("33. a job blurb is too thin to map honestly — no section", "What I would bring" not in md0)

# ── breathing room + header (his review: "the pdf is congested — a human is reading") ─────
from resume.render import PAGE1_MAX_FILL, _teaser_fill
if res.teaser:
    fill = _teaser_fill(res.pdf, res.teaser)
    check("34. page 1 ends with breathing room, not at the margin", fill <= PAGE1_MAX_FILL + 0.001,
          f"fill={fill:.2f}")
lines = [l.strip() for l in p1.splitlines() if l.strip()]
check("35. header reads name → headline → education → contact, each on its own line",
      lines[0] == "K MOHITH KANNAN" and "MCP servers" in lines[1] and "2025–2029" in lines[2]
      and "promohith535@gmail.com" in lines[3], str(lines[:4]))
check("36. the education line never runs into the links", not any("looplab.page B.Tech" in l for l in lines))

G2 = sys.modules["resume.generate"]
comm = ["**Four hackathons in 2026:** NitroStack × SRM · Ossome Hacks 3.0",
        "**Open source:** selected contributor to GSSoC 2026 (AI/Agents track) and SSoC Season 5.",
        "**Writing:** technical posts on LinkedIn."]
progs = ["**GSSoC 2026** (AI/Agents track) and **SSoC Season 5** — selected open-source contributor, 2026."]
kept = G2._drop_repeats(comm, progs)
check("37. a bullet repeating another section (GSSoC/SSoC twice) is dropped",
      len(kept) == 2 and not any("GSSoC" in k for k in kept), str(kept))
check("38. distinct bullets are never dropped", G2._drop_repeats(comm[:1] + comm[2:], progs) == comm[:1] + comm[2:])

from resume.profile import carry_over
old = {"education": [{"institution": "SRM Institute of Science and Technology", "startDate": "2025", "endDate": "2029"}]}
new = {"education": [{"institution": "SRM Institute of Science and Technology", "startDate": "2024", "endDate": "2028"}]}
merged, _ = carry_over(old, new)
check("39. a rebuild from the export cannot restore the wrong graduation year",
      (merged["education"][0]["startDate"], merged["education"][0]["endDate"]) == ("2025", "2029"))

print("=" * 76)
for name, ok_, detail in R:
    print(f"  {'PASS' if ok_ else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok_ else ""))
print("=" * 76)
passed = sum(1 for _, ok_, _ in R if ok_)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
