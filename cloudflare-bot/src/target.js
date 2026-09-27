/**
 * /target — edit the standing hunt target from the phone.
 *
 * Pure functions only (no Telegram, no KV), so they can be tested with plain Node:
 *   node test/target.test.mjs
 *
 * The target is the same JSON as the laptop's hunt_target.json. It lives in KV under "target" as
 * { target, updated_at, source }, and the daily cloud run reads it from there before anything else.
 */

// Mirrors filters/focus.py KINDS — a focus the hunt doesn't know would silently match nothing.
export const KINDS = ["hackathon", "research", "internship", "job", "fellowship", "grant", "startup",
  "scholarship", "contest", "ambassador", "meetup", "program", "news", "learning"];

const LIST_FIELDS = {
  city: "locations", cities: "locations", place: "locations", places: "locations", locations: "locations",
  focus: "focus", tier1: "roles.tier1", tier2: "roles.tier2", avoid: "avoid",
};
const MAX_ITEMS = 40, MAX_WORD = 60, MAX_GOAL = 300;

export const HELP =
  "🎯 <b>Change your target from here</b>\n" +
  "<code>/target</code> — show it\n" +
  "<code>/target pay 30000</code> · <code>/target pay none</code>\n" +
  "<code>/target city +pune -remote</code> · <code>/target city mumbai, remote</code>\n" +
  "<code>/target focus internship, job</code>\n" +
  "<code>/target tier1 +rust</code> · <code>/target tier2 -devops</code>\n" +
  "<code>/target avoid +pr</code>\n" +
  "<code>/target by 2026-12-05</code> · <code>/target goal …</code>\n" +
  "<code>/target paid on|off</code> — push unpaid listings down, or not\n" +
  "<code>/target off</code> · <code>/target on</code>\n" +
  "Changes apply from the next 08:00 run, and your laptop picks them up on its next hunt.";

function clean(s) { return String(s || "").trim().toLowerCase().replace(/\s+/g, " ").slice(0, MAX_WORD); }

function getPath(t, path) {
  return path.split(".").reduce((o, k) => (o && typeof o === "object" ? o[k] : undefined), t);
}
function setPath(t, path, v) {
  const keys = path.split(".");
  let o = t;
  for (const k of keys.slice(0, -1)) { if (!o[k] || typeof o[k] !== "object") o[k] = {}; o = o[k]; }
  o[keys[keys.length - 1]] = v;
}

/** "30000", "30,000", "30k", "₹30000", "rs 30k" -> 30000; NaN when it isn't a number. */
export function parsePay(s) {
  const m = String(s || "").toLowerCase().replace(/[₹,\s]|rs\.?|inr/g, "").match(/^(\d+(?:\.\d+)?)(k|l|lakh)?$/);
  if (!m) return NaN;
  const n = parseFloat(m[1]) * (m[2] === "k" ? 1e3 : m[2] ? 1e5 : 1);
  return Math.round(n);
}

/** "+pune -remote", "+ai engineer, -seo" -> edits; "mumbai, remote" -> a replacement list. */
export function parseList(value) {
  const parts = String(value || "").split(/,|\s+(?=[+-])/).map((p) => p.trim()).filter(Boolean);
  const edits = parts.every((p) => p[0] === "+" || p[0] === "-");
  return edits
    ? { mode: "edit", add: parts.filter((p) => p[0] === "+").map((p) => clean(p.slice(1))).filter(Boolean),
        remove: parts.filter((p) => p[0] === "-").map((p) => clean(p.slice(1))).filter(Boolean) }
    : { mode: "replace", items: parts.map((p) => clean(p.replace(/^[+]/, ""))).filter(Boolean) };
}

/**
 * Apply one "/target …" command to a target object. Returns { target, said } on success,
 * { show: true } / { help: true } for read-only commands, or { error } with a message to show.
 * Never mutates the input.
 */
export function applyCommand(current, argText, today = new Date().toISOString().slice(0, 10)) {
  const t = JSON.parse(JSON.stringify(current || {}));
  const text = String(argText || "").trim();
  if (!text || text === "show") return { show: true };
  if (text === "help") return { help: true };
  const sp = text.indexOf(" ");
  const field = (sp === -1 ? text : text.slice(0, sp)).toLowerCase();
  const value = sp === -1 ? "" : text.slice(sp + 1).trim();

  if (field === "on" || field === "off") {
    t.active = field === "on";
    return { target: t, said: field === "on" ? "Target is ON — every hunt applies it." : "Target is OFF — hunts ignore it until /target on." };
  }
  if (field === "pay") {
    if (/^(none|0|off)$/i.test(value)) { delete t.min_pay_per_month; return { target: t, said: "Pay floor removed." }; }
    const n = parsePay(value);
    if (!Number.isFinite(n) || n < 1000 || n > 10000000) return { error: "Say it like <code>/target pay 30000</code> (rupees per month)." };
    t.min_pay_per_month = n;
    return { target: t, said: `Pay floor is now Rs ${n.toLocaleString("en-IN")}/month.` };
  }
  if (field === "paid") {
    if (!/^(on|off)$/i.test(value)) return { error: "Use <code>/target paid on</code> or <code>/target paid off</code>." };
    t.require_pay = value.toLowerCase() === "on";
    return { target: t, said: t.require_pay ? "Listings that state no pay are now pushed down." : "Unpaid-or-unstated listings are shown on their merit again." };
  }
  if (field === "by") {
    if (/^(none|off)$/i.test(value)) { delete t.by; return { target: t, said: "No deadline on the target now." }; }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || isNaN(Date.parse(value + "T00:00:00Z")))
      return { error: "Use a date like <code>/target by 2026-12-05</code>." };
    if (value < today) return { error: `${value} has already passed.` };
    t.by = value;
    return { target: t, said: `Aiming to have it settled by ${value}.` };
  }
  if (field === "goal") {
    if (!value) return { error: "Write the goal after it: <code>/target goal …</code>" };
    t.goal = value.slice(0, MAX_GOAL);
    return { target: t, said: "Goal updated." };
  }
  const path = LIST_FIELDS[field];
  if (!path) return { error: `I don't know "${field}". Send <code>/target help</code>.` };
  if (!value) return { error: `Give it values: <code>/target ${field} +something</code>.` };
  const p = parseList(value);
  const before = (getPath(t, path) || []).map(clean);
  let after;
  if (p.mode === "replace") after = [...new Set(p.items)];
  else after = [...new Set([...before.filter((x) => !p.remove.includes(x)), ...p.add])];
  if (path === "focus") {
    const bad = after.filter((k) => !KINDS.includes(k));
    if (bad.length) return { error: `Not a kind I hunt: ${bad.join(", ")}. Kinds: ${KINDS.join(", ")}.` };
  }
  if (after.length > MAX_ITEMS) return { error: `That's over ${MAX_ITEMS} entries — trim it first.` };
  setPath(t, path, after);
  const label = { locations: "Places", focus: "Hunting", "roles.tier1": "Tier 1 roles", "roles.tier2": "Tier 2 roles", avoid: "Avoiding" }[path];
  return { target: t, said: `${label}: ${after.join(", ") || "(none)"}` };
}

function esc(s) { return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }

/** The /target reply: what the hunts are aiming at right now. */
export function formatTarget(entry, today = new Date().toISOString().slice(0, 10)) {
  const t = (entry && entry.target) || {};
  if (!entry || !entry.target) return "No target in the cloud yet. On your laptop, run <code>py sync_secrets.py</code> once.";
  const list = (xs, n = 8) => (xs && xs.length ? esc(xs.slice(0, n).join(", ")) + (xs.length > n ? ` (+${xs.length - n})` : "") : "—");
  const lines = [`🎯 <b>Your target</b> — ${t.active === false ? "<b>OFF</b>" : "on"}`];
  if (t.goal) lines.push(`<i>${esc(t.goal)}</i>`);
  lines.push(`Hunting: ${list(t.focus)}`);
  lines.push(`Places: ${list(t.locations)}`);
  lines.push(`Pay floor: ${t.min_pay_per_month ? "Rs " + Number(t.min_pay_per_month).toLocaleString("en-IN") + "/month" : "—"}` +
    (t.require_pay ? " (unstated pay pushed down)" : ""));
  if (t.by) {
    const days = Math.round((Date.parse(t.by + "T00:00:00Z") - Date.parse(today + "T00:00:00Z")) / 864e5);
    lines.push(`By: ${esc(t.by)} (${days >= 0 ? days + " days" : "passed"})`);
  }
  const roles = t.roles || {};
  lines.push(`Tier 1: ${list(roles.tier1)}`);
  lines.push(`Tier 2: ${list(roles.tier2)}`);
  lines.push(`Avoid: ${list(t.avoid)}`);
  if (entry.updated_at) lines.push(`<i>Last changed ${esc(String(entry.updated_at).slice(0, 10))} from your ${esc(entry.source || "laptop")}.</i>`);
  lines.push("Change it: <code>/target help</code>");
  return lines.join("\n");
}

/** A target pushed from the laptop must at least look like one. */
export function validTarget(obj) {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return "target must be a JSON object";
  if (JSON.stringify(obj).length > 16000) return "target is too large";
  for (const k of ["focus", "locations", "avoid"])
    if (obj[k] !== undefined && !Array.isArray(obj[k])) return `${k} must be a list`;
  return "";
}
