// The service worker's caching rules, run in a sandbox with a fake cache
// and network. The rule that matters most for privacy: signed-in pages and
// API/socket/account traffic are never stored on the device.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = fs.readFileSync(path.join(__dirname, "../../static/service-worker.js"), "utf8");
const ORIGIN = "https://me-nd-you.example";

function load({ online = true, cached = {} } = {}) {
  const stores = new Map(); // cache name -> Map(url -> body)
  const puts = [];
  const handlers = {};
  const network = [];
  const cacheFor = (name) => {
    if (!stores.has(name)) stores.set(name, new Map());
    const store = stores.get(name);
    return {
      match: async (request) => (store.has(urlOf(request)) ? fakeResponse(store.get(urlOf(request))) : undefined),
      put: async (request, response) => { puts.push(urlOf(request)); store.set(urlOf(request), response.body); },
      addAll: async (urls) => urls.forEach((u) => { puts.push(new URL(u, ORIGIN).href); store.set(new URL(u, ORIGIN).href, `body of ${u}`); }),
    };
  };
  const urlOf = (request) => new URL(typeof request === "string" ? request : request.url, ORIGIN).href;
  const fakeResponse = (body, ok = true) => ({ ok, status: ok ? 200 : 500, type: "basic", body, clone() { return fakeResponse(body, ok); } });
  const caches = {
    open: async (name) => cacheFor(name),
    keys: async () => [...stores.keys()],
    delete: async (name) => stores.delete(name),
    match: async (request) => {
      for (const name of stores.keys()) {
        const found = await cacheFor(name).match(request);
        if (found) return found;
      }
      return undefined;
    },
  };
  const sandbox = {
    URL,
    console: { log() {}, warn() {}, error() {} },
    caches,
    fetch: async (request) => {
      network.push(urlOf(request));
      if (!online) throw new TypeError("offline");
      return fakeResponse(`fresh ${urlOf(request)}`);
    },
    self: {
      location: { origin: ORIGIN },
      addEventListener: (type, handler) => (handlers[type] = handler),
      skipWaiting() {},
      clients: {
        claim: async () => {},
        matchAll: async () => windows,
        openWindow: async (url) => opened.push(url),
      },
      registration: { showNotification: async (title, options) => shown.push({ title, options }) },
    },
  };
  // Push notifications shown, windows opened, and app windows already open.
  const shown = [];
  const opened = [];
  const windows = [];
  vm.runInNewContext(SOURCE, sandbox);
  for (const [name, entries] of Object.entries(cached)) {
    const store = (stores.has(name) ? stores : stores.set(name, new Map())).get(name);
    for (const [u, body] of Object.entries(entries)) store.set(new URL(u, ORIGIN).href, body);
  }
  const cacheName = vm.runInNewContext("CACHE_NAME", sandbox);
  async function request(url, { method = "GET", mode = "cors" } = {}) {
    let responded = null;
    const event = {
      request: { url: new URL(url, ORIGIN).href, method, mode },
      respondWith: (promise) => (responded = promise),
    };
    handlers.fetch(event);
    return responded === null ? "not handled" : (await responded).body;
  }
  return { handlers, stores, puts, network, cacheName, request, sandbox, shown, opened, windows };
}

async function dispatch(handler, event) {
  let done;
  handler({ ...event, waitUntil: (p) => (done = p) });
  await done;
}

test("a push shows the notification it carries", async () => {
  const sw = load();
  const data = { title: "Me & You", body: "Your partner sent you a message.", url: "/space/?chat=1", tag: "chat_message" };
  await dispatch(sw.handlers.push, { data: { json: () => data } });
  assert.equal(sw.shown.length, 1);
  assert.equal(sw.shown[0].title, "Me & You");
  assert.equal(sw.shown[0].options.body, "Your partner sent you a message.");
  assert.equal(sw.shown[0].options.tag, "chat_message");
  assert.equal(sw.shown[0].options.data.url, "/space/?chat=1");
});

test("a push without readable data still shows a plain notification", async () => {
  const sw = load();
  await dispatch(sw.handlers.push, { data: { json: () => { throw new SyntaxError("bad"); } } });
  await dispatch(sw.handlers.push, {});
  assert.equal(sw.shown.length, 2);
  assert.ok(sw.shown.every((n) => n.title === "Me & You" && n.options.data.url === "/space/"));
});

test("tapping a notification opens its page in the app, only ever on this site", async () => {
  const sw = load();
  const close = () => {};
  await dispatch(sw.handlers.notificationclick, { notification: { close, data: { url: "/play/?mode=spicy" } } });
  await dispatch(sw.handlers.notificationclick, { notification: { close, data: { url: "https://evil.example/" } } });
  await dispatch(sw.handlers.notificationclick, { notification: { close, data: { url: "//evil.example/" } } });
  assert.deepEqual(sw.opened, ["/play/?mode=spicy", "/space/", "/space/"]);
});

test("tapping a notification reuses an open app window", async () => {
  const sw = load();
  const visited = [];
  sw.windows.push({ url: `${ORIGIN}/modes/`, focus: async () => {}, navigate: async (u) => visited.push(u) });
  await dispatch(sw.handlers.notificationclick, { notification: { close() {}, data: { url: "/space/?chat=1" } } });
  assert.deepEqual(visited, ["/space/?chat=1"]);
  assert.deepEqual(sw.opened, []);
});

test("installing caches the offline page and the public static files", async () => {
  const sw = load();
  let done;
  sw.handlers.install({ waitUntil: (p) => (done = p) });
  await done;
  assert.ok(sw.puts.includes(`${ORIGIN}/offline/`));
  assert.ok(sw.puts.includes(`${ORIGIN}/static/fonts/outfit-latin.woff2`));
  for (const url of sw.puts) {
    const { pathname } = new URL(url);
    assert.ok(pathname === "/offline/" || pathname.startsWith("/static/"), `precached ${pathname}`);
  }
});

test("pages always come from the network and are never stored", async () => {
  const sw = load();
  for (const page of ["/", "/space/", "/play/?mode=questions", "/modes/", "/accounts/profile/", "/accounts/consent/"]) {
    assert.equal(await sw.request(page, { mode: "navigate" }), `fresh ${ORIGIN}${page}`);
  }
  assert.deepEqual(sw.puts, []);
});

test("offline, a page shows the offline page, never a stored copy of a personal page", async () => {
  const sw = load({ online: false, cached: { offline: { "/offline/": "OFFLINE PAGE" } } });
  // Even if an old worker had stored a personal page, it is not served.
  const name = sw.cacheName;
  sw.stores.set(name, new Map([[`${ORIGIN}/offline/`, "OFFLINE PAGE"], [`${ORIGIN}/space/`, "Ann's space"]]));
  assert.equal(await sw.request("/space/", { mode: "navigate" }), "OFFLINE PAGE");
});

test("API, sockets, account actions, the admin and other methods are left alone", async () => {
  const sw = load();
  for (const url of ["/api/space/custom-questions/", "/ws/chat/", "/accounts/login/", "/accounts/profile/download/",
    "/admin/", "/privacy/", "https://elsewhere.example/x.js"]) {
    assert.equal(await sw.request(url), "not handled", url);
  }
  assert.equal(await sw.request("/static/js/card.js", { method: "POST" }), "not handled");
  assert.deepEqual(sw.puts, []);
});

test("static files: cached copy first, else the network, which is then cached", async () => {
  const sw = load();
  assert.equal(await sw.request("/static/js/card.js"), `fresh ${ORIGIN}/static/js/card.js`);
  assert.deepEqual(sw.puts, [`${ORIGIN}/static/js/card.js`]);
  sw.network.length = 0;
  assert.equal(await sw.request("/static/js/card.js"), `fresh ${ORIGIN}/static/js/card.js`);
  assert.deepEqual(sw.network, []); // Served from the cache.
});

test("activating drops every older cache", async () => {
  const sw = load({ cached: { "couple-game-cache-v2": { "/space/": "old personal page" } } });
  let done;
  sw.handlers.activate({ waitUntil: (p) => (done = p) });
  await done;
  assert.deepEqual([...sw.stores.keys()].filter((n) => n !== sw.cacheName), []);
});
