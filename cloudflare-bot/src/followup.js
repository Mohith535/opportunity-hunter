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
    // followup:false — something whose answer comes months later (SRFP results are Mar–Apr).
    if (e.status !== "applied" || e.outcome || !e.title || e.followup === false) continue;
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
  return `⏰ <b>Reminder</b> — you asked me to bring this back:\n${t}` + (e.note ? `\n\n${esc(e.note)}` : "")
    + (e.url ? `\n${esc(e.url)}` : "");
}

/** A to-do gets Done; an opportunity gets the usual Applied / Skip. Both can come back again. */
export function reminderButtons(key, e) {
  const again = { text: "⏰ Again", callback_data: `remind:${key}` };
  return e && e.todo ? [[{ text: "✅ Done", callback_data: `done:${key}` }, again]]
    : [[{ text: "✅ Applied", callback_data: `applied:${key}` }, { text: "⏭ Skip", callback_data: `skip:${key}` }, again]];
}

/**
 * Staged reminders (22 Oct): "remember me" for something with steps, like SRFP — ask a teacher,
 * write the 150–250 words, submit, check the letter went in. The entry carries the current step
 * (remind_at + note) and the rest in `steps`; after each send it moves to the next step still ahead.
 */
export function afterReminder(e, todayISO) {
  const out = { ...e, reminded_at: todayISO };
  delete out.remind_at; delete out.note; delete out.steps;
  const rest = (e.steps || []).filter((s) => s && String(s.at) > todayISO);
  if (rest.length) {
    out.remind_at = rest[0].at;
    if (rest[0].note) out.note = rest[0].note;
    if (rest.length > 1) out.steps = rest.slice(1);
  }
  return out;
}

const ISO = /^\d{4}-\d{2}-\d{2}$/;
/** POST /remind body → [key, tracker entry], or { error }. Keys are slugs, never a 12-hex feed key. */
export function reminderEntry(b, todayISO) {
  if (!b || typeof b !== "object") return { error: "body must be JSON" };
  if (!/^[a-z0-9][a-z0-9-]{2,39}$/.test(b.key || "") || /^[0-9a-f]{12}$/.test(b.key))
    return { error: "key: 3–40 lowercase letters, digits or dashes" };
  if (typeof b.title !== "string" || !b.title.trim() || b.title.length > 120) return { error: "title: 1–120 chars" };
  const steps = Array.isArray(b.steps) ? b.steps : [];
  if (!steps.length || steps.length > 10) return { error: "steps: 1–10 of {at, note}" };
  for (const s of steps)
    if (!s || !ISO.test(s.at || "") || (s.note && (typeof s.note !== "string" || s.note.length > 600)))
      return { error: "each step: at = YYYY-MM-DD, note ≤ 600 chars" };
  const ahead = steps.filter((s) => s.at >= todayISO).sort((x, y) => (x.at < y.at ? -1 : 1));
  if (!ahead.length) return { error: "every step is in the past" };
  const e = { status: "remind", title: b.title.trim(), updated_at: todayISO, remind_at: ahead[0].at, followup: false };
  if (ahead[0].note) e.note = ahead[0].note;
  if (ahead.length > 1) e.steps = ahead.slice(1);
  if (typeof b.url === "string" && /^https:\/\//.test(b.url)) e.url = b.url;
  if (ISO.test(b.deadline || "")) e.deadline = b.deadline;
  if (b.todo) e.todo = true;
  return [b.key, e];
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
