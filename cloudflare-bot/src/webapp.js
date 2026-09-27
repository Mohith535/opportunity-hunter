/**
 * The Telegram Mini App — OPH's real UI. Opens inside Telegram from the ☰ menu button or the
 * "Open OPH" button, so there is no login and no token to paste: Telegram signs every launch with
 * the bot token, and verifyInitData() checks that signature and that the user is the owner.
 *
 *   GET  /app              the app (HTML)
 *   GET  /app/api/state    { target, updated_at, source, top[] }
 *   PUT  /app/api/target   save the whole target (source "app")
 *   POST /app/api/pack     { key } -> start the cloud build for one pack
 *
 * Every /app/api call carries the launch data in X-Init-Data.
 */

const enc = new TextEncoder();

async function hmac(keyBytes, msg) {
  const key = await crypto.subtle.importKey("raw", keyBytes, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(msg)));
}
const hex = (b) => [...b].map((x) => x.toString(16).padStart(2, "0")).join("");

/**
 * Telegram's documented check (core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app):
 * secret = HMAC_SHA256(key="WebAppData", bot_token); hash = HMAC_SHA256(secret, data_check_string),
 * where data_check_string is every field except `hash`, sorted, as "k=v" joined by "\n".
 * Returns the user object, or null. maxAgeSec rejects replayed old launches.
 */
export async function verifyInitData(initData, botToken, nowSec = Math.floor(Date.now() / 1000), maxAgeSec = 86400) {
  if (!initData || !botToken) return null;
  const p = new URLSearchParams(initData);
  const hash = p.get("hash");
  if (!hash) return null;
  p.delete("hash");
  const dcs = [...p.entries()].map(([k, v]) => `${k}=${v}`).sort().join("\n");
  const secret = await hmac(enc.encode("WebAppData"), botToken);
  const want = hex(await hmac(secret, dcs));
  if (want.length !== hash.length) return null;
  let diff = 0;
  for (let i = 0; i < want.length; i++) diff |= want.charCodeAt(i) ^ hash.charCodeAt(i);
  if (diff) return null;
  const when = Number(p.get("auth_date") || 0);
  if (!when || nowSec - when > maxAgeSec) return null;
  try { return JSON.parse(p.get("user") || "null"); } catch (e) { return null; }
}

/** Only the owner. With no OWNER_CHAT_ID set, nobody — the app edits his hunt. */
export async function appUser(request, env) {
  const user = await verifyInitData(request.headers.get("X-Init-Data") || "", env.TELEGRAM_BOT_TOKEN);
  if (!user || !env.OWNER_CHAT_ID) return null;
  return String(user.id).trim() === String(env.OWNER_CHAT_ID).trim() ? user : null;
}
