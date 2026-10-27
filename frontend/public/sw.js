// tax.ng service worker: keeps the public app usable on weak or no signal.
// Scope is deliberately narrow:
//  * The signed-in app (/app/) and every non-GET request are never touched.
//  * Only public reference data is cached (laws, guides, news, meta).
//    Calculations, Tax AI and anything account-related always go to the server.
const VERSION = "taxng-v1";
const SHELL = ["/", "/assets/styles.css", "/assets/site.js", "/manifest.webmanifest", "/icons/icon-192.png"];
const CACHEABLE_API = [/^\/api\/meta$/, /^\/api\/laws(\/[^/]+)?$/, /^\/api\/guides(\/[^/]+)?$/, /^\/api\/news$/];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

async function networkFirst(request) {
  const cache = await caches.open(VERSION);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch (err) {
    const hit = await cache.match(request);
    if (hit) return hit;
    throw err;
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(VERSION);
  const hit = await cache.match(request);
  const refresh = fetch(request)
    .then((response) => {
      if (response.ok) cache.put(request, response.clone());
      return response;
    })
    .catch(() => hit);
  return hit || refresh;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/app")) return;

  if (url.pathname.startsWith("/api/")) {
    if (CACHEABLE_API.some((re) => re.test(url.pathname))) event.respondWith(networkFirst(request));
    return;
  }
  if (request.mode === "navigate") {
    event.respondWith(networkFirst(request).catch(() => caches.match("/")));
    return;
  }
  if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/icons/")) {
    event.respondWith(staleWhileRevalidate(request));
  }
});
