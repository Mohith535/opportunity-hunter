/**
 * EDI -> OPH intake (4 Oct 2026). EDI reads a posting he sends it, researches the team, and calls this
 * Worker's `Intake.pack(packet)` over a Cloudflare service binding; OPH builds the resume in the cloud
 * and sends it to his OPH chat, where its Applied/Skip/Remind buttons live. EDI then polls
 * `Intake.statuses([key])` and closes its "apply to …" task when he taps Applied or Skip.
 *
 * The contract is EDI's `worker/src/oph.ts` (IntakePacket v1): field names are fixed on both sides.
 * Pure functions here so `node test/intake.test.mjs` can check them without a Worker.
 */

export const JD_MIN = 200;          // the contract: the posting, whole — a sentence is not a posting
export const JD_MAX = 15_000;
export const INTAKE_TTL = 60 * 60 * 24 * 30;   // 30 days in KV

const str = (v, max) => typeof v === "string" && v.trim().length > 0 && v.length <= max;
const strs = (v, n, max) => Array.isArray(v) && v.length <= n && v.every((x) => typeof x === "string" && x.length <= max);

/** "" when the packet is a v1 packet from EDI we can build from; otherwise why not. */
export function validatePacket(p) {
  if (!p || typeof p !== "object") return "no packet";
  if (p.v !== 1) return `unsupported packet version ${p.v}`;
  if (p.source !== "edi") return "packet is not from EDI";
  if (!str(p.title, 200) || !str(p.company, 200)) return "title and company are required";
  if (!str(p.jd, JD_MAX) || p.jd.trim().length < JD_MIN) return `jd must be ${JD_MIN}-${JD_MAX} characters`;
  if (p.url !== null && p.url !== undefined && !(str(p.url, 2000) && /^https?:\/\//.test(p.url))) return "url must be http(s)";
  const r = p.requirements;
  if (!r || !strs(r.must ?? [], 40, 400) || !strs(r.bonus ?? [], 40, 400) || !strs(r.responsibilities ?? [], 40, 400))
    return "requirements must be lists of short strings";
  if (!strs(p.keywords ?? [], 80, 120)) return "keywords must be a list of short strings";
  if (JSON.stringify(p).length > 60_000) return "packet too large";
  return "";
}

/**
 * The 12-hex key his tracker and buttons use. Derived from the posting itself, so EDI's "resend to OPH"
 * of the same job lands on the same key — one tracker row, not two.
 */
export async function intakeKey(p) {
  const basis = `intake:${(p.url || `${p.company}|${p.title}`).trim().toLowerCase()}`;
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(basis));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 12);
}

/**
 * EDI's contract says statuses are `applied | skip | remind | planned | null`; OPH's tracker stores
 * "skipped" for a ⏭ tap. Without this translation EDI's `s === 'skip'` never matched and a skipped job
 * would have stayed open in EDI forever.
 */
export function statusesFor(tracker, keys) {
  const map = { applied: "applied", skipped: "skip", skip: "skip", remind: "remind", planned: "planned" };
  const out = {};
  for (const k of Array.isArray(keys) ? keys.slice(0, 50) : []) {
    const s = tracker && tracker[k] && tracker[k].status;
    out[k] = s && map[s] ? map[s] : null;
  }
  return out;
}

/** What his tracker and the 📦 card need from a packet — the same fields a feed item has. */
export function itemFromPacket(key, p) {
  return { key, title: `${p.title} — ${p.company}`, url: p.url || "", score: 10, deadline: p.deadline || "",
           tags: ["internship", "edi"], source: "edi" };
}
