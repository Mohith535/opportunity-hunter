/**
 * Opportunity Hunter — always-on Telegram bot on Cloudflare Workers (FREE, no PC).
 *
 * This is the JS port of telegram_listener.py. It runs 24/7 at the edge via a
 * Telegram WEBHOOK, so taps and questions work even when your PC is off:
 *   - reads opportunities from the public repo's feed.json (key-bearing)
 *   - Plan tap  -> writes the taskflow-sync repo's inbox.json (you `taskflow sync pull`)
 *   - Applied/Skip/Remind -> tracker state in Workers KV; taste re-learned
 *   - Draft / Coach / Ask -> the same Groq->Cerebras->OpenRouter LLM chain
 *
 * The daily DIGEST is still sent by GitHub Actions (Python). This Worker only
 * handles incoming taps/commands. Every update is acknowledged immediately and the
 * real work runs in ctx.waitUntil(), so Telegram never times out.
 *
 * Bindings (wrangler.toml + secrets):
 *   KV:      BOT_KV
 *   vars:    TASKFLOW_SYNC_REPO, OPHUNTER_FEED_URL, REMIND_DAYS
 *   secrets: TELEGRAM_BOT_TOKEN, WEBHOOK_SECRET, TASKFLOW_SYNC_TOKEN,
 *            GROQ_API_KEY, CEREBRAS_API_KEY, OPENROUTER_API_KEY
 */

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "POST") {
      return new Response("Opportunity Hunter bot is running. ✅");
    }
    // Verify the request really came from Telegram (secret_token set on the webhook).
    if (env.WEBHOOK_SECRET &&
        request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }
    const update = await request.json().catch(() => null);
    if (update) ctx.waitUntil(handleUpdate(env, update));
    return new Response("ok");  // ack immediately
  },
};

// ─── routing ─────────────────────────────────────────────────────────
async function handleUpdate(env, update) {
  try {
    if (update.callback_query) return await handleCallback(env, update.callback_query);
    if (update.message) return await handleMessage(env, update.message);
  } catch (e) {
    console.log("handleUpdate error:", e && e.message);
  }
}

async function handleCallback(env, cb) {
  const data = cb.data || "";
  const i = data.indexOf(":");
  const action = i === -1 ? data : data.slice(0, i);
  const key = i === -1 ? "" : data.slice(i + 1);
  const chatId = cb.message && cb.message.chat && cb.message.chat.id;
  if (action === "plan") return handlePlan(env, key, cb, chatId);
  if (action === "draft") return handleDraft(env, key, cb, chatId);
  if (action === "applied" || action === "skip" || action === "remind")
    return handleStatus(env, action, key, cb);
  return answerCallback(env, cb.id, "");
}

async function handleMessage(env, msg) {
  const chatId = msg.chat.id;
  const text = (msg.text || "").trim();
  if (!text) return;
  if (text.startsWith("/start"))
    return sendMessage(env, chatId,
      `👋 <b>Opportunity Hunter</b> is connected (cloud, always-on).\n` +
      `Your chat id is <code>${chatId}</code>.\n` +
      `Commands: /top · /report · /taste · /coach — or just ask me anything.`);
  if (text.startsWith("/top")) return handleTop(env, chatId);
  if (text.startsWith("/report")) return handleReport(env, chatId);
  if (text.startsWith("/taste")) return handleTaste(env, chatId);
  if (text.startsWith("/coach")) return handleCoach(env, chatId);
  if (text.startsWith("/"))
    return sendMessage(env, chatId, "Try /top · /report · /taste · /coach — or ask me a question.");
  // freeform question -> grounded answer
  const feed = await getFeed(env);
  const ans = await llmComplete(env, askPrompt(await profileBlock(env), feed, text), 450);
  return sendMessage(env, chatId, ans ? esc(ans) : "Couldn't answer right now — try again shortly.");
}

// ─── handlers ────────────────────────────────────────────────────────
async function handlePlan(env, key, cb, chatId) {
  const item = await findItem(env, key);
  if (!item) return answerCallback(env, cb.id, "Couldn't find that item.");
  try {
    await addToInbox(env, item, item.score || 0);
    await setStatus(env, key, "planned", item);
    await answerCallback(env, cb.id, "Queued for TaskFlow ✅");
    await sendMessage(env, chatId,
      `✅ Queued for TaskFlow — run <code>taskflow sync pull</code> (or tap ↓ in the dashboard):\n` +
      `<b>${esc(item.title)}</b>`);
  } catch (e) {
    await answerCallback(env, cb.id, "Couldn't queue it — try again shortly.");
  }
}

async function handleStatus(env, action, key, cb) {
  const item = await findItem(env, key);
  const status = action === "applied" ? "applied" : action === "skip" ? "skipped" : "remind";
  await setStatus(env, key, status, item);
  const msg = action === "applied" ? "Marked as applied ✅ — nice one!"
    : action === "skip" ? "Skipped — I won't nag you about this."
      : `I'll remind you in ${env.REMIND_DAYS || 3} days ⏰`;
  return answerCallback(env, cb.id, msg);
}

async function handleDraft(env, key, cb, chatId) {
  const item = await findItem(env, key);
  if (!item) return answerCallback(env, cb.id, "Couldn't find that item.");
  await answerCallback(env, cb.id, "✍️ Drafting your application — one sec…");
  const text = await llmComplete(env, draftPrompt(await profileBlock(env), item), 400);
  return sendMessage(env, chatId, text
    ? `✍️ <b>Draft — ${esc(item.title.slice(0, 60))}</b>\n\n${esc(text)}\n\n<i>Tweak it and send. Good luck. 🚀</i>`
    : "Couldn't generate a draft right now — try again shortly.");
}

async function handleTop(env, chatId) {
  const feed = await getFeed(env);
  const top = feed.slice(0, 5);
  if (!top.length) return sendMessage(env, chatId, "No opportunities yet — let the hunter run.");
  return sendMessage(env, chatId, "<b>Top opportunities</b>\n" +
    top.map((it) => `${it.score}/10 — <b>${esc(it.title.slice(0, 60))}</b>`).join("\n"));
}

async function handleTaste(env, chatId) {
  const d = await kvGet(env, "taste", {});
  const sig = d.signals || 0;
  if (sig < 3)
    return sendMessage(env, chatId,
      `🧪 Still learning your taste — ${sig} signal(s) so far. Tap ✅/➕/⏭ on a few more.`);
  return sendMessage(env, chatId,
    `🧠 <b>What I've learned about your taste</b> (${sig} signals)\n` +
    `👍 You go for: <b>${(d.likes || []).join(", ") || "—"}</b>\n` +
    `👎 You skip: <b>${(d.avoids || []).join(", ") || "—"}</b>`);
}

async function handleCoach(env, chatId) {
  const feed = await getFeed(env);
  const elite = feed.filter((it) => (it.score || 0) >= 7).slice(0, 15);
  if (elite.length < 3)
    return sendMessage(env, chatId,
      "🧭 Not enough high-value opportunities in your feed yet to coach on. Let the hunter run a few days, then ask again.");
  const context = elite.map((it) => `- ${it.title.slice(0, 74)} (${it.source})`).join("\n");
  const text = await llmComplete(env, coachPrompt(await profileBlock(env), context), 650);
  return sendMessage(env, chatId, text ? esc(text) : "Couldn't coach right now — try again shortly.");
}

async function handleReport(env, chatId) {
  const t = await kvGet(env, "tracker", {});
  const feed = await getFeed(env);
  const recent = (e) => { const d = Date.parse(e.updated_at); return d && (Date.now() - d) / 864e5 <= 7; };
  const applied = Object.values(t).filter((e) => e.status === "applied" && recent(e));
  const skipped = Object.values(t).filter((e) => e.status === "skipped" && recent(e));
  const reminders = Object.values(t).filter((e) => e.status === "remind");
  const acted = new Set(Object.keys(t).filter((k) => ["applied", "skipped"].includes(t[k].status)));
  const regret = feed
    .filter((it) => !acted.has(it.key) && (it.score || 0) >= 7 && it.deadline)
    .map((it) => ({ it, days: Math.round((Date.parse(it.deadline) - Date.now()) / 864e5) }))
    .filter((x) => x.days >= 0 && x.days <= 21)
    .sort((a, b) => a.days - b.days)
    .slice(0, 5);
  const lines = ["📊 <b>Weekly Opportunity Report</b>", "",
    `✅ Applied this week: <b>${applied.length}</b>`];
  applied.slice(0, 5).forEach((e) => lines.push(`   • ${esc((e.title || "").slice(0, 50))}`));
  lines.push(`⏭ Skipped this week: <b>${skipped.length}</b>`);
  lines.push(`⏰ Reminders pending: <b>${reminders.length}</b>`, "");
  if (regret.length) {
    lines.push("⚠️ <b>Closing soon — you haven't acted on these:</b>");
    regret.forEach(({ it, days }) => {
      const when = days === 0 ? "today" : days === 1 ? "tomorrow" : `${days} days`;
      lines.push(`   • [${it.score}/10] ${esc(it.title.slice(0, 46))} — <b>${when}</b>`);
    });
  } else {
    lines.push("🎉 Nothing high-value slipping through the cracks. Nice.");
  }
  return sendMessage(env, chatId, lines.join("\n"));
}

// ─── opportunity feed (from the public repo) ─────────────────────────
async function getFeed(env) {
  try {
    const r = await fetch(env.OPHUNTER_FEED_URL, {
      headers: { "User-Agent": "ophunter-bot" }, cf: { cacheTtl: 300 },
    });
    if (!r.ok) return [];
    const d = await r.json();
    return d.items || [];
  } catch (e) { return []; }
}
async function findItem(env, key) {
  const feed = await getFeed(env);
  return feed.find((x) => x.key === key);
}

// ─── KV state: tracker + taste ───────────────────────────────────────
async function kvGet(env, k, def) {
  const v = await env.BOT_KV.get(k);
  return v ? JSON.parse(v) : def;
}
async function kvPut(env, k, v) { await env.BOT_KV.put(k, JSON.stringify(v)); }

async function setStatus(env, key, status, item) {
  const t = await kvGet(env, "tracker", {});
  const e = t[key] || {};
  e.status = status;
  e.updated_at = new Date().toISOString().slice(0, 10);
  if (item) {
    e.title = item.title; e.url = item.url; e.score = item.score;
    e.deadline = item.deadline; e.tags = item.tags || [];
  }
  if (status === "remind") {
    const days = Number(env.REMIND_DAYS || 3);
    e.remind_at = new Date(Date.now() + days * 864e5).toISOString().slice(0, 10);
  } else { delete e.remind_at; }
  t[key] = e;
  await kvPut(env, "tracker", t);
  await relearnTaste(env, t);
}

const STOP_TAGS = new Set(["ophunter", "inbox", "opportunity", "program",
  "in-season", "opening-soon", "learning", "news"]);
async function relearnTaste(env, tracker) {
  tracker = tracker || await kvGet(env, "tracker", {});
  const pos = {}, neg = {};
  for (const e of Object.values(tracker)) {
    const tags = (e.tags || []).map((t) => t.toLowerCase()).filter((t) => !STOP_TAGS.has(t));
    const bucket = (e.status === "applied" || e.status === "planned") ? pos
      : (e.status === "skipped" ? neg : null);
    if (!bucket) continue;
    for (const t of tags) bucket[t] = (bucket[t] || 0) + 1;
  }
  const all = new Set([...Object.keys(pos), ...Object.keys(neg)]);
  const net = {}; for (const t of all) net[t] = (pos[t] || 0) - (neg[t] || 0);
  const likes = [...all].filter((t) => net[t] > 0).sort((a, b) => net[b] - net[a]).slice(0, 6);
  const avoids = [...all].filter((t) => net[t] < 0).sort((a, b) => net[a] - net[b]).slice(0, 6);
  const signals = Object.values(pos).reduce((a, b) => a + b, 0) + Object.values(neg).reduce((a, b) => a + b, 0);
  await kvPut(env, "taste", { likes, avoids, signals });
}

// ─── TaskFlow inbox (GitHub Contents API) ────────────────────────────
function ghHeaders(env) {
  return {
    "Authorization": `Bearer ${env.TASKFLOW_SYNC_TOKEN}`,
    "Accept": "application/vnd.github+json",
    "User-Agent": "ophunter-bot",
  };
}
function inboxUrl(env) {
  return `https://api.github.com/repos/${env.TASKFLOW_SYNC_REPO}/contents/inbox.json`;
}
function b64decodeUtf8(b64) {
  const bin = atob((b64 || "").replace(/\n/g, ""));
  const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}
function b64encodeUtf8(str) {
  const bytes = new TextEncoder().encode(str);
  let bin = ""; for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}
async function ghGetInbox(env) {
  const r = await fetch(inboxUrl(env), { headers: ghHeaders(env) });
  if (r.status === 404) return { items: [], sha: null };
  if (!r.ok) throw new Error(`gh get inbox ${r.status}`);
  const data = await r.json();
  let items = [];
  try { items = JSON.parse(b64decodeUtf8(data.content)); } catch (e) { items = []; }
  return { items: Array.isArray(items) ? items : [], sha: data.sha };
}
async function ghPutInbox(env, items, sha, message) {
  const body = { message, content: b64encodeUtf8(JSON.stringify(items, null, 2)) };
  if (sha) body.sha = sha;
  const r = await fetch(inboxUrl(env), {
    method: "PUT", headers: { ...ghHeaders(env), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`gh put inbox ${r.status}`);
}
async function addToInbox(env, item, score) {
  const { items, sha } = await ghGetInbox(env);
  const ref = `OPH-${item.key}`;
  if (items.some((x) => x.external_ref === ref)) return true;
  items.push(toInboxItem(item, score));
  await ghPutInbox(env, items, sha, `ophunter: queue ${item.title.slice(0, 48)} [skip ci]`);
  return true;
}

// ── inbox item builder (mirrors taskflow/cloud_sync.py + integration.py) ──
const TYPE_RULES = [
  [["internship", "intern"], "internship"],
  [["fellowship"], "fellowship"],
  [["scholarship", "grant"], "scholarship"],
  [["residency"], "residency"],
  [["ambassador"], "ambassador"],
  [["hackathon", "hack2skill"], "hackathon"],
  [["conference", "webinar", "summit", "meetup", "workshop", "expo", "symposium"], "event"],
  [["competition", "contest", "challenge", "kaggle", "codeforces", "leetcode", "codechef", "atcoder"], "competition"],
  [["certification", "certificate", "credential", "course", "nanodegree"], "certification"],
  [["research", "paper", "arxiv", "preprint"], "research"],
];
const SOURCE_FALLBACK = { programs: "program", github: "learning", reddit: "news", hackernews: "news", arxiv: "research" };
const ACTION_VERB = {
  internship: "Apply:", fellowship: "Apply:", scholarship: "Apply:", residency: "Apply:",
  ambassador: "Apply:", program: "Apply:", hackathon: "Register:", competition: "Register:",
  event: "Attend:", research: "Read:", certification: "Start:", learning: "Explore:",
  news: "Read:", opportunity: "Check:",
};
function classifyType(item) {
  const hay = `${item.title} ${item.ai_summary || ""} ${(item.tags || []).join(" ")} ${item.source}`.toLowerCase();
  for (const [keys, tag] of TYPE_RULES) if (keys.some((k) => hay.includes(k))) return tag;
  return SOURCE_FALLBACK[item.source] || "opportunity";
}
function priorityWord(score) { return score >= 9 ? "critical" : score >= 7 ? "high" : "low"; }
function buildTitle(item, score) {
  const type = classifyType(item);
  const verb = ACTION_VERB[type] || "Check:";
  return `${verb} ${item.title.slice(0, 80)} #${type} #OPHunter !${priorityWord(score)}`;
}
function buildNote(item) {
  const parts = [];
  if (item.ai_summary) parts.push(`Why this matters: ${item.ai_summary}`);
  if (item.action_plan && item.action_plan.length)
    parts.push("Plan: " + item.action_plan.map((s, i) => `${i + 1}. ${s}`).join("  "));
  parts.push(`Source: ${item.source} · via OP Hunter`);
  return parts.join("\n");
}
function toInboxItem(item, score) {
  const out = {
    inbox_id: crypto.randomUUID(),
    source: "ophunter",
    external_ref: `OPH-${item.key}`,
    title: buildTitle(item, score),
    priority: priorityWord(score),
    notes: buildNote(item),
    links: item.url ? [{ url: item.url, title: item.title.slice(0, 60) }] : [],
    created_at: new Date().toISOString().slice(0, 19),
  };
  if (item.deadline) { out.deadline = item.deadline; out.deadline_type = "hard"; }
  return out;
}

// ─── LLM provider chain (Groq -> Cerebras -> OpenRouter) ─────────────
function providers(env) {
  const list = [];
  if (env.GROQ_API_KEY) list.push({ base: "https://api.groq.com/openai/v1", key: env.GROQ_API_KEY, model: "llama-3.3-70b-versatile" });
  if (env.CEREBRAS_API_KEY) list.push({ base: "https://api.cerebras.ai/v1", key: env.CEREBRAS_API_KEY, model: "gpt-oss-120b" });
  if (env.OPENROUTER_API_KEY) list.push({ base: "https://openrouter.ai/api/v1", key: env.OPENROUTER_API_KEY, model: "google/gemma-4-31b-it:free" });
  return list;
}
async function llmComplete(env, prompt, maxTokens = 500) {
  for (const p of providers(env)) {
    try {
      const r = await fetch(`${p.base}/chat/completions`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${p.key}`, "Content-Type": "application/json" },
        body: JSON.stringify({ model: p.model, messages: [{ role: "user", content: prompt }], temperature: 0.5, max_tokens: maxTokens }),
      });
      if (!r.ok) continue;
      const data = await r.json();
      const text = data && data.choices && data.choices[0] && data.choices[0].message && data.choices[0].message.content;
      if (text) return text.trim();
    } catch (e) { /* try next */ }
  }
  return "";
}

// ─── profile + prompts (mirror user_profile.py / draft.py / ask.py / coach.py) ──
const PROFILE_BASE =
  `NAME: Mohith
IDENTITY: 2nd-year B.Tech CSE (AI & ML) student in India. Builder over consumer. Author of TaskFlow and Nova. Wants Google/Microsoft-level and international (esp. Japan) opportunities.
LONG-TERM GOAL: Become an exceptional AI engineer, builder, and entrepreneur before graduation.
TOP INTERESTS: AI agents, LLMs, generative AI, AI engineering, machine learning, deep learning, Python, software engineering.
HIGH-VALUE COMPANIES: Google, DeepMind, Microsoft, NVIDIA, Anthropic, OpenAI, Hugging Face, Meta, GitHub, Kaggle, IBM, AWS.
VALUES: Portfolio/resume value over cash or swag. Builder over consumer. International exposure. Startup mindset.`;

async function profileBlock(env) {
  const d = await kvGet(env, "taste", {});
  if ((d.signals || 0) >= 3) {
    const parts = [];
    if (d.likes && d.likes.length) parts.push("gravitates toward: " + d.likes.join(", "));
    if (d.avoids && d.avoids.length) parts.push("tends to skip: " + d.avoids.join(", "));
    if (parts.length) return PROFILE_BASE + "\nLEARNED FROM BEHAVIOUR — " + parts.join("; ") + ".";
  }
  return PROFILE_BASE;
}

function draftPrompt(profile, item) {
  return `You are helping Mohith write a short application note for an opportunity.

OPPORTUNITY:
${item.title}
${item.ai_summary || ""}

Mohith's profile:
${profile}

Write a first-person application paragraph (120-160 words) that Mohith can adapt and send.
Rules:
- Specific to THIS opportunity (reference what it actually is) — not generic.
- Lead with genuine fit: why it matches his goals and what he concretely brings
  (e.g. building TaskFlow and Nova, AI agents, the strengths in his profile).
- Confident but honest. No clichés like "I am passionate", no invented achievements.
- End with one clear line of intent.
Return ONLY the paragraph — no preamble, no greeting, no sign-off block.`;
}

function askPrompt(profile, feed, question) {
  const ctx = feed.slice(0, 30).map((it) =>
    `- ${it.title.slice(0, 72)} | ${it.score} | ${it.deadline || "rolling"} | ${it.source}`).join("\n") || "(no opportunities tracked yet)";
  const today = new Date().toISOString().slice(0, 10);
  return `You are Mohith's personal opportunity assistant. Answer the question using ONLY the
opportunities listed below (his current feed). Be concise and specific, and cite opportunity
titles. If the answer isn't in the data, say so honestly — never invent opportunities or details.

Mohith's profile (for relevance):
${profile}

Today is ${today}.

Opportunities (title | score/10 | deadline | source):
${ctx}

Question: ${question.slice(0, 300)}

Answer concisely, citing specific titles:`;
}

function coachPrompt(profile, context) {
  return `You are Mohith's career coach — a senior mentor who is direct and honest, not a
cheerleader. Look at the ELITE opportunities he's currently seeing (below) and his profile:

1. GAP: What do these high-value opportunities repeatedly REQUIRE that he most likely doesn't
   have yet? (a published paper, real open-source contributions, a standout project, a specific
   skill, competition results.) Be specific and honest — name the actual gap.
2. PLAN: Give 2-3 CONCRETE things to build or do over the next 4-6 weeks to close that gap, each
   tied to what these opportunities actually want. Real actions, not "study more". Lead with the
   highest-leverage one.

Ground everything in his REAL profile and these specific opportunities. No clichés, no fluff.

Mohith's profile:
${profile}

Elite opportunities he's seeing right now:
${context}

Coaching (GAP, then PLAN):`;
}

// ─── Telegram + util ─────────────────────────────────────────────────
async function tg(env, method, payload) {
  return fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
}
async function answerCallback(env, id, text) {
  return tg(env, "answerCallbackQuery", { callback_query_id: id, text });
}
async function sendMessage(env, chatId, text, buttons) {
  const p = { chat_id: chatId, text, parse_mode: "HTML", disable_web_page_preview: true };
  if (buttons) p.reply_markup = { inline_keyboard: buttons };
  return tg(env, "sendMessage", p);
}
function esc(s) {
  return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Exported for unit-testing the inbox-item format against the Python side.
export { classifyType, priorityWord, buildTitle, buildNote, toInboxItem };
