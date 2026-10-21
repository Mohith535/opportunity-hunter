// node test/followup.test.mjs
import { duePlan, markFollowed, recordOutcome, followupButtons, outcomeReply, daysBetween, appliedOn,
         reminderEntry, afterReminder, reminderText, reminderButtons,
         MAX_PER_DAY } from "../src/followup.js";

const R = [];
const check = (name, cond, detail = "") => R.push([name, !!cond, detail]);
const TODAY = "2026-10-21";

check("1. days are counted, not felt", daysBetween("2026-10-14", TODAY) === 7 && daysBetween("2026-09-30", TODAY) === 21);
check("2. old taps have no applied_at: the day the status was set stands in",
  appliedOn({ status: "applied", updated_at: "2026-10-06" }) === "2026-10-06");

const t = {
  a7: { status: "applied", applied_at: "2026-10-14", title: "A" },
  a14: { status: "applied", applied_at: "2026-10-07", title: "B", followups: [7] },
  a6: { status: "applied", applied_at: "2026-10-15", title: "too soon" },
  done: { status: "applied", applied_at: "2026-10-01", outcome: "interview" },
  stale: { status: "applied", updated_at: "2026-07-05", title: "July" },
  r1: { status: "remind", remind_at: "2026-10-20", title: "R" },
  r2: { status: "remind", remind_at: "2026-10-25" },
  skip: { status: "skipped", updated_at: "2026-10-01" },
};
const p = duePlan(t, TODAY);
const keys = p.followups.map(([k, , d]) => `${k}@${d}`);
check("3. a week on, ask; two weeks on, ask again; never before a week", keys.includes("a7@7") && keys.includes("a14@14") && !keys.some((k) => k.startsWith("a6")), keys);
check("4. an answered application is never chased", !keys.some((k) => k.startsWith("done")));
check("5. a July application is history, not a follow-up", !keys.some((k) => k.startsWith("stale")));
check("6. a reminder fires on its day, not before", p.reminders.map(([k]) => k).join() === "r1");

const many = {};
for (let i = 0; i < 9; i++) many[`k${i}`] = { status: "applied", updated_at: `2026-10-0${i + 1}`, title: `T${i}` };
const m = duePlan(many, TODAY);
check("7. nine due at once (his first run) → three a day, oldest first",
  m.followups.length === MAX_PER_DAY && m.followups[0][0] === "k0", m.followups.map((f) => f[0]));

const e14 = markFollowed(t.a7, 7, TODAY);
check("8. once sent, the same day's question is not asked again",
  !duePlan({ a7: e14 }, TODAY).followups.length && duePlan({ a7: e14 }, "2026-10-28").followups[0][2] === 14);

check("9. 'no reply' a week in is not an outcome — it asks again at 14 days",
  !recordOutcome(t.a7, "noreply", TODAY).outcome && recordOutcome(t.a7, "noreply", TODAY).noreply_at === TODAY);
check("10. 'no reply' at two weeks is recorded as no_reply",
  recordOutcome(t.a14, "noreply", TODAY).outcome === "no_reply");
check("11. interview / rejected are outcomes", recordOutcome(t.a7, "interview", TODAY).outcome === "interview"
  && recordOutcome(t.a7, "rejected", TODAY).outcome === "rejected");
const btns = followupButtons("abcdef123456").flat();
check("12. three buttons, callback data within Telegram's 64 bytes",
  btns.length === 3 && btns.every((b) => new TextEncoder().encode(b.callback_data).length <= 64));
check("13. a week of silence gets a follow-up he can send, in his name, HTML-escaped",
  /K Mohith Kannan/.test(outcomeReply({ ...t.a7, title: "<Intern> & Co" }, "noreply", TODAY))
  && /&lt;Intern&gt; &amp; Co/.test(outcomeReply({ ...t.a7, title: "<Intern> & Co" }, "noreply", TODAY)));

check("14. a job it cannot name is never asked about (5 of his oldest taps have no title)",
  !duePlan({ x: { status: "applied", updated_at: "2026-09-30" } }, TODAY).followups.length
  && duePlan({ x: { status: "applied", updated_at: "2026-09-30", title: "T" } }, TODAY).followups.length === 1);

// ── staged reminders (22 Oct): SRFP — ask a teacher, write, submit, check — one entry, several dates ──
const body = { key: "srfp-2027", title: "IAS Summer Research Fellowship", url: "https://webjapps.ias.ac.in/fellowship2027/",
  deadline: "2026-11-30", steps: [{ at: "2026-11-01", note: "write it" }, { at: "2026-10-26", note: "ask a teacher" },
    { at: "2026-11-27", note: "last call" }] };
const [rk, re] = reminderEntry(body, TODAY);
check("15. a plan is stored as its first date + the rest, in date order, never chased as an application",
  rk === "srfp-2027" && re.remind_at === "2026-10-26" && re.note === "ask a teacher"
  && re.steps.map((s) => s.at).join() === "2026-11-01,2026-11-27" && re.followup === false, re);
const s1 = afterReminder(re, "2026-10-26"), s2 = afterReminder(s1, "2026-11-01"), s3 = afterReminder(s2, "2026-11-27");
check("16. after each send it moves to the next step; after the last there is nothing left to fire",
  s1.remind_at === "2026-11-01" && s1.note === "write it" && s2.remind_at === "2026-11-27" && !s2.steps
  && !s3.remind_at && !s3.note && s3.reminded_at === "2026-11-27", [s1, s2, s3]);
check("17. an ⏰ Again that overshoots a step skips it, not fires twice",
  afterReminder({ ...re, remind_at: "2026-11-03" }, "2026-11-03").remind_at === "2026-11-27");
check("18. the step's note is in the message, escaped",
  /ask a teacher/.test(reminderText(re)) && /&lt;b&gt;/.test(reminderText({ ...re, note: "<b>" })));
const tb = reminderButtons("todo-x", { todo: true }).flat().map((b) => b.callback_data);
check("19. a to-do gets Done + Again; an opportunity keeps Applied / Skip / Again",
  tb.join() === "done:todo-x,remind:todo-x" && reminderButtons("k", {}).flat().length === 3);
check("20. bad input is refused: a feed-style key, no steps, past-only dates, a long note",
  reminderEntry({ ...body, key: "abcdef123456" }, TODAY).error && reminderEntry({ ...body, steps: [] }, TODAY).error
  && reminderEntry({ ...body, steps: [{ at: "2026-01-01" }] }, TODAY).error
  && reminderEntry({ ...body, steps: [{ at: "2026-11-01", note: "x".repeat(601) }] }, TODAY).error
  && reminderEntry(null, TODAY).error);
check("21. an applied SRFP is not asked 'heard back?' a week on — results come in March",
  !duePlan({ s: { status: "applied", applied_at: "2026-10-10", title: "SRFP", followup: false } }, TODAY).followups.length);

let ok = 0;
for (const [n, pass, d] of R) { console.log(`  ${pass ? "PASS" : "FAIL"}  ${n}${!pass && d ? `   [${JSON.stringify(d)}]` : ""}`); if (pass) ok++; }
console.log(`${ok}/${R.length} passed`);
process.exit(ok === R.length ? 0 : 1);
