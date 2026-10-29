// The shared game mode on member pages (static/js/mode-banner.js), run in a
// sandbox with a fake page. When a switch is agreed, both partners go
// straight to the new game, from whatever member page they're on.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = fs.readFileSync(path.join(__dirname, "../../static/js/mode-banner.js"), "utf8");

function element() {
  return { textContent: "", dataset: {}, replaceChildren() {}, addEventListener() {}, querySelector: () => element() };
}

function load({ page = "space", state = { mode: "questions", version: 3, pending: null }, server = {} } = {}) {
  const listeners = {};
  const visited = [];
  const banner = { ...element(), dataset: { partner: "Ben" }, addEventListener: (t, fn) => (listeners[`banner:${t}`] = fn) };
  const sandbox = {
    document: {
      body: { dataset: page === "play" ? { playMode: state.mode } : {} },
      cookie: "csrftoken=t",
      getElementById: (id) => (id === "mode-banner" ? banner : id === "mode-state" ? { textContent: JSON.stringify(state) } : null),
      createElement: () => element(),
    },
    window: {
      addEventListener: (t, fn) => (listeners[t] = fn),
      location: { assign: (url) => visited.push(url), set href(url) { visited.push(url); } },
    },
    fetch: async (url, options = {}) => {
      const reply = server[options.method || "GET"] || { ok: true, status: 200, body: state };
      return { ok: reply.ok, status: reply.status, json: async () => reply.body };
    },
    JSON,
    encodeURIComponent,
  };
  sandbox.window.document = sandbox.document;
  vm.runInNewContext(SOURCE, sandbox);
  const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
  return { sandbox, listeners, visited, settle };
}

const switched = { mode: "truth", version: 4, pending: null };

test("when the partner accepts your switch, you go straight to the new game from the space page", async () => {
  const { listeners, visited, settle } = load({ page: "space", server: { GET: { ok: true, status: 200, body: switched } } });
  listeners["couple-mode"]({ detail: { event: "switched", mode: "truth", by_you: false } });
  await settle();
  assert.deepEqual(visited, ["/play/?mode=truth"]);
});

test("...and from the game menu", async () => {
  const { listeners, visited, settle } = load({ page: "menu", server: { GET: { ok: true, status: 200, body: switched } } });
  listeners["couple-mode"]({ detail: { event: "switched", mode: "truth", by_you: false } });
  await settle();
  assert.deepEqual(visited, ["/play/?mode=truth"]);
});

test("accepting a switch takes you to the new game too", async () => {
  const pending = { mode: "questions", version: 3, pending: { mode: "truth", by_you: false } };
  const { listeners, visited, settle } = load({ page: "menu", state: pending, server: { POST: { ok: true, status: 200, body: switched } } });
  listeners["banner:click"]({ target: { dataset: { modeAction: "accept" } } });
  await settle();
  await settle();
  assert.deepEqual(visited, ["/play/?mode=truth"]);
});

test("declining, a cancelled request or a new request moves nobody", async () => {
  for (const event of ["declined", "cancelled", "requested"]) {
    const { listeners, visited, settle } = load({ page: "space" });
    listeners["couple-mode"]({ detail: { event, mode: "truth", by_you: false } });
    await settle();
    assert.deepEqual(visited, [], event);
  }
});
