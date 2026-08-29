/**
 * Inbox Assistant — a PRIVATE, FREE dashboard on Cloudflare Workers.
 *
 * Privacy: every route is gated by a secret in the URL path (INBOX_SECRET). Only someone with the
 * full secret URL can see anything; everything else is a 404. We use a secret path rather than a
 * login screen on purpose — login sessions don't survive "Add to Home Screen", but a secret URL does,
 * so the page installs cleanly as a phone app (PWA).
 *
 * Your computer pushes the latest dashboard HTML here (POST /<secret>/push); the Worker stores it in
 * KV and serves it (GET /<secret>/), injecting the PWA bits so you can install it like an app.
 * Separate from the Opportunity Hunter bot worker — this one only ever handles your inbox page.
 */

const ICON = 'data:image/svg+xml,' + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">' +
  '<rect width="100" height="100" rx="22" fill="#2E7D5B"/>' +
  '<g fill="none" stroke="#fff" stroke-width="6" stroke-linejoin="round">' +
  '<rect x="21" y="33" width="58" height="34" rx="4"/><path d="M21 37l29 20 29-20"/></g></svg>');

const SW = `const C='inbox-v1';
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x!==C).map(x=>caches.delete(x))))));
self.addEventListener('fetch',e=>{if(e.request.method!=='GET')return;
 e.respondWith(fetch(e.request).then(r=>{const c=r.clone();caches.open(C).then(x=>x.put(e.request,c));return r;}).catch(()=>caches.match(e.request)));});`;

function manifest(base) {
  return JSON.stringify({
    name: 'My Inbox', short_name: 'Inbox', start_url: base + '/', scope: base + '/',
    display: 'standalone', background_color: '#12160f', theme_color: '#2E7D5B',
    icons: [{ src: ICON, sizes: 'any', type: 'image/svg+xml', purpose: 'any maskable' }],
  });
}

function injectPWA(html, base) {
  const head =
    `<link rel="manifest" href="${base}/manifest.webmanifest">` +
    `<meta name="theme-color" content="#2E7D5B">` +
    `<link rel="apple-touch-icon" href="${ICON}">` +
    `<meta name="apple-mobile-web-app-capable" content="yes">` +
    `<meta name="apple-mobile-web-app-title" content="Inbox">` +
    `<script>if('serviceWorker'in navigator){navigator.serviceWorker.register('${base}/sw.js')}</script>`;
  return html.includes('</head>') ? html.replace('</head>', head + '</head>') : head + html;
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const parts = url.pathname.split('/').filter(Boolean);
    const secret = parts[0] || '';
    // The whole app is invisible without the exact secret.
    if (!env.INBOX_SECRET || secret !== env.INBOX_SECRET) {
      return new Response('Not found', { status: 404 });
    }
    const base = '/' + secret;
    const rest = '/' + parts.slice(1).join('/');

    if (req.method === 'POST' && rest === '/push') {
      await env.INBOX_KV.put('latest', await req.text());
      await env.INBOX_KV.put('updated', new Date().toISOString());
      return new Response('ok');
    }

    // Phone → local action bridge. The dashboard POSTs a tap here ({id, act}); it's queued in KV until
    // your computer drains it and applies it through the TaskFlow CLI on the next sync. The phone can't
    // reach your machine directly, so this is the free, no-server way to act on a task from your pocket.
    if (req.method === 'POST' && rest === '/action') {
      let body = {};
      try { body = await req.json(); } catch (e) {}
      const id = String(body.id == null ? '' : body.id).slice(0, 32);
      const act = body.act === 'snooze' ? 'snooze' : 'done';
      if (id) {
        let q;
        try { q = JSON.parse((await env.INBOX_KV.get('actions')) || '[]'); } catch (e) { q = []; }
        if (!Array.isArray(q)) q = [];
        q.push({ id, act, at: new Date().toISOString() });
        if (q.length > 200) q = q.slice(-200);
        await env.INBOX_KV.put('actions', JSON.stringify(q));
      }
      return new Response('ok');
    }
    if (req.method === 'POST' && rest === '/drain') {
      let q;
      try { q = JSON.parse((await env.INBOX_KV.get('actions')) || '[]'); } catch (e) { q = []; }
      await env.INBOX_KV.put('actions', '[]');
      return new Response(JSON.stringify(Array.isArray(q) ? q : []),
        { headers: { 'content-type': 'application/json' } });
    }
    if (rest === '/manifest.webmanifest') {
      return new Response(manifest(base), { headers: { 'content-type': 'application/manifest+json' } });
    }
    if (rest === '/sw.js') {
      return new Response(SW, { headers: { 'content-type': 'application/javascript' } });
    }

    let html = await env.INBOX_KV.get('latest');
    if (!html) {
      html = '<!doctype html><meta charset="utf-8">' +
        '<meta name="viewport" content="width=device-width,initial-scale=1">' +
        '<body style="font-family:system-ui,sans-serif;padding:2rem;max-width:600px;margin:auto">' +
        '<h2>No inbox summary yet 🌱</h2><p>On your computer, run ' +
        '<code>python -m inbox --publish</code> to fill this page.</p></body>';
    }
    return new Response(injectPWA(html, base),
      { headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' } });
  },
};
