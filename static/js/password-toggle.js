// Every password field gets a Show / Hide button, so people can check what
// they typed. The field goes back to hidden when its form is submitted, so
// the browser never stores it as plain text. Styled in accounts/base.html.
(function () {
  const EYE = '<path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z" /><circle cx="12" cy="12" r="3" />';
  const EYE_SLASH = '<path d="M9.9 5.7c.7-.1 1.4-.2 2.1-.2 6.4 0 10 6.5 10 6.5s-1 1.8-2.9 3.5M6.6 7.1C3.6 8.9 2 12 2 12s3.6 6.5 10 6.5c1.8 0 3.4-.5 4.7-1.2" /><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2M3.5 3.5l17 17" />';

  function icon(paths) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    // Fixed markup from this file, never from the page or the user.
    svg.innerHTML = paths;
    return svg;
  }

  function enhance(input) {
    if (input.closest(".password-field")) return;
    const wrapper = document.createElement("div");
    wrapper.className = "password-field";
    input.replaceWith(wrapper);
    wrapper.append(input);

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "password-toggle";
    if (input.id) toggle.setAttribute("aria-controls", input.id);

    function show(visible) {
      input.type = visible ? "text" : "password";
      toggle.setAttribute("aria-pressed", String(visible));
      toggle.setAttribute("aria-label", visible ? "Hide password" : "Show password");
      toggle.replaceChildren(icon(visible ? EYE_SLASH : EYE));
    }

    toggle.addEventListener("click", () => {
      const start = input.selectionStart;
      const end = input.selectionEnd;
      show(input.type === "password");
      input.focus();
      try {
        input.setSelectionRange(start, end);
      } catch (e) {
        // Some browsers don't allow a selection on every input type.
      }
    });
    if (input.form) input.form.addEventListener("submit", () => show(false));
    show(false);
    wrapper.append(toggle);
  }

  function enhanceAll() {
    document.querySelectorAll('input[type="password"]').forEach(enhance);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", enhanceAll);
  else enhanceAll();
})();
