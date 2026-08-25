# Inbox dashboard — private, free, installable-as-an-app

A tiny Cloudflare Worker that shows your inbox summary as a private web page on your phone — free,
and installable to your home screen like a real app (PWA). Kept separate from the Opportunity Hunter
bot worker.

**How it's private:** the page only exists at a URL that contains a long **secret** you choose. No
secret in the URL → 404. (We use a secret URL instead of a login page because logins break the
"Add to Home Screen" app install — a secret URL doesn't.)

**How it works:** your computer runs `python -m inbox --publish`, which pushes the latest dashboard
to this Worker; the Worker stores it and serves it at your private URL.

---

## Deploy (one time, ~10 minutes)

You need a free Cloudflare account and Node installed. From inside this `cloudflare-inbox/` folder:

1. **Log in:** `npx wrangler login`
2. **Create the storage:** `npx wrangler kv namespace create INBOX_KV`
   → it prints an `id`. Paste that id into `wrangler.toml` (replace `PASTE_KV_ID_HERE`).
3. **Pick a secret** — a long random string, e.g. run `openssl rand -hex 24` (or make up 30+ random
   characters). Set it:
   `npx wrangler secret put INBOX_SECRET` → paste your secret when asked.
4. **Deploy:** `npx wrangler deploy`
   → it prints your worker URL, like `https://inbox-dashboard.<you>.workers.dev`
5. **Tell your computer where to publish.** Add these to the project's `.env` (gitignored):
   ```
   INBOX_WORKER_URL=https://inbox-dashboard.<you>.workers.dev
   INBOX_SECRET=<the same secret from step 3>
   ```

## Use it

```
python -m inbox --publish          # scans, and pushes the page to your private URL
```
The command prints your private link:  `https://inbox-dashboard.<you>.workers.dev/<secret>/`
Open it on your phone → tap the browser menu → **Add to Home Screen** → it installs as an app.
Re-run `--publish` any time to refresh what the app shows.

## Notes
- Keep the secret URL private (don't paste it in public chats). To rotate it, `wrangler secret put
  INBOX_SECRET` again with a new value and update `.env`.
- Free tier: 100k requests/day — far more than a personal dashboard needs.
- The page also works offline once opened (the app caches the last summary).
