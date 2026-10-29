// What the add-a-prompt form shows and sends (owner, 2026-10-29). The
// server checks the same rules (game.views.add_space_custom_question).
//   Truth or Dare: a Truth/Dare choice; the kind is sent.
//   Other single modes: no choice; the prompt goes to the current mode.
//   Mixed Mode: a category selector of the real categories (never "Mixed");
//   Truth or Dare there also shows the Truth/Dare choice.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.promptForm = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  const CATEGORIES = [
    { value: "questions", label: "Questions" },
    { value: "truth", label: "Truth or Dare" },
    { value: "challenge", label: "Challenge" },
    { value: "spicy", label: "Spicy Only" },
    { value: "would", label: "Would You Rather" },
  ];
  const REAL = new Set(CATEGORIES.map((c) => c.value));

  function categoryFor(pageMode, category) {
    return pageMode === "mixed" ? category : pageMode;
  }

  function promptControls(pageMode, category) {
    return { showCategory: pageMode === "mixed", showKind: categoryFor(pageMode, category) === "truth" };
  }

  function promptPayload({ pageMode, category, kind, text }) {
    const mode = categoryFor(pageMode, category);
    const trimmed = (text || "").trim();
    if (!REAL.has(mode) || !trimmed) return null;
    return mode === "truth" ? { text: trimmed, mode, kind } : { text: trimmed, mode };
  }

  return { CATEGORIES, promptControls, promptPayload };
});
