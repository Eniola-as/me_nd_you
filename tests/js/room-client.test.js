const test = require("node:test");
const assert = require("node:assert/strict");
const { createRoomClient } = require("../../static/js/room-client.js");

class FakeSocket {
  static instances = [];
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    FakeSocket.instances.push(this);
  }
  send(data) {
    this.sent.push(JSON.parse(data));
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  fail() {
    this.readyState = 3;
    this.onclose?.({ code: 1006 });
  }
  receive(message) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}

function setup() {
  FakeSocket.instances = [];
  const states = [];
  const errors = [];
  const timers = [];
  let n = 0;
  const room = createRoomClient({
    url: "ws://test/ws/room/questions/questions/",
    onState: (state) => states.push(state),
    onError: (error) => errors.push(error),
    WebSocketImpl: FakeSocket,
    schedule: (fn) => timers.push(fn),
    newRequestId: () => `req-${++n}`,
  });
  room.connect();
  const socket = () => FakeSocket.instances.at(-1);
  socket().open();
  const runTimers = () => timers.splice(0).forEach((fn) => fn());
  return { room, states, errors, socket, runTimers };
}

const state = (version, text = `Card ${version}`) => ({
  type: "state", version, state: { current: { key: `q:${version}`, text }, remaining: 10 - version },
});

test("renders the snapshot the server sends on connect", () => {
  const { room, states, socket } = setup();
  socket().receive(state(3));
  assert.equal(states.length, 1);
  assert.equal(room.version, 3);
});

test("actions carry the version they are based on and a fresh request id", () => {
  const { room, socket } = setup();
  socket().receive(state(3));
  room.act("next");
  room.act("reset");
  assert.deepEqual(socket().sent, [
    { type: "action", action: "next", expectedVersion: 3, requestId: "req-1" },
    { type: "action", action: "reset", expectedVersion: 3, requestId: "req-2" },
  ]);
});

test("payloads are sent with the action", () => {
  const { room, socket } = setup();
  socket().receive(state(1));
  room.act("answer", { text: "Mine" });
  assert.deepEqual(socket().sent[0].payload, { text: "Mine" });
});

test("never renders an older or repeated version", () => {
  const { states, socket } = setup();
  socket().receive(state(5));
  socket().receive(state(4));
  socket().receive(state(5));
  assert.deepEqual(states.map((s) => s.version), [5]);
});

test("a stale rejection is reported and the following state is rendered", () => {
  const { states, errors, socket } = setup();
  socket().receive(state(1));
  socket().receive({ type: "error", reason: "stale", requestId: "req-1" });
  socket().receive(state(2));
  assert.deepEqual(errors.map((e) => e.reason), ["stale"]);
  assert.deepEqual(states.map((s) => s.version), [1, 2]);
});

test("after a reconnect, the server's snapshot is rendered if it moved on", () => {
  const { states, socket, runTimers } = setup();
  socket().receive(state(2));
  socket().fail();
  runTimers();
  socket().open();
  socket().receive(state(4)); // The partner played on while we were away.
  assert.deepEqual(states.map((s) => s.version), [2, 4]);
});

test("ignores anything that isn't a state or an error", () => {
  const { states, errors, socket } = setup();
  socket().receive({ type: "question", question: "Relayed?" });
  socket().receive({ type: "state", version: "7" });
  assert.equal(states.length + errors.length, 0);
});

test("act returns the request id it sent, so a page can match replies", () => {
  const { room, socket } = setup();
  socket().receive(state(1));
  const id = room.act("answer", { text: "Mine" });
  assert.equal(id, "req-1");
  assert.equal(socket().sent[0].requestId, id);
});
