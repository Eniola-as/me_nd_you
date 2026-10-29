// Me & You service worker, served from /service-worker.js (scope "/").
//
// Privacy rule: nothing personal is ever stored on the device. Only public
// static files and the offline page are cached. Pages always come from the
// network (offline, the offline page is shown instead, never a stored copy).
// The API, sockets, account actions and the admin are left to the browser.
//
// Bump the version whenever the cached files change, so old caches are dropped.
const CACHE_NAME = "me-and-you-v5";
const OFFLINE_PAGE = "/offline/";
const PRECACHE = [
  OFFLINE_PAGE,
  "/static/manifest.json",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/fonts/outfit-latin.woff2",
  "/static/fonts/outfit-latin-ext.woff2",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    Promise.all([
      self.clients.claim(),
      caches.keys().then((names) =>
        Promise.all(names.filter((name) => name !== CACHE_NAME).map((name) => caches.delete(name)))
      ),
    ])
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    // Network only; never stored. Offline: the offline page.
    event.respondWith(
      fetch(request).catch(() =>
        caches.open(CACHE_NAME).then((cache) => cache.match(OFFLINE_PAGE))
      )
    );
    return;
  }

  if (url.pathname.startsWith("/static/")) {
    // Public files: the cached copy, else the network (then cached).
    event.respondWith(
      caches.open(CACHE_NAME).then((cache) =>
        cache.match(request).then(
          (cached) =>
            cached ||
            fetch(request).then((response) => {
              if (response.ok && response.type === "basic") cache.put(request, response.clone());
              return response;
            })
        )
      )
    );
  }
  // Anything else (API, sockets, account actions, admin) is not handled here.
});
