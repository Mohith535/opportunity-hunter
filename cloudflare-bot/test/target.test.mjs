// Tests for src/target.js — run: node test/target.test.mjs
import assert from "node:assert/strict";
import { applyCommand, formatTarget, parseList, parsePay, validTarget, KINDS } from "../src/target.js";

const T = {
  active: true, goal: "An internship", by: "2026-12-05", focus: ["internship", "job"],
  locations: ["mumbai", "remote"], min_pay_per_month: 30000, require_pay: false,
  roles: { tier1: ["ai engineer", "backend"], tier2: ["data analyst"] }, avoid: ["sales", "seo"],
};
const TODAY = "2026-09-27";
let n = 0;
const t = (name, fn) => { fn(); n++; console.log("  PASS", name); };

t("pay parses the ways people type it", () => {
  assert.equal(parsePay("30000"), 30000);
  assert.equal(parsePay("30,000"), 30000);
  assert.equal(parsePay("30k"), 30000);
  assert.equal(parsePay("₹35000"), 35000);
  assert.equal(parsePay("1.2l"), 120000);
  assert.ok(Number.isNaN(parsePay("lots")));
});
t("a list with +/- is an edit; without is a replacement; multi-word survives", () => {
  assert.deepEqual(parseList("+pune -remote"), { mode: "edit", add: ["pune"], remove: ["remote"] });
  assert.deepEqual(parseList("+ai agents, -seo"), { mode: "edit", add: ["ai agents"], remove: ["seo"] });
  assert.deepEqual(parseList("Mumbai, Remote"), { mode: "replace", items: ["mumbai", "remote"] });
});
t("city +pune -remote edits in place", () => {
  const r = applyCommand(T, "city +pune -remote", TODAY);
  assert.deepEqual(r.target.locations, ["mumbai", "pune"]);
});
t("the input is never mutated", () => {
  applyCommand(T, "city +pune", TODAY);
  assert.deepEqual(T.locations, ["mumbai", "remote"]);
});
t("tier1 +rust lands in roles.tier1, deduped", () => {
  const r = applyCommand(T, "tier1 +rust +backend", TODAY);
  assert.deepEqual(r.target.roles.tier1, ["ai engineer", "backend", "rust"]);
});
t("avoid +pr works on an empty list too", () => {
  const r = applyCommand({ active: true }, "avoid +pr", TODAY);
  assert.deepEqual(r.target.avoid, ["pr"]);
});
t("focus rejects a kind the hunt doesn't know", () => {
  assert.match(applyCommand(T, "focus internship, jobs", TODAY).error, /Not a kind/);
  assert.deepEqual(applyCommand(T, "focus internship, fellowship", TODAY).target.focus, ["internship", "fellowship"]);
  assert.ok(KINDS.includes("internship") && KINDS.length === 14);
});
t("pay: set, remove, reject nonsense", () => {
  assert.equal(applyCommand(T, "pay 35k", TODAY).target.min_pay_per_month, 35000);
  assert.equal(applyCommand(T, "pay none", TODAY).target.min_pay_per_month, undefined);
  assert.ok(applyCommand(T, "pay 12", TODAY).error);
});
t("by: a past date or a bad date is refused", () => {
  assert.ok(applyCommand(T, "by 2026-01-01", TODAY).error);
  assert.ok(applyCommand(T, "by next friday", TODAY).error);
  assert.equal(applyCommand(T, "by 2026-12-20", TODAY).target.by, "2026-12-20");
});
t("off / on / paid", () => {
  assert.equal(applyCommand(T, "off", TODAY).target.active, false);
  assert.equal(applyCommand(T, "paid on", TODAY).target.require_pay, true);
  assert.ok(applyCommand(T, "paid maybe", TODAY).error);
});
t("show / help / unknown", () => {
  assert.equal(applyCommand(T, "", TODAY).show, true);
  assert.equal(applyCommand(T, "help", TODAY).help, true);
  assert.match(applyCommand(T, "salary 5", TODAY).error, /don't know/);
});
t("the reply escapes HTML and counts days", () => {
  const s = formatTarget({ target: { ...T, goal: "R&D <x>" }, updated_at: "2026-09-27T10:00:00Z", source: "phone" }, TODAY);
  assert.match(s, /R&amp;D &lt;x&gt;/);
  assert.match(s, /2026-12-05 \(69 days\)/);   // 27 Sep -> 5 Dec: 3 + 31 + 30 + 5 = 69
  assert.match(s, /from your phone/);
  assert.match(formatTarget(null, TODAY), /sync_secrets/);
});
t("validTarget rejects shapes that would break the hunt", () => {
  assert.equal(validTarget(T), "");
  assert.ok(validTarget([]));
  assert.ok(validTarget({ focus: "internship" }));
});
console.log(`${n}/${n} passed`);
