// Flip card for the play page. The black front face holds the question (or a
// status message); the pink back face shows the mode name.
(function (root) {
  function createCard({
    container,
    front,
    back,
    status = null,
    schedule = (fn, ms) => setTimeout(fn, ms),
  }) {
    // Each show call bumps this so an older pending reveal can't override it.
    let latest = 0;

    // Hide the face turned away from the viewer from screen readers too.
    function setFlipped(flipped) {
      if (flipped) container.classList.add("flipped");
      else container.classList.remove("flipped");
      front.setAttribute("aria-hidden", flipped);
      back.setAttribute("aria-hidden", !flipped);
    }

    function flip() {
      setFlipped(!container.classList.contains("flipped"));
    }

    // A new question lands face-down: it is written to the black front face,
    // then the card turns to the pink mode face. Tapping reveals it.
    function showQuestion(text) {
      const token = ++latest;
      setFlipped(false);
      schedule(() => {
        if (token !== latest) return;
        front.textContent = text;
        setFlipped(true);
        if (status) status.textContent = "New question ready. Tap the card to reveal it.";
      }, 300);
    }

    function showMessage(text) {
      latest++;
      setFlipped(false);
      front.textContent = text;
      if (status) status.textContent = text;
    }

    function currentQuestion() {
      return front.textContent;
    }

    return { flip, showQuestion, showMessage, currentQuestion };
  }

  if (typeof module === "object" && module.exports) {
    module.exports = { createCard };
  } else {
    root.createCard = createCard;
  }
})(typeof self !== "undefined" ? self : this);
