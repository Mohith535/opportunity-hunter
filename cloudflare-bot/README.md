# Opportunity Hunter — always-on Telegram bot (Cloudflare Workers)

The JS port of `telegram_listener.py`, running 24/7 on Cloudflare Workers via a
Telegram **webhook** — so taps, drafts, `/coach`, and questions work **even when
your PC is off**. 100% free, no credit card.

**What it does:** reads opportunities from the public repo's `feed.json`; on a
**Plan** tap it writes the `taskflow-sync` repo's `inbox.json` (you run
`taskflow sync pull` to bring them in); Applied/Skip/Remind + taste live in
Cloudflare **KV**; Draft/Coach/Ask use the Groq→Cerebras→OpenRouter chain.

> The daily **digest** is still sent by GitHub Actions (Python). This Worker only
> handles incoming taps/commands.

---

## Deploy (one-time, ~10 min)

**0. Prereqs:** Node installed (you have it). Use `npx wrangler ...` (no global install needed).

**1. Cloudflare account** — sign up free (no card) at https://dash.cloudflare.com.

**2. Log wrangler in:**
```bash
cd cloudflare-bot
npx wrangler login          # opens a browser to authorize
```

**3. Create the KV namespace** (bot state) and paste its id into `wrangler.toml`:
```bash
npx wrangler kv namespace create BOT_KV
# -> copy the printed id into wrangler.toml under [[kv_namespaces]] id = "..."
```

**4. Set the secrets** (each prompts for the value, nothing is stored in files):
```bash
npx wrangler secret put TELEGRAM_BOT_TOKEN     # your @BotFather token
npx wrangler secret put WEBHOOK_SECRET         # any random string you invent
npx wrangler secret put TASKFLOW_SYNC_TOKEN    # GitHub PAT with repo write on taskflow-sync
npx wrangler secret put GROQ_API_KEY
npx wrangler secret put CEREBRAS_API_KEY
npx wrangler secret put OPENROUTER_API_KEY
```
> **TASKFLOW_SYNC_TOKEN:** create a fine-grained GitHub PAT scoped to the
> `taskflow-sync` repo with **Contents: Read and write**
> (github.com → Settings → Developer settings → Personal access tokens).

**5. Deploy:**
```bash
npx wrangler deploy
# -> prints your Worker URL, e.g. https://ophunter-bot.<your-subdomain>.workers.dev
```

**6. Point Telegram at the Worker** (this switches the bot from your PC to the cloud):
```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=<WORKER_URL>&secret_token=<WEBHOOK_SECRET>"
```
✅ You should get `{"ok":true,...}`.

> ⚠️ Setting a webhook **disables polling** — so **stop the local
> `telegram_listener.py`** (the Worker now handles everything). To go back to local:
> `curl "https://api.telegram.org/bot<TOKEN>/deleteWebhook"` then run the listener again.

**7. (For the daily digest in the cloud)** add these as **GitHub Actions secrets**
on the `opportunity-hunter` repo so the 8 AM run sends the digest to Telegram:
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. The digest's buttons are handled by this Worker.

---

## Test it
Message your bot: `/start`, `/top`, `/coach`, ask *"what's closing this week?"* — and
tap the buttons on a digest. `npx wrangler tail` streams live logs.

## Update later
Edit `src/index.js`, then `npx wrangler deploy`. Done.
