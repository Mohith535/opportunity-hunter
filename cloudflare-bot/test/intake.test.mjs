// Tests for src/intake.js — run: node test/intake.test.mjs
import assert from "node:assert/strict";
import { validatePacket, intakeKey, statusesFor, itemFromPacket, JD_MIN } from "../src/intake.js";

const P = {
  v: 1, source: "edi", at: "2026-10-04T10:00:00Z",
  url: "https://jobs.ea.com/en_US/careers/JobDetail/Software-Engineer-Intern/216034",
  title: "Software Engineer Intern", company: "Electronic Arts", team: "EA Mobile - Slingshot Games (India)",
  location: "Hyderabad, Telangana, India", work_model: "hybrid", worker_type: "Intern - Temporary Employee",
  paid: true, deadline: null, jd: "x".repeat(JD_MIN + 50),
  requirements: { must: ["Have a solid foundation of data structures and algorithms"], bonus: [], responsibilities: [] },
  keywords: ["C++", "Java"], research: null, his_words: "private", edi_ref: "apply-to-electronic-arts",
};
let n = 0;
const t = async (name, fn) => { await fn(); n++; console.log("  PASS", name); };

await t("a real v1 packet from EDI is accepted", () => assert.equal(validatePacket(P), ""));
await t("wrong version / source / missing company are refused with a reason", () => {
  assert.match(validatePacket({ ...P, v: 2 }), /version/);
  assert.match(validatePacket({ ...P, source: "x" }), /EDI/);
  assert.match(validatePacket({ ...P, company: "" }), /company/);
});
await t("a sentence is not a posting (jd too short)", () => assert.match(validatePacket({ ...P, jd: "short" }), /jd/));
await t("a non-http url is refused; url null is fine", () => {
  assert.match(validatePacket({ ...P, url: "javascript:alert(1)" }), /url/);
  assert.equal(validatePacket({ ...P, url: null }), "");
});
await t("requirements must be lists of strings", () =>
  assert.match(validatePacket({ ...P, requirements: { must: "x" } }), /requirements/));
await t("the key is 12 hex, and the SAME job re-sent gets the SAME key", async () => {
  const a = await intakeKey(P), b = await intakeKey({ ...P, at: "2026-10-05T00:00:00Z", his_words: "again" });
  assert.match(a, /^[0-9a-f]{12}$/);
  assert.equal(a, b);
  assert.notEqual(a, await intakeKey({ ...P, url: "https://jobs.ea.com/other" }));
});
await t("statuses: 'skipped' in OPH's tracker is 'skip' in EDI's contract", () => {
  const tr = { a: { status: "applied" }, b: { status: "skipped" }, c: { status: "remind" }, d: { status: "planned" } };
  assert.deepEqual(statusesFor(tr, ["a", "b", "c", "d", "z"]),
    { a: "applied", b: "skip", c: "remind", d: "planned", z: null });
});
await t("the tracker item carries title, url and key", () => {
  const it = itemFromPacket("abc123abc123", P);
  assert.equal(it.key, "abc123abc123");
  assert.match(it.title, /Software Engineer Intern — Electronic Arts/);
  assert.equal(it.url, P.url);
});
console.log(`${n}/${n} passed`);
