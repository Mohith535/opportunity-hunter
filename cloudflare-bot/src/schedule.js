// The bot is OPH's clock (5 Nov 2026). GitHub's own schedule started the "08:00 IST" hunt 4 h 38 min to
// 7 h 26 min late on every one of 20 days (16 Oct – 4 Nov), and never started the hourly fresh watcher at
// all in its first 5 hours. Cloudflare's cron fires on the minute, so the bot starts both workflows.
// One cron expression (wrangler.toml) covers all three jobs, so the account's cron count doesn't grow.
export const CRON = "30,50 1-17 * * *";

// What runs at a given minute (UTC). Pure, so the test pins every slot.
export function jobsAt(t) {
  const h = t.getUTCHours(), m = t.getUTCMinutes(), out = [];
  if (m === 50 && h >= 1 && h <= 17) out.push("fresh");     // 07:20–23:20 IST, hourly
  if (h === 2 && m === 30) out.push("hunt");                // 08:00 IST: the daily hunt + digest + packs
  if (h === 3 && m === 30) out.push("followups");           // 09:00 IST: reminders + "heard back?"
  return out;
}

// The workflow and inputs each GitHub job is started with. `scheduled` tells the run it is the morning
// hunt, which the Sunday shortlist checks (it used to read GITHUB_EVENT_NAME == "schedule").
export const WORKFLOWS = {
  hunt: { file: "daily.yml", inputs: { scheduled: "true" }, label: "this morning's hunt" },
  fresh: { file: "fresh.yml", inputs: {}, label: "the hourly fresh-postings check" },
};

// GitHub refused a start: one message a day per job, never one an hour.
export function alertDue(sent, job, today) {
  return (sent || {})[job] !== today;
}

export function clockAlert(job, status) {
  const w = WORKFLOWS[job];
  const why = status === 401 || status === 403
    ? "The bot's GitHub token (GH_DISPATCH_TOKEN) has likely expired or lost Actions access. Make a new one " +
      "(opportunity-hunter only, Actions: read and write) and run <code>wrangler secret put GH_DISPATCH_TOKEN</code>."
    : "GitHub may be down. It will try again at the next slot.";
  return `⚠ Couldn't start ${w ? w.label : job}: GitHub said ${status}.\n${why}`;
}
