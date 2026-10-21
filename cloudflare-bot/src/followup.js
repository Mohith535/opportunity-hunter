/**
 * Follow-ups, outcomes and reminders — the daily job (21 Oct 2026).
 *
 * Why. By 21 Oct he had tapped ✅ Applied on 14 jobs and not one had an outcome recorded, so nothing
 * could learn which packs get replies — and "⏰ Remind" replied "I'll remind you in 3 days" while no
 * code ever sent the reminder (the only sender was the retired laptop listener, reading another file).
 *
 * Pure functions only: index.js does the KV and Telegram I/O. Run the checks: node test/followup.test.mjs
 */

export const FOLLOW_DAYS = [7, 14];   // ask "heard back?" a week after applying, then once more
export const MAX_AGE = 30;            // an application older than this is not chased — it is history
export const MAX_PER_DAY = 3;         // the first run met nine old applications; three a day, oldest first
export const OUTCOMES = { interview: "interview", rejected: "rejected", noreply: "no_reply" };

const DAY = 864e5;

export function daysBetween(fromISO, toISO) {
  const a = Date.parse(String(fromISO).slice(0, 10) + "T00:00:00Z");
  const b = Date.parse(String(toISO).slice(0, 10) + "T00:00:00Z");
  return Number.isNaN(a) || Number.isNaN(b) ? NaN : Math.round((b - a) / DAY);
}

/** When he applied: applied_at (from 21 Oct) or, for older taps, the day the status was set. */
export function appliedOn(e) {
  return (e && (e.applied_at || (e.status === "applied" && e.updated_at))) || "";
}

/**
 * What today's run should send.
 *   reminders: [[key, entry]]        — a ⏰ Remind whose date has come
 *   followups: [[key, entry, day]]   — an application with no outcome, 7 or 14 days on
 */
export function duePlan(tracker, todayISO, maxPerDay = MAX_PER_DAY) {
  const reminders = [], follow = [];
  for (const [key, e] of Object.entries(tracker || {})) {
    if (!e || typeof e !== "object") continue;
    if (e.status === "remind" && e.remind_at && String(e.remind_at) <= todayISO) reminders.push([key, e]);
    // A job it cannot name is not asked about: "21 days ago you applied to an application — heard
    // back?" is a question he cannot answer. Five of his taps (before 4 Oct) have no title anywhere.
    if (e.status !== "applied" || e.outcome || !e.title) continue;
    const age = daysBetween(appliedOn(e), todayISO);
    if (!(age >= FOLLOW_DAYS[0]) || age > MAX_AGE) continue;
    const sent = new Set(e.followups || []);
    const day = [...FOLLOW_DAYS].reverse().find((d) => age >= d && !sent.has(d));
    if (day) follow.push([key, e, day, age]);
  }
  follow.sort((x, y) => y[3] - x[3]);                       // oldest first: they matter soonest
  return { reminders: reminders.slice(0, 5), followups: follow.slice(0, maxPerDay).map((f) => f.slice(0, 3)) };
}

/** The entry after a follow-up for `day` was sent (never asks the same day twice). */
export function markFollowed(e, day, todayISO) {
  return { ...e, followups: [...new Set([...(e.followups || []), day])], followed_at: todayISO };
}

/** The entry after he answered. "No reply" a week in is not an outcome yet — a week later it is. */
export function recordOutcome(e, kind, todayISO) {
  const out = { ...e };
  if (kind === "noreply" && daysBetween(appliedOn(e), todayISO) < FOLLOW_DAYS[1]) {
    out.noreply_at = todayISO;
    return out;
  }
  out.outcome = OUTCOMES[kind] || kind;
  out.outcome_at = todayISO;
  return out;
}

export function followupButtons(key) {
  return [[{ text: "🎉 Interview", callback_data: `out:interview:${key}` },
           { text: "❌ Rejected", callback_data: `out:rejected:${key}` },
           { text: "🔇 No reply yet", callback_data: `out:noreply:${key}` }]];
}

const esc = (s) => String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export function followupText(e, day) {
  const t = esc((e.title || "an application").slice(0, 120));
  return `📮 <b>${day} days ago you applied to</b>\n${t}\n\nHeard back? One tap — it teaches OPH which packs work.`;
}

export function reminderText(e) {
  const t = esc((e.title || "something you saved").slice(0, 120));
  return `⏰ <b>Reminder</b> — you asked me to bring this back:\n${t}` + (e.url ? `\n${esc(e.url)}` : "");
}

/** What the bot says after an outcome tap. A "no reply" a week in gets a follow-up he can send. */
export function outcomeReply(e, kind, todayISO) {
  if (kind === "interview")
    return "🎉 Logged. Open the pack's job.md — its asks table is your interview prep: every row is a question they can ask.";
  if (kind === "rejected")
    return "Logged. One rejection is data, not a verdict — OPH weighs it into what it shows you next.";
  const when = appliedOn(e) || "recently";
  const title = (e.title || "the role").slice(0, 80);
  if (daysBetween(appliedOn(e), todayISO) >= FOLLOW_DAYS[1])
    return "Logged as no reply. Two weeks of silence is common — it is not a judgement of your work.";
  return "Noted — I'll ask again in a week. If there is a recruiter email, this is a short follow-up you can send " +
    "(edit it first):\n\n" +
    `<i>Hi — I applied for ${esc(title)} on ${esc(when)} and wanted to say I'm still very interested. ` +
    "Happy to share anything else that helps. — K Mohith Kannan</i>";
}
