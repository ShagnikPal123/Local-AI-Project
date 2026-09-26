/* Nyx shell cache.
 *
 * Nyx's page is served by the Nyx engine on this computer, so when the engine is
 * off a reload used to show the browser's "This site can't be reached" page —
 * with nothing to click. This worker keeps the last good copy of the app shell,
 * so the page still loads and can offer one button: Turn on Nyx.
 *
 * Rules:
 *  - /api/* is never cached. Answers must always be live.
 *  - Page loads are network-first: when the engine is up you always get the
 *    newest build; the cache is only the fallback.
 *  - Hashed /assets/* files never change, so they are cache-first.
 *  - The shell's own assets are cached up front. The page load that installs
 *    this worker is not controlled by it, so without this the offline copy of
 *    the page pointed at scripts and images that were never stored.
 */

const CACHE = "nyx-shell-v3";

/* The engine's CORS layer adds "Vary: Origin" whenever a request carries an
   Origin header, and module scripts always do. Honouring Vary made every cached
   script a miss exactly when it mattered — the engine off — so the offline page
   loaded with no JavaScript and rendered blank. These are same-origin, hashed
   files; Vary means nothing for them. */
const MATCH = { ignoreVary: true };

const OFFLINE_PAGE = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Nyx Ichos</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#161826;color:#e9e9ed;
font-family:Inter,system-ui,Segoe UI,sans-serif}main{text-align:center;max-width:420px;padding:24px}
a{display:inline-block;margin-top:18px;padding:14px 26px;border-radius:12px;background:#9184d9;color:#12141f;
font-weight:600;text-decoration:none}p{color:#9397ab;line-height:1.6}</style></head>
<body><main><h1>Nyx is turned off</h1><p>Nyx runs on this computer. Turn it on, then reload this page.</p>
<a href="nyx://open">Turn on Nyx</a><p style="font-size:13px">First time? Your browser may ask to open Nyx — choose Open.</p>
</main></body></html>`;

const ASSET_IN_HTML = /(?:src|href)="(\/assets\/[^"]+)"/g;
const ASSET_IN_JS = /\/assets\/[A-Za-z0-9._-]+\.(?:png|svg|jpe?g|webp|gif|css|woff2?)/g;

/** Store the page and everything it needs to render with the engine off. */
async function cacheShell(html) {
  const cache = await caches.open(CACHE);
  const wanted = new Set(["/favicon.svg"]);
  for (const match of html.matchAll(ASSET_IN_HTML)) wanted.add(match[1]);

  // Images and styles imported from JavaScript are not in the HTML; find them
  // in the bundle so the offline screen is not missing its avatar.
  for (const path of [...wanted]) {
    if (!path.endsWith(".js")) continue;
    try {
      const response = await fetch(path);
      if (!response.ok) continue;
      const text = await response.clone().text();
      await cache.put(path, response);
      for (const found of text.matchAll(ASSET_IN_JS)) wanted.add(found[0]);
    } catch {
      /* engine went away mid-way; whatever was stored still helps */
    }
  }

  await Promise.all(
    [...wanted].map(async (path) => {
      if (await cache.match(path, MATCH)) return;
      try {
        const response = await fetch(path);
        if (response.ok) await cache.put(path, response);
      } catch {
        /* best effort */
      }
    }),
  );
}

async function refreshShell() {
  const response = await fetch("/", { cache: "no-store" });
  if (!response.ok) return;
  const html = await response.clone().text();
  const cache = await caches.open(CACHE);
  await cache.put("/", response);
  await cacheShell(html);
}

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(refreshShell().catch(() => undefined));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(names.filter((n) => n.startsWith("nyx-shell-") && n !== CACHE).map((n) => caches.delete(n)));
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;

  if (request.mode === "navigate") {
    event.respondWith(
      (async () => {
        try {
          const response = await fetch(request);
          if (response.ok) {
            const copy = response.clone();
            // A rebuilt UI has new hashed asset names; store them for next time.
            event.waitUntil(
              (async () => {
                const html = await copy.clone().text();
                const cache = await caches.open(CACHE);
                await cache.put("/", copy);
                await cacheShell(html);
              })().catch(() => undefined),
            );
          }
          return response;
        } catch {
          const cached = await caches.match("/", MATCH);
          return cached || new Response(OFFLINE_PAGE, { headers: { "Content-Type": "text/html; charset=utf-8" } });
        }
      })(),
    );
    return;
  }

  if (url.pathname.startsWith("/assets/") || /\.(?:png|svg|ico|woff2?)$/.test(url.pathname)) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(CACHE);
        const hit = await cache.match(request, MATCH);
        if (hit) return hit;
        try {
          const response = await fetch(request);
          if (response.ok) await cache.put(request, response.clone());
          return response;
        } catch {
          return Response.error();
        }
      })(),
    );
  }
});
