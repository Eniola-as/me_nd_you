const CACHE_NAME = "couple-game-cache-v1";
const urlsToCache = [
  "/",
  "/modes/",
  "/play/",
  "/static/manifest.json",
  "/static/icons/icon.png",
  "/static/icons/icon.png"
];

self.addEventListener("install", event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", event => {
  event.respondWith(
    caches.match(event.request)
      .then(response => response || fetch(event.request))
  );
});
