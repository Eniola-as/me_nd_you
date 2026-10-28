const test = require("node:test");
const assert = require("node:assert/strict");
const { createChatClient } = require("../../static/js/chat-client.js");

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
  drop() {
    this.readyState = 3;
    this.onclose?.({ code: 1006 });
  }
  receive(message) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}

function setup() {
  FakeSocket.instances = [];
  const timers = [];
  let n = 0;
  let changes = 0;
  const chat = createChatClient({
    url: "ws://test/ws/chat/",
    onChange: () => changes++,
    WebSocketImpl: FakeSocket,
    schedule: (fn) => timers.push(fn),
    newRequestId: () => `req-${++n}`,
  });
  chat.connect();
  const socket = () => FakeSocket.instances.at(-1);
  socket().open();
  const runTimers = () => timers.splice(0).forEach((fn) => fn());
  return { chat, socket, runTimers, changes: () => changes };
}

const msg = (id, text, mine = false, extra = {}) => ({ id, text, mine, unreadable: false, sentAt: "2026-10-28T10:00:00Z", ...extra });
const initial = (messages, extra = {}) => ({
  type: "history", initial: true, messages, has_more: false, lastRead: null, unread: 0, partner: "Ben", ...extra,
});
const texts = (chat) => chat.state.items.map((i) => i.text);

test("the history sent on connect is shown with the server's unread count", () => {
  const { chat, socket, changes } = setup();
  socket().receive(initial([msg(1, "Hi"), msg(2, "Hey", true)], { unread: 1, has_more: true }));
  assert.deepEqual(texts(chat), ["Hi", "Hey"]);
  assert.equal(chat.state.unread, 1);
  assert.equal(chat.state.hasMore, true);
  assert.equal(chat.state.partner, "Ben");
  assert.ok(changes() > 0);
});

test("a partner's message while the panel is closed adds to the badge", () => {
  const { chat, socket } = setup();
  socket().receive(initial([]));
  socket().receive({ type: "message", message: msg(5, "New") });
  socket().receive({ type: "message", message: msg(6, "Newer") });
  assert.equal(chat.state.unread, 2);
  assert.deepEqual(texts(chat), ["New", "Newer"]);
});

test("your own messages never add to the badge", () => {
  const { chat, socket } = setup();
  socket().receive(initial([]));
  socket().receive({ type: "message", message: msg(5, "Mine", true) });
  assert.equal(chat.state.unread, 0);
});

test("opening the panel marks everything read up to the newest message", () => {
  const { chat, socket } = setup();
  socket().receive(initial([msg(3, "Old"), msg(4, "Unread")], { unread: 1, lastRead: 3 }));
  chat.setOpen(true);
  assert.equal(chat.state.unread, 0);
  assert.deepEqual(socket().sent.at(-1), { type: "read", upTo: 4 });
});

test("while the panel is open, new messages are read straight away", () => {
  const { chat, socket } = setup();
  socket().receive(initial([]));
  chat.setOpen(true);
  socket().receive({ type: "message", message: msg(7, "Seen") });
  assert.equal(chat.state.unread, 0);
  assert.deepEqual(socket().sent.at(-1), { type: "read", upTo: 7 });
});

test("reading on another device clears the badge here", () => {
  const { chat, socket } = setup();
  socket().receive(initial([msg(1, "A"), msg(2, "B")], { unread: 2 }));
  socket().receive({ type: "read", upTo: 2 });
  assert.equal(chat.state.unread, 0);
});

test("sending shows the message at once and the server's copy replaces it", () => {
  const { chat, socket } = setup();
  socket().receive(initial([]));
  chat.send("  Hello  ");
  assert.deepEqual(socket().sent.at(-1), { type: "send", text: "Hello", requestId: "req-1" });
  assert.deepEqual(chat.state.items.map((i) => [i.text, i.pending]), [["Hello", true]]);
  socket().receive({ type: "message", message: msg(9, "Hello", true, { requestId: "req-1" }) });
  assert.deepEqual(chat.state.items.map((i) => [i.id, i.text, i.pending]), [[9, "Hello", false]]);
});

test("empty messages are not sent", () => {
  const { chat, socket } = setup();
  socket().receive(initial([]));
  chat.send("   ");
  assert.equal(socket().sent.length, 0);
});

test("a refused message is marked as not sent, with the reason", () => {
  const { chat, socket } = setup();
  socket().receive(initial([]));
  chat.send("Too fast");
  socket().receive({ type: "error", reason: "rate_limited", requestId: "req-1", detail: "That's 30 messages in a minute." });
  assert.equal(chat.state.items[0].failed, true);
  assert.equal(chat.state.error, "That's 30 messages in a minute.");
});

test("deleting asks the server; the message goes when the server says so", () => {
  const { chat, socket } = setup();
  socket().receive(initial([msg(1, "Oops", true), msg(2, "Reply")]));
  chat.remove(1);
  assert.deepEqual(socket().sent.at(-1), { type: "delete", id: 1 });
  assert.deepEqual(texts(chat), ["Oops", "Reply"]);
  socket().receive({ type: "deleted", id: 1 });
  assert.deepEqual(texts(chat), ["Reply"]);
});

test("a deleted unread message comes off the badge", () => {
  const { chat, socket } = setup();
  socket().receive(initial([]));
  socket().receive({ type: "message", message: msg(5, "Oops") });
  socket().receive({ type: "deleted", id: 5 });
  assert.equal(chat.state.unread, 0);
});

test("older messages load in front, without duplicates", () => {
  const { chat, socket } = setup();
  socket().receive(initial([msg(51, "m51"), msg(52, "m52")], { has_more: true }));
  chat.loadOlder();
  assert.deepEqual(socket().sent.at(-1), { type: "history", before: 51 });
  socket().receive({ type: "history", messages: [msg(50, "m50"), msg(51, "m51")], has_more: false });
  assert.deepEqual(texts(chat), ["m50", "m51", "m52"]);
  assert.equal(chat.state.hasMore, false);
});

test("after a reconnect, messages deleted meanwhile disappear and older pages stay", () => {
  const { chat, socket, runTimers } = setup();
  socket().receive(initial([msg(51, "m51"), msg(52, "m52"), msg(53, "gone")], { has_more: true }));
  socket().receive({ type: "history", messages: [msg(50, "m50")], has_more: true });
  socket().drop();
  runTimers();
  socket().open();
  socket().receive(initial([msg(51, "m51"), msg(52, "m52"), msg(54, "new")], { has_more: true, unread: 1 }));
  assert.deepEqual(texts(chat), ["m50", "m51", "m52", "new"]);
  assert.equal(chat.state.unread, 1);
});

test("losing access closes the chat", () => {
  const { chat, socket } = setup();
  socket().receive(initial([msg(1, "Hi")]));
  socket().receive({ type: "error", reason: "forbidden", detail: "You no longer have access to this chat." });
  assert.equal(chat.state.closed, true);
});

test("the partner's presence is kept as the server sends it", () => {
  const { chat, socket } = setup();
  socket().receive(initial([]));
  socket().receive({ type: "presence", partner: { online: true, where: "play:truth", lastSeen: null } });
  assert.deepEqual(chat.state.presence, { online: true, where: "play:truth", lastSeen: null });
});

test("the page says where it is when it connects and when told", () => {
  FakeSocket.instances = [];
  const chat = createChatClient({ url: "ws://t/", where: "space", WebSocketImpl: FakeSocket, schedule: () => {} });
  chat.connect();
  FakeSocket.instances[0].open();
  assert.deepEqual(FakeSocket.instances[0].sent[0], { type: "presence", where: "space" });
});

test("typing is sent at most every 3 seconds", () => {
  let now = 0;
  FakeSocket.instances = [];
  const chat = createChatClient({ url: "ws://t/", WebSocketImpl: FakeSocket, schedule: () => {}, now: () => now });
  chat.connect();
  FakeSocket.instances[0].open();
  chat.typing();
  now = 1000;
  chat.typing();
  now = 3500;
  chat.typing();
  assert.equal(FakeSocket.instances[0].sent.filter((m) => m.type === "typing").length, 2);
});

test("the partner shows as typing for 5 seconds, or until their message arrives", () => {
  let now = 0;
  FakeSocket.instances = [];
  const chat = createChatClient({ url: "ws://t/", WebSocketImpl: FakeSocket, schedule: () => {}, now: () => now });
  chat.connect();
  const socket = FakeSocket.instances[0];
  socket.open();
  socket.receive(initial([]));
  socket.receive({ type: "typing" });
  assert.equal(chat.state.partnerTyping, true);
  now = 5100;
  assert.equal(chat.state.partnerTyping, false);
  socket.receive({ type: "typing" });
  socket.receive({ type: "message", message: msg(1, "Done") });
  assert.equal(chat.state.partnerTyping, false);
});

test("disconnect() closes the chat socket, for pages being left", () => {
  const { chat, socket } = setup();
  let closed = false;
  socket().close = () => { closed = true; };
  socket().receive(initial([]));
  chat.disconnect();
  assert.equal(closed, true);
  assert.equal(chat.state.connected, false);
});
