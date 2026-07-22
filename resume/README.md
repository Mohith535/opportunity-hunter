# Career Intelligence Engine (`resume/`)

> **Branch-only** (`feat/career-intelligence`) — not merged. `main` stays frozen while
> `opportunity-hunter` is Kaggle-judged. Everything here is local; your profile is gitignored.

An honest career engine: it reads what you have **actually done** (GitHub public + private, your
certificates folder, your LinkedIn export) and helps you apply — analysis, tailoring, a resume, a
cover letter, and a grounded career simulation.

**The one rule that runs through all of it: it never invents.** Every skill carries an evidence trail
(`repo:` / `cert:` / `linkedin:`). Missing numbers become `[add metric]`, never fabricated ones.
Nothing is auto-submitted.

```
harvest ─┐
         ├─► profile (career_profile.json = single source of truth) ─┬─► generate  (resume)
certs ───┤                                                          ├─► cover     (letter)
LinkedIn ┘                                                          ├─► simulate  (roadmap)
                                                    analyze + tailor ┘ (existing resume vs a JD)
```

---

## Setup (once)

1. **Private repos** (optional but recommended) — create a GitHub **classic PAT with `repo` scope**,
   then add to the gitignored `.env` at the repo root:
   ```
   GITHUB_TOKEN=ghp_xxxxxxxx
   ```
2. **LLM** — uses the project's existing free chain (`GROQ_API_KEY` → `CEREBRAS_API_KEY` →
   `OPENROUTER_API_KEY` in `.env`). Everything still renders without one, just plainer.
3. **Reading .pdf/.docx resumes** (only for `python -m resume`):
   `pip install pdfminer.six python-docx`

---

## 1. Build your profile — **do this first**

```bash
python -m resume.profile --github Mohith535 --include-private --certs "E:/certificates"
```
Add `--linkedin "E:/LinkedInExport"` once your LinkedIn export arrives (Settings → Data Privacy →
"Get a copy of your data"; folder **or** `.zip`). That fills in work history + education.

- `--show` — display the cached profile without rebuilding
- Writes `data/career_profile.json` (JSON-Resume standard, **gitignored** — it's your personal data)
- **Re-run whenever your evidence changes** (new repo, new certificate, new export)

## 2. Check + tailor an existing resume against a job

```bash
python -m resume --resume "MyResume.pdf" --jd "jd.txt" --profile --tailor
```
- Honest ATS parse-check (real parse-killers, **no fake score**) + true keyword coverage
- Gap list auto-checked against your evidence: ✅ proven → safe to add · ⚠️ unproven → it asks you
- `--tailor` rewrites bullets in Google's XYZ shape, grounded in your **real projects**

| flag | what it does |
|---|---|
| `--profile` | read the cached profile (recommended) |
| `--github / --certs / --linkedin` | live harvest instead of the cache |
| `--include-private` | include private repos (needs the PAT) |
| `--have "Docker,SQL"` | manually confirm skills you genuinely have |

## 3. Generate a resume from your profile

```bash
python -m resume.generate --jd "jd.txt" --out resume.md
```
ATS-safe single-column Markdown → export to PDF. Omit `--jd` for a general resume. Fill the
`[bracketed]` placeholders (email, university), review, then send.

## 4. Cover letter

```bash
python -m resume.cover --jd "jd.txt" --company "Anthropic" --role "AI/ML Intern" \
  --why "your genuine reason for THIS company" --out cover.md
```
`--why` is the one thing the tool will **never** invent for you. Omit it and you get a visible
placeholder to fill — not a fluent lie about admiring their work.

## 5. Which job should you even apply to? (Feed → Fit)

```bash
python -m resume.fit --top 8
```
Ranks the opportunities OPHunter already found (`data/feed.json`) against your **verified** profile:
what you can *prove* it asks for, plus an honest verdict — **STRONG FIT / STRETCH / NOT YET**. No
invented match percentage; expired deadlines dropped (`--include-expired` to look back,
`--no-verdict` to skip the LLM).

## 6. Can you defend it? ("Prove it")

```bash
python -m resume.prove --resume resume.md
```
A receipt for every claim — each verified skill/project gets its evidence trail, and anything the
profile **can't back** is flagged before an interviewer finds it.

## 7. Fix your evidence (audit)

```bash
python -m resume.audit
```
Finds what silently weakens every document: repos with no description (skipped everywhere), skills
backed **only** by a certificate (*exposure, not practice*), thin single-evidence skills, staleness.
Each finding has a FIX and a WHY.

## 8. LinkedIn profile text

```bash
python -m resume.social --target "AI/ML Engineering Intern" --out linkedin.md
```
An honest headline (220-char limit, first ~70 are what recruiters see) + About section (2,600 limit,
first ~300 show before "See more"), written from your real projects. Works today — no export needed.

## 9. Career simulation

```bash
python -m resume.simulate --target "Machine Learning Engineer intern" --months 6 --profile
```
An honest path from where you **actually** are: your verified profile → the target's real bar → the
gap → a backward-planned 70-20-10 roadmap with SMART milestones, citing **real opportunities from
your own feed** (`data/feed.json`) at the phase where they fit. Honest about odds — never a promise.

---

## Modules

| file | role |
|---|---|
| `analyzer.py` | text extraction, honest ATS checks, JD keywords, literal coverage |
| `harvest.py` | verified skills **with evidence** (GitHub pub+priv, certs) |
| `linkedin.py` | LinkedIn **data-export** parser (no scraping — ToS + account safety) |
| `profile.py` | Profile Engine → `career_profile.json` (the single source of truth) |
| `tailor.py` | XYZ bullet rewriting, confirmed skills only |
| `generate.py` | resume document generator |
| `cover.py` | cover-letter generator |
| `simulate.py` | career simulation |

## Guarantees

- **No invented experience** — unproven skills are surfaced as questions, never added
- **No fake ATS score** — real parse issues + a true keyword count instead
- **No fabricated numbers** — `[add metric]` placeholders you fill
- **No LinkedIn scraping** — only the export you download yourself
- **No auto-submit** — every output is a draft you review and send

*Free to run (no paid APIs). Deterministic structure + fact-bound LLM prose: the facts come from
code, the phrasing from the model, and you make the final call.*
