const test = require("node:test");
const assert = require("node:assert/strict");
const { createSocketClient } = require("../../static/js/socket-client.js");

class FakeSocket {
  static instances = [];
  constructor(url) {
    this.url = url;
    this.readyState = 0; // CONNECTING
    this.sent = [];
    FakeSocket.instances.push(this);
  }
  send(data) {
    if (this.failSends) throw new Error("send failed");
    this.sent.push(data);
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  fail() {
    this.readyState = 3;
    this.onerror?.(new Error("boom"));
    this.onclose?.({ code: 1006 });
  }
  receive(data) {
    this.onmessage?.({ data });
  }
}

function setup(options = {}) {
  FakeSocket.instances = [];
  const timers = [];
  const received = [];
  const client = createSocketClient({
    url: "ws://test/ws/game/room/mode/",
    WebSocketImpl: FakeSocket,
    onMessage: (data) => received.push(data),
    schedule: (fn, ms) => timers.push({ fn, ms }),
    ...options,
  });
  const runTimers = () => timers.splice(0).forEach((t) => t.fn());
  return { client, timers, runTimers, received, sockets: FakeSocket.instances };
}

test("reconnects after the first connection attempt fails", () => {
  const { client, timers, runTimers, sockets } = setup();
  client.connect();
  sockets[0].fail();
  assert.equal(timers.length, 1);
  runTimers();
  assert.equal(sockets.length, 2);
});

test("backs off exponentially and stops after maxAttempts", () => {
  const { client, timers, runTimers, sockets } = setup({ maxAttempts: 3 });
  client.connect();
  const delays = [];
  for (let i = 0; i < 5; i++) {
    sockets.at(-1).fail();
    delays.push(...timers.map((t) => t.ms));
    runTimers();
  }
  assert.deepEqual(delays, [1000, 2000, 4000]);
  assert.equal(sockets.length, 4);
});

test("queues messages while offline and flushes them in order on open", () => {
  const { client, sockets } = setup();
  client.connect();
  client.send({ n: 1 });
  client.send({ n: 2 });
  sockets[0].open();
  assert.deepEqual(sockets[0].sent, ['{"n":1}', '{"n":2}']);
  assert.equal(client.queueLength, 0);
});

test("keeps the offline queue bounded", () => {
  const { client } = setup({ maxQueue: 3 });
  client.connect();
  for (let n = 0; n < 10; n++) client.send({ n });
  assert.equal(client.queueLength, 3);
});

test("keeps a message queued when sending it throws", () => {
  const { client, sockets } = setup();
  client.connect();
  client.send({ n: 1 });
  sockets[0].failSends = true;
  assert.doesNotThrow(() => sockets[0].open());
  assert.equal(client.queueLength, 1);
});

test("passes parsed messages to onMessage and ignores invalid JSON", () => {
  const { client, sockets, received } = setup();
  client.connect();
  sockets[0].open();
  sockets[0].receive("not json");
  sockets[0].receive('{"type":"reset"}');
  assert.deepEqual(received, [{ type: "reset" }]);
});

test("onOpen runs on the first connection and on every reconnection", () => {
  let opens = 0;
  const { client, runTimers, sockets } = setup({ onOpen: () => opens++ });
  client.connect();
  sockets[0].open();
  assert.equal(opens, 1);
  sockets[0].fail();
  runTimers();
  sockets[1].open();
  assert.equal(opens, 2);
});

test("a message sent from onOpen goes out after the queued ones", () => {
  let client;
  ({ client } = setup({ onOpen: () => client.send({ type: "sync_request" }) }));
  const sockets = FakeSocket.instances;
  client.connect();
  client.send({ type: "question" });
  sockets[0].open();
  assert.deepEqual(sockets[0].sent, ['{"type":"question"}', '{"type":"sync_request"}']);
});

test("isOpen reports whether messages go out immediately", () => {
  const { client, sockets } = setup();
  assert.equal(client.isOpen, false);
  client.connect();
  assert.equal(client.isOpen, false); // Still connecting.
  sockets[0].open();
  assert.equal(client.isOpen, true);
  sockets[0].fail();
  assert.equal(client.isOpen, false);
});

test("a send while offline after giving up starts a fresh attempt", () => {
  const { client, runTimers, sockets } = setup({ maxAttempts: 1 });
  client.connect();
  sockets[0].fail();
  runTimers();
  sockets[1].fail();
  assert.equal(sockets.length, 2);
  client.send({ n: 1 });
  assert.equal(sockets.length, 3);
});

test("close() closes the socket and doesn't reconnect; connect() starts again", () => {
  const { client, sockets, runTimers, timers } = setup();
  client.connect();
  sockets[0].close = function () {
    this.readyState = 3;
    this.onclose?.({ code: 1000 });
  };
  sockets[0].open();
  client.close();
  assert.equal(sockets[0].readyState, 3);
  runTimers();
  assert.equal(sockets.length, 1);
  assert.equal(timers.length, 0);
  client.connect();
  assert.equal(sockets.length, 2);
});

test("close() during a pending reconnect cancels it", () => {
  const { client, sockets, runTimers } = setup();
  client.connect();
  sockets[0].fail(); // A reconnect is now scheduled.
  client.close();
  runTimers();
  assert.equal(sockets.length, 1);
});

test("onGiveUp runs once it stops retrying", () => {
  let gaveUp = 0;
  const { client, sockets, runTimers } = setup({ maxAttempts: 2, onGiveUp: () => gaveUp++ });
  client.connect();
  sockets.at(-1).fail();
  runTimers();
  sockets.at(-1).fail();
  runTimers();
  assert.equal(gaveUp, 0);
  sockets.at(-1).fail(); // Third failure: no attempts left.
  assert.equal(gaveUp, 1);
});
