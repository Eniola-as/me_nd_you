// Me & You service worker, served from /service-worker.js (scope "/").
//
// Privacy rule: nothing personal is ever stored on the device. Only public
// static files and the offline page are cached. Pages always come from the
// network (offline, the offline page is shown instead, never a stored copy).
// The API, sockets, account actions and the admin are left to the browser.
//
// Bump the version whenever the cached files change, so old caches are dropped.
const CACHE_NAME = "me-and-you-v6";
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

// Push notifications (notifications.push): the server sends only a short
// generic text ("Your partner sent you a message.") and a link on this site,
// never names or content, since it can show on a lock screen.
const PUSH_FALLBACK = { title: "Me & You", body: "Something new in your space.", url: "/space/", tag: "me-and-you" };

// Only a path on this site: never another origin ("//x" or "https://x").
function sitePath(url) {
  return typeof url === "string" && url.startsWith("/") && !url.startsWith("//") ? url : "/space/";
}

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = (event.data && event.data.json()) || {};
  } catch (err) {
    data = {};
  }
  const note = { ...PUSH_FALLBACK, ...data };
  event.waitUntil(
    self.registration.showNotification(note.title, {
      body: note.body,
      tag: note.tag, // A newer one of the same kind replaces the older.
      icon: "/static/icons/icon-192.png",
      badge: "/static/icons/icon-192.png",
      data: { url: sitePath(note.url) },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = sitePath(event.notification.data && event.notification.data.url);
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const open = windows.find((w) => new URL(w.url).origin === self.location.origin);
      if (open) return open.focus().then(() => open.navigate(url));
      return self.clients.openWindow(url);
    })
  );
});
