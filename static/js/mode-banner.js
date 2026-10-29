// The couple's shared game mode on member pages (game/_mode_banner.html).
// Notices arrive over the chat connection as "couple-mode" events; the
// banner then reloads the state from the server, which is the authority.
// Switching is a request the partner accepts: nothing here changes the
// game being played until the server says the mode has changed.
(function () {
  const LABELS = {
    questions: "Questions", truth: "Truth or Dare", challenge: "Challenge",
    spicy: "Spicy Only", mixed: "Mixed Mode", would: "Would You Rather",
  };
  const banner = document.getElementById("mode-banner");
  const stateScript = document.getElementById("mode-state");
  let state = stateScript ? JSON.parse(stateScript.textContent) : { mode: null, version: 0, pending: null };
  const partner = banner ? banner.dataset.partner : "Your partner";

  function csrf() {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function notice(text) {
    const el = banner && banner.querySelector(".mode-notice");
    if (el) el.textContent = text;
  }

  function button(label, action, secondary) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.dataset.modeAction = action;
    if (secondary) b.className = "secondary";
    return b;
  }

  function render() {
    if (!banner) return;
    banner.querySelector(".mode-now strong").textContent = LABELS[state.mode] || "";
    const pendingText = banner.querySelector(".mode-pending");
    const actions = banner.querySelector(".mode-actions");
    const pending = state.pending;
    if (!pending) {
      pendingText.textContent = "";
      actions.replaceChildren();
    } else if (pending.by_you) {
      pendingText.textContent = `Waiting for ${partner} to accept a switch to ${LABELS[pending.mode]}.`;
      actions.replaceChildren(button("Cancel", "cancel", true));
    } else {
      pendingText.textContent = `${partner} wants to switch to ${LABELS[pending.mode]}.`;
      actions.replaceChildren(button("Switch", "accept"), button("Keep playing", "decline", true));
    }
  }

  // A play page shows one mode; when the couple's mode changes, follow it.
  function follow() {
    const pageMode = document.body.dataset.playMode;
    if (pageMode && state.mode && state.mode !== pageMode) {
      window.location.assign(`/play/?mode=${encodeURIComponent(state.mode)}`);
    }
  }

  function apply(next) {
    state = next;
    render();
    follow();
  }

  async function refresh() {
    const response = await fetch("/api/space/mode/", { credentials: "same-origin" });
    if (response.ok) apply(await response.json());
  }

  async function send(body) {
    const response = await fetch("/api/space/mode/", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (response.ok) {
      apply(data);
    } else if (response.status === 409 && data.state) {
      apply(data.state);
      notice("Something changed in the meantime. Here's the latest.");
    } else {
      notice(data.detail || "That didn't work. Please try again.");
    }
    return response.ok;
  }

  if (banner) {
    banner.addEventListener("click", (event) => {
      const action = event.target.dataset && event.target.dataset.modeAction;
      if (action) send({ action, version: state.version });
    });
  }

  window.addEventListener("couple-mode", (event) => {
    const n = event.detail || {};
    const label = LABELS[n.mode] || "";
    const texts = {
      started: n.by_you ? "" : `${partner} started ${label}.`,
      requested: "",
      switched: `Now playing ${label}.`,
      declined: n.by_you ? "" : `${partner} wants to keep playing for now.`,
      cancelled: n.by_you ? "" : `${partner} cancelled the switch.`,
    };
    notice(texts[n.event] || "");
    refresh();
  });

  // The mode menu: start or open the current mode, or ask to switch.
  window.modeBanner = {
    get state() {
      return state;
    },
    choose(mode) {
      if (!state.mode || state.mode === mode) {
        window.location.href = `/play/?mode=${encodeURIComponent(mode)}`;
      } else if (state.pending) {
        notice("A switch is already waiting for an answer.");
      } else {
        send({ action: "request", mode, version: state.version });
      }
    },
  };
})();
