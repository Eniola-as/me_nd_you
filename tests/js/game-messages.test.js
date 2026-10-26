const test = require("node:test");
const assert = require("node:assert/strict");
const messages = require("../../static/js/game-messages.js");

const ME = "page-me";
const PARTNER = "page-partner";

test("builds each message type in the agreed shape", () => {
  assert.deepEqual(messages.question(ME, "Q?"), { type: "question", userId: ME, question: "Q?" });
  assert.deepEqual(messages.reset(ME, 42), { type: "reset", userId: ME, seed: 42 });
  assert.deepEqual(messages.syncRequest(ME), { type: "sync_request", userId: ME });
  assert.deepEqual(messages.syncResponse(ME, 42, "Q?"), {
    type: "sync_response", userId: ME, seed: 42, currentQuestion: "Q?",
  });
});

test("a sync response without a current question sends null", () => {
  assert.equal(messages.syncResponse(ME, null, "").currentQuestion, null);
  assert.equal(messages.syncResponse(ME, Number.NaN, null).seed, null);
});

test("accepts every valid message type from the partner", () => {
  for (const message of [
    messages.question(PARTNER, "Q?"),
    messages.reset(PARTNER, 7),
    messages.syncRequest(PARTNER),
    messages.syncResponse(PARTNER, 7, "Q?"),
    messages.syncResponse(PARTNER, null, null),
  ]) {
    assert.deepEqual(messages.parse(message, ME), message);
  }
});

test("ignores the page's own messages echoed back by the server", () => {
  assert.equal(messages.parse(messages.question(ME, "Q?"), ME), null);
});

test("drops unexpected fields", () => {
  const parsed = messages.parse({ ...messages.question(PARTNER, "Q?"), html: "<b>" }, ME);
  assert.deepEqual(Object.keys(parsed).sort(), ["question", "type", "userId"]);
});

test("rejects malformed messages", () => {
  const malformed = [
    null,
    "question",
    [1, 2],
    { userId: PARTNER, questions: ["Old shape?"] },
    { type: "dance", userId: PARTNER },
    { type: "question", question: "Q?" },
    { type: "question", userId: "", question: "Q?" },
    { type: "question", userId: "u".repeat(65), question: "Q?" },
    { type: "question", userId: PARTNER, question: 5 },
    { type: "question", userId: PARTNER, question: "" },
    { type: "question", userId: PARTNER, question: "q".repeat(501) },
    { type: "reset", userId: PARTNER, seed: "42" },
    { type: "reset", userId: PARTNER, seed: 1.5 },
    { type: "reset", userId: PARTNER },
    { type: "sync_response", userId: PARTNER, seed: 1, currentQuestion: 7 },
    { type: "error", reason: "invalid_message" },
  ];
  for (const message of malformed) {
    assert.equal(messages.parse(message, ME), null, JSON.stringify(message));
  }
});
