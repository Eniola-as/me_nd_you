const test = require("node:test");
const assert = require("node:assert/strict");
const { createCard } = require("../../static/js/card.js");

function fakeElement(text = "") {
  const classes = new Set();
  const attributes = {};
  return {
    textContent: text,
    attributes,
    setAttribute: (name, value) => (attributes[name] = String(value)),
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      contains: (c) => classes.has(c),
      toggle: (c) => (classes.has(c) ? classes.delete(c) : classes.add(c)),
    },
  };
}

function setup() {
  const container = fakeElement();
  // Black face (front) holds the question; pink face (back) shows the mode.
  const front = fakeElement("Loading...");
  const back = fakeElement("Questions");
  const timers = [];
  const card = createCard({
    container,
    front,
    back,
    schedule: (fn) => timers.push(fn),
  });
  const runTimers = () => timers.splice(0).forEach((fn) => fn());
  // The CSS shows the back face while the container has the "flipped" class.
  const visibleText = () =>
    container.classList.contains("flipped") ? back.textContent : front.textContent;
  return { card, container, front, back, runTimers, visibleText };
}

test("a new question lands face-down, showing the pink mode face", () => {
  const { card, runTimers, visibleText } = setup();
  card.showQuestion("What's your favorite memory?");
  runTimers();
  assert.equal(visibleText(), "Questions");
});

test("tapping the card reveals the question on the black face", () => {
  const { card, front, runTimers, visibleText } = setup();
  card.showQuestion("What's your favorite memory?");
  runTimers();
  card.flip();
  assert.equal(visibleText(), "What's your favorite memory?");
  assert.equal(front.textContent, "What's your favorite memory?");
});

test("the next question also lands face-down after a reveal", () => {
  const { card, runTimers, visibleText } = setup();
  card.showQuestion("First");
  runTimers();
  card.flip();
  card.showQuestion("Second");
  runTimers();
  assert.equal(visibleText(), "Questions");
  card.flip();
  assert.equal(visibleText(), "Second");
});

test("two quick questions still land face-down with the latest one", () => {
  const { card, runTimers, visibleText } = setup();
  card.showQuestion("First");
  card.showQuestion("Second");
  runTimers();
  assert.equal(visibleText(), "Questions");
  card.flip();
  assert.equal(visibleText(), "Second");
});

test("a message shows on the black face and cancels a pending question", () => {
  const { card, runTimers, visibleText } = setup();
  card.showQuestion("First");
  runTimers();
  card.showQuestion("Second");
  card.showMessage("All questions finished.");
  runTimers();
  assert.equal(visibleText(), "All questions finished.");
});

test("currentQuestion reports the question even before it is revealed", () => {
  const { card, runTimers } = setup();
  card.showQuestion("First");
  runTimers();
  assert.equal(card.currentQuestion(), "First");
});

test("screen readers only see the face that is showing", () => {
  const { card, front, back, runTimers } = setup();
  card.showQuestion("First");
  runTimers();
  assert.equal(front.attributes["aria-hidden"], "true");
  assert.equal(back.attributes["aria-hidden"], "false");
  card.flip();
  assert.equal(front.attributes["aria-hidden"], "false");
  assert.equal(back.attributes["aria-hidden"], "true");
});

test("the status region says a new card is ready, without spoiling it", () => {
  const status = fakeElement();
  const card = createCard({
    container: fakeElement(),
    front: fakeElement(),
    back: fakeElement("Questions"),
    status,
    schedule: (fn) => fn(),
  });
  card.showQuestion("Secret question");
  assert.doesNotMatch(status.textContent, /Secret question/);
  assert.match(status.textContent, /tap the card/i);
});
