// Tests for src/schedule.js — run: node test/schedule.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { CRON, jobsAt, WORKFLOWS, alertDue, clockAlert } from "../src/schedule.js";

let n = 0;
const t = (name, fn) => { fn(); n++; console.log("  PASS", name); };
const at = (hhmm) => jobsAt(new Date(`2026-11-05T${hhmm}:00Z`));

t("08:00 IST starts the hunt, 09:00 IST the follow-ups — nothing else at those minutes", () => {
  assert.deepEqual(at("02:30"), ["hunt"]);
  assert.deepEqual(at("03:30"), ["followups"]);
});
t("the fresh watcher: every :50 UTC from 01:50 to 17:50 (07:20–23:20 IST), 17 a day, none overnight", () => {
  const day = [];
  for (let h = 0; h < 24; h++) for (const m of [0, 30, 50]) if (jobsAt(new Date(Date.UTC(2026, 10, 5, h, m))).includes("fresh")) day.push(h);
  assert.deepEqual(day, Array.from({ length: 17 }, (_, i) => i + 1));
  assert.deepEqual(at("00:50"), []);
  assert.deepEqual(at("18:50"), []);
});
t("the other :30 slots the cron fires at do nothing", () => {
  for (const h of ["01", "04", "10", "17"]) assert.deepEqual(at(`${h}:30`), []);
});
t("wrangler.toml's cron is the one this module decides for", () => {
  const toml = readFileSync(new URL("../wrangler.toml", import.meta.url), "utf8");
  assert.ok(toml.includes(`crons = ["${CRON}"]`), "wrangler.toml [triggers] crons must be exactly CRON");
});
t("the hunt tells its run it is the morning one (the Sunday shortlist reads it); fresh needs no inputs", () => {
  assert.deepEqual(WORKFLOWS.hunt, { file: "daily.yml", inputs: { scheduled: "true" }, label: "this morning's hunt" });
  assert.equal(WORKFLOWS.fresh.file, "fresh.yml");
  assert.deepEqual(WORKFLOWS.fresh.inputs, {});
});
t("a refusal alerts once a day per job, never once an hour", () => {
  assert.equal(alertDue({}, "fresh", "2026-11-05"), true);
  assert.equal(alertDue({ fresh: "2026-11-05" }, "fresh", "2026-11-05"), false);
  assert.equal(alertDue({ fresh: "2026-11-04" }, "fresh", "2026-11-05"), true);
  assert.equal(alertDue({ fresh: "2026-11-05" }, "hunt", "2026-11-05"), true);
});
t("the alert says what broke and how to fix it", () => {
  assert.match(clockAlert("hunt", 401), /this morning's hunt: GitHub said 401[\s\S]*GH_DISPATCH_TOKEN/);
  assert.match(clockAlert("fresh", 502), /fresh-postings check: GitHub said 502[\s\S]*next slot/);
});
t("both workflows accept what the bot sends (daily.yml declares `scheduled`; neither keeps GitHub's schedule)", () => {
  const read = (f) => readFileSync(new URL(`../../.github/workflows/${f}`, import.meta.url), "utf8").split("\r").join("");
  const daily = read("daily.yml"), fresh = read("fresh.yml");
  assert.match(daily, /\n      scheduled:\n/);
  assert.doesNotMatch(daily, /\n  schedule:/);
  assert.doesNotMatch(fresh, /\n  schedule:/);
  assert.match(fresh, /workflow_dispatch:/);
});
console.log(`${n} passed`);
