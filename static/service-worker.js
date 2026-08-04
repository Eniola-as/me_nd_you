const CACHE_NAME = "couple-game-cache-v1";
const urlsToCache = [
  "/",
  "/modes/",
  "/play/",
  "/static/manifest.json",
  "/static/icons/icon.jpg"
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        return Promise.all(
          urlsToCache.map(url => {
            return fetch(url)
              .then(response => {
                if (!response.ok || response.type !== "basic") {
                  console.warn(`Skipping caching for ${url}: ${response.statusText}`);
                  return null;
                }
                return cache.put(url, response);
              })
              .catch(error => {
                console.error(`Failed to fetch ${url}:`, error);
              });
          })
        );
      })
      .catch(error => {
        console.error("Cache open failed:", error);
      })
  );
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    Promise.all([
      self.clients.claim(),
      caches.keys().then(cacheNames => {
        return Promise.all(
          cacheNames.map(name => {
            if (name !== CACHE_NAME) {
              return caches.delete(name);
            }
          })
        );
      })
    ])
  );
});

self.addEventListener("fetch", event => {
  const url = event.request.url;

  // Log all requests to identify problematic ones
  console.log("Handling fetch event for:", url);

  // Ignore non-GET requests and unsupported schemes
  if (
    event.request.method !== "GET" ||
    url.startsWith("chrome-extension://") ||
    url.startsWith("chrome://") ||
    url.startsWith("about:")
  ) {
    console.warn("Ignoring unsupported request:", url);
    return;
  }

  // Handle Google Fonts with stale-while-revalidate strategy
  if (url.startsWith("https://fonts.googleapis.com") || url.startsWith("https://fonts.gstatic.com")) {
    event.respondWith(
      caches.open(CACHE_NAME).then(cache => {
        return fetch(event.request)
          .then(response => {
            if (response.ok) {
              cache.put(event.request, response.clone());
            }
            return response;
          })
          .catch(() => caches.match(event.request));
      })
    );
    return;
  }

  // Default fetch handler
  event.respondWith(
    caches.match(event.request)
      .then(response => {
        if (response) {
          return response;
        }
        return fetch(event.request)
          .then(response => {
            if (!response || response.status !== 200 || response.type !== "basic") {
              console.warn("Skipping caching for:", url);
              return response;
            }
            const responseToCache = response.clone();
            caches.open(CACHE_NAME)
              .then(cache => {
                cache.put(event.request, responseToCache);
              });
            return response;
          })
          .catch(error => {
            console.error(`Fetch failed for ${url}:`, error);
          });
      })
  );
});
