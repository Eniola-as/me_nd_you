const test = require("node:test");
const assert = require("node:assert/strict");
const { EMOJI_GROUPS, emojiIn } = require("../../static/js/emoji-picker.js");

test("each group lists its emoji one by one, multi-character emoji kept whole", () => {
  const people = EMOJI_GROUPS.find((g) => g.name === "Smileys");
  assert.ok(people);
  const list = emojiIn(people);
  assert.ok(list.length >= 16);
  assert.ok(list.every((e) => e.length > 0 && !e.includes(" ")));
});

test("the hearts group keeps the red heart with its variation selector", () => {
  const hearts = EMOJI_GROUPS.find((g) => g.name === "Hearts");
  assert.ok(emojiIn(hearts).includes("❤️"));
});
