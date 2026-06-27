# Opportunity Hunter → "Filter by Mohith" — Design Spec

> **Date:** 2026-06-28
> **Author:** K Mohith Kannan · designed with Claude (brainstorming session)
> **Status:** Design — awaiting your approval before implementation
> **One line:** Stop filtering by keywords. Start filtering by *Mohith*. Make the agent ask
> *"Would Mohith regret missing this?"* instead of *"Is this an AI hackathon?"*

---

## 0. How to read this doc

This is the plan. Read it top to bottom — it's written to be understood, not to be technical.
If a section looks right, it's right. At the end there's **one thing to do: say "go"** and I build
**Phase A** (the part that makes it smart). You don't need to decide anything else.

---

## 1. The problem with the current system (honest take)

Today the Hunter is excellent *plumbing* but a *dumb judge*:

- It collects from 9 sources ✅ (this part is great — keep it)
- It filters by **keyword match** — "does the text contain 'machine learning'?"
- It scores by **fixed rules** — +3 if keyword in title, +2 for remote, etc.

That means it treats a **Google AI Residency** and a **random ML webinar** almost the same if they
share keywords. It has no idea that *you* would crawl over glass for the first and skip the second.
It finds opportunities. It doesn't understand them. **That's the 80% that's missing.**

## 2. The core idea (the psychology this is built on)

The reframe — *"Would Mohith regret missing this?"* — is not a cute phrase. It's a real decision
model, and the design is built on it deliberately:

- **Regret-Minimization (Bezos):** humans regret *inaction they can't undo* far more than *effort
  that didn't pay off.* So the agent's real question is **"what is the cost of NOT acting?"** A
  prestigious program closing in 4 days scores high *even if it's hard*, because missing it is
  **irreversible**. A webinar you can rewatch forever scores low even if it's relevant.
- **The regret formula the scorer uses:** `regret ≈ career_leverage × urgency × irreversibility`.
- **Opportunity cost over keyword match:** a "9/10 relevant" thing you can do anytime loses to a
  "7/10 relevant" thing that vanishes Friday and opens a door at Google.
- **Planning-fallacy awareness (for the action plan):** people underestimate effort. The agent's
  suggested mini-plan deliberately front-loads a *tiny* first step ("read the page — 15 min"),
  because starting is the hard part (Zeigarnik open-loop). This mirrors how your own Nova Coach
  already talks.

**This is the difference between an RSS reader and a second brain.**

## 3. The three decisions already made (by you, in brainstorming)

1. **Architecture = Hybrid (C):** Opportunity Hunter stays its **own standalone project**, but is
   **Nova-aware** — it reads Nova's brain and feeds Nova's Scout, all through files (never importing
   code). A future full merge into Nova stays trivial, but isn't done now (Nova is mid-competition).
2. **Profile source = Nova's brain + local fallback:** the scorer judges against the *real* you,
   read from Nova's profile, with a safe fallback so it still works in the cloud.
3. **Action = propose, never auto:** nothing is auto-dumped into TaskFlow. The agent surfaces the
   opportunity + *why it matters* + a suggested plan; **you** confirm. The confirm UI **already
   exists** — it's Nova's Scout "→ Plan this in TaskFlow" button. Phone notification is just the alert.

## 4. The new pipeline

```
                                    ┌─────────────────────────────┐
  9 sources ──▶ Relevance Gate ──▶  │   LLM SCORER (Gemini)        │ ──▶ Dedup ──▶ history.json
  (+ flagship   (cheap keyword      │   • 6-dimension score        │              │
   programs,     pre-filter, kills  │   • regret-aware final 0–10  │              ▼
   Phase B)      obvious junk)      │   • "why it matters" reason  │      ┌───────────────┐
                                    │   • 3–4 step action plan     │      │ Notify (phone) │
                                    └─────────────────────────────┘      │ Propose (Nova  │
                                          ▲                              │ Scout 1-click) │
                                          │ profile (the real Mohith)    └───────────────┘
                                  ┌───────┴────────┐
                                  │ PROFILE LOADER │ ← Nova user_profile.json + nova_insights.json
                                  └────────────────┘    (fallback: local profile.yaml / secret)
```

**Why this is low-risk:** your code was *designed* for this exact moment. `scorer.ai_score_item()`
is already a stub returning `-1`. `policy.effective_score()` already prefers `ai_score` the instant
it's `≥ 0`. So switching from "dumb rules" to "LLM brain" is **flipping one wire that already
exists** — not re-architecting.

## 5. The scoring model (what the LLM actually returns)

For each opportunity, Gemini receives **(profile + opportunity)** and returns structured JSON:

| Dimension | Weight | Meaning |
|---|---|---|
| Career Impact | 35% | Does this move Mohith toward "exceptional AI engineer, builder, entrepreneur"? |
| Interest Match | 25% | AI agents / LLMs / GenAI / building — his real interests, not just any CS |
| Prestige | 15% | Google / Microsoft / NVIDIA / Anthropic / top-lab signal on a resume |
| Deadline | 10% | Urgency — how irreversible is missing it |
| Skill Growth | 10% | Portfolio / real-skill gain (weighted above swag/cash, per your values) |
| Time Required | 5% | Effort vs. payoff (a month-long low-value thing is penalized) |

→ Weighted **final score 0–10**, plus a **regret flag** for the irreversible-elite items, plus:
- **`ai_summary`** — one line: *why this matters for Mohith specifically*
- **`action_plan`** — 3–4 concrete steps with tiny first action (e.g. *"Read program page (15 min) →
  update resume bullet (30 min) → draft application (45 min) → submit before Jul 12"*)

**Graceful degradation (senior-dev rule):** if there's no API key, or Gemini quota is exhausted, the
agent **falls back to the existing rule-based scorer** and still ships a digest. It never dies. This
matches the Hunter's existing "never crash, one source failing doesn't kill the run" philosophy.

## 6. The profile loader (reading "the real Mohith")

`profile.py` builds one normalized `MohithProfile`, reading in priority order:

1. `~/.taskflow/user_profile.json` — Nova's 7-question psychological profile + AI-import block
2. `~/.taskflow/nova_insights.json` — your *real behavioral patterns* (what you actually follow through on)
3. **fallback** → local `profile.yaml` (committed as `profile.example.yaml`; real one gitignored)
4. **cloud** → `OH_PROFILE_JSON` GitHub secret (because the repo is **public** — the real profile
   must never be committed in plaintext; same pattern Nova uses for `TASKFLOW_TASKS_JSON`)

The profile carries: long-term goal (the "north star" sentence), interest weights, company weights,
opportunity-type weights, geography preferences (incl. Japan + international), and "values" (portfolio
> swag). This is exactly the structure the GPT sketched — but sourced from systems you already built.

## 7. Privacy (because the repo is public)

- Real `profile.yaml` → **gitignored.** Only `profile.example.yaml` (placeholder) is committed.
- Cloud run reads the profile from the **`OH_PROFILE_JSON` secret**, not from the repo.
- Raw Nova psychological data **never** gets committed or sent anywhere except the Gemini scoring
  call (and only the *derived* profile fields the scorer needs, not raw memory) — consistent with
  Nova's own "raw data stays local, only derived context reaches Gemini" posture.

## 8. The Nova contract (must not break)

Nova reads `data/history.json`. We only **add** fields (`ai_score`, `ai_summary`, `action_plan`,
`dimensions`) — Nova ignores unknown keys, and `ai_score`/`ai_summary` are literally fields Nova
*already* looks for. **Result: Nova's Scout instantly gets smarter the moment we ship — zero changes
on Nova's side.** Nothing in the contract (path, top-level shape, key names) changes.

## 9. Build order

### Phase A — Make it smart (THE MVP — build this first)
The whole "filter by Mohith" wow, smallest new surface, reuses the existing pipeline + your Nova brain.
- `profile.py` — the profile loader (Nova + fallback + secret)
- `filters/llm_scorer.py` — Gemini 6-dimension regret-aware scoring + reason + action plan
- Wire it into the existing `ai_score_item()` stub (rule-based fallback preserved)
- Extend the `Opportunity` model + `history.json` output with the new fields
- Notification shows the *reason* + *action plan*; nothing auto-dumps
- Config + `requirements.txt` + workflow secrets (`GEMINI_API_KEY`, `OH_PROFILE_JSON`)
- **Outcome:** every opportunity arrives with a real "why this matters for you" + a plan. Nova's
  Scout ranks by the new intelligent score automatically.

### Phase B — Make the search precise (flagship programs)
A new "programs" source layer watching the *exact* high-value sources generic feeds miss:
Google (Cloud / Kaggle×Google / Gen AI Exchange APAC / GDG / Student programs), Microsoft (Learn
Student Ambassador / AI Skills Fest), Kaggle, IBM SkillsBuild, NVIDIA DLI, Anthropic, MLH, plus
Japan/international tracks. Each is one file + one registry line (your existing pattern). Exact URLs
verified at implementation time.

### Phase C — Two-way confirm from your phone (optional polish)
A Telegram bot so you can confirm "→ add to TaskFlow" *from the notification itself*, not just from
Nova's web console. (Your earlier Phase-2 note already wanted two-way Telegram.) Until then, Nova
Scout's one-click is the confirm path.

## 10. What "done" looks like for Phase A

- `python main.py --test` runs; if `GEMINI_API_KEY` is set, items show real LLM scores + reasons +
  action plans; if not, it cleanly falls back to rule scoring (no crash).
- A real run writes the new fields into `history.json`; Nova's Scout shows the smarter ranking with
  no Nova code change.
- The phone digest shows, per item: score, the one-line "why it matters," and the mini action plan.
- Profile loads from Nova locally, from the secret in cloud, from `profile.yaml` if both absent.

## 11. Explicitly NOT doing now (YAGNI)

- Not merging into Nova (Phase-later).
- Not building Research/Scholarship/Email/LinkedIn/Calendar "hunters" (that's the long-term Nova-OS
  vision — noted, not now).
- Not building the Telegram bot in Phase A.
- Not touching Nova's code at all.
