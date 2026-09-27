// Tests for src/webapp.js — run: node test/webapp.test.mjs
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { verifyInitData, appUser } from "../src/webapp.js";

const TOKEN = "123456:TEST-BOT-TOKEN";
const NOW = 1790500000;

// Build initData exactly as Telegram does, with node's own crypto (a second implementation).
function sign(fields, token = TOKEN) {
  const dcs = Object.keys(fields).sort().map((k) => `${k}=${fields[k]}`).join("\n");
  const secret = createHmac("sha256", "WebAppData").update(token).digest();
  const hash = createHmac("sha256", secret).update(dcs).digest("hex");
  return new URLSearchParams({ ...fields, hash }).toString();
}
const user = JSON.stringify({ id: 42, first_name: "M" });
let n = 0;
const t = async (name, fn) => { await fn(); n++; console.log("  PASS", name); };

await t("a genuine launch is accepted and returns the user", async () => {
  const u = await verifyInitData(sign({ auth_date: String(NOW - 10), query_id: "q", user }), TOKEN, NOW);
  assert.equal(u.id, 42);
});
await t("a tampered field is rejected", async () => {
  const s = sign({ auth_date: String(NOW - 10), user }).replace("%22id%22%3A42", "%22id%22%3A43");
  assert.equal(await verifyInitData(s, TOKEN, NOW), null);
});
await t("signed with another bot's token is rejected", async () => {
  assert.equal(await verifyInitData(sign({ auth_date: String(NOW - 10), user }, "999:OTHER"), TOKEN, NOW), null);
});
await t("an old launch (replay) is rejected", async () => {
  assert.equal(await verifyInitData(sign({ auth_date: String(NOW - 90000), user }), TOKEN, NOW), null);
});
await t("empty / missing hash is rejected", async () => {
  assert.equal(await verifyInitData("", TOKEN, NOW), null);
  assert.equal(await verifyInitData("auth_date=1&user=x", TOKEN, NOW), null);
});
await t("appUser: only the owner, and nobody when OWNER_CHAT_ID is unset", async () => {
  const init = sign({ auth_date: String(Math.floor(Date.now() / 1000) - 5), user });
  const req = { headers: new Map([["X-Init-Data", init]]) };
  req.headers.get = req.headers.get.bind(req.headers);
  assert.equal((await appUser(req, { TELEGRAM_BOT_TOKEN: TOKEN, OWNER_CHAT_ID: "42" })).id, 42);
  assert.equal(await appUser(req, { TELEGRAM_BOT_TOKEN: TOKEN, OWNER_CHAT_ID: "7" }), null);
  assert.equal(await appUser(req, { TELEGRAM_BOT_TOKEN: TOKEN }), null);
});
console.log(`${n}/${n} passed`);
