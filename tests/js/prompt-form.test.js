// What the add-a-prompt form shows and sends in each mode.
const test = require("node:test");
const assert = require("node:assert/strict");
const { CATEGORIES, promptControls, promptPayload } = require("../../static/js/prompt-form.js");

test("the categories are the real ones, never Mixed", () => {
  assert.deepEqual(CATEGORIES.map((c) => c.value), ["questions", "truth", "challenge", "spicy", "would"]);
});

test("Truth or Dare shows the Truth/Dare choice and sends the kind", () => {
  assert.deepEqual(promptControls("truth"), { showCategory: false, showKind: true });
  assert.deepEqual(promptPayload({ pageMode: "truth", kind: "dare", text: "Hug me." }),
    { text: "Hug me.", mode: "truth", kind: "dare" });
});

test("other single modes show nothing extra and send their own mode, without a kind", () => {
  for (const mode of ["questions", "challenge", "spicy", "would"]) {
    assert.deepEqual(promptControls(mode), { showCategory: false, showKind: false }, mode);
    assert.deepEqual(promptPayload({ pageMode: mode, category: "truth", kind: "dare", text: "Hi?" }), { text: "Hi?", mode }, mode);
  }
});

test("Mixed shows the categories, and the Truth/Dare choice only for Truth or Dare", () => {
  assert.deepEqual(promptControls("mixed", "questions"), { showCategory: true, showKind: false });
  assert.deepEqual(promptControls("mixed", "truth"), { showCategory: true, showKind: true });
  assert.deepEqual(promptPayload({ pageMode: "mixed", category: "truth", kind: "truth", text: "Why?" }),
    { text: "Why?", mode: "truth", kind: "truth" });
  assert.deepEqual(promptPayload({ pageMode: "mixed", category: "would", kind: "dare", text: "A or B?" }),
    { text: "A or B?", mode: "would" });
});

test("nothing is sent without a real category or text", () => {
  assert.equal(promptPayload({ pageMode: "mixed", category: "mixed", text: "Hi?" }), null);
  assert.equal(promptPayload({ pageMode: "mixed", category: "", text: "Hi?" }), null);
  assert.equal(promptPayload({ pageMode: "questions", text: "   " }), null);
});
