// Turning push notifications on or off for this device (space page,
// notifications/_panel.html). Permission is asked only when the person taps
// "Turn on", never on page load, and a "blocked" answer is respected. Signing
// out turns them off for this device first, so a shared device stops
// getting someone else's alerts.
(function () {
  const box = document.getElementById("push-settings");
  const status = document.getElementById("push-status");
  const onButton = document.getElementById("push-on");
  const offButton = document.getElementById("push-off");

  function csrfToken() {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify(body),
    });
  }

  // The VAPID public key arrives base64url-encoded; subscribe wants bytes.
  function keyBytes(base64url) {
    const padded = (base64url + "=".repeat((4 - (base64url.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
    return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
  }

  const supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const installed = window.navigator.standalone === true ||
    (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches);

  async function currentSubscription() {
    const registration = await navigator.serviceWorker.ready;
    return registration.pushManager.getSubscription();
  }

  function show(text, { on = false, off = false } = {}) {
    if (!box) return;
    box.hidden = false;
    status.textContent = text;
    onButton.hidden = !on;
    offButton.hidden = !off;
  }

  async function refresh() {
    if (!box) return;
    if (!supported) {
      show(isIos && !installed
        ? "To get notifications on iPhone or iPad, add Me & You to your home screen first, then open it from there."
        : "This browser can't show notifications from Me & You.");
      return;
    }
    const { key } = await (await fetch("/api/push/key/", { credentials: "same-origin" })).json();
    if (!key) return; // Push isn't set up on the server: nothing to offer.
    if (Notification.permission === "denied") {
      show("Notifications are blocked for this site. You can allow them in your browser's settings.");
      return;
    }
    const subscription = await currentSubscription();
    if (subscription) {
      show("Notifications are on for this device, even when the app is closed.", { off: true });
    } else {
      show("Get a notification when your partner messages you or plays, even when the app is closed.", { on: true });
    }
  }

  async function turnOn() {
    onButton.disabled = true;
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") return refresh();
      const { key } = await (await fetch("/api/push/key/", { credentials: "same-origin" })).json();
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: keyBytes(key),
      });
      const response = await post("/api/push/subscribe/", subscription.toJSON());
      if (!response.ok) {
        await subscription.unsubscribe();
        show("Couldn't turn notifications on. Please try again.", { on: true });
        return;
      }
      await refresh();
    } catch (err) {
      show("Couldn't turn notifications on. Please try again.", { on: true });
    } finally {
      onButton.disabled = false;
    }
  }

  async function turnOff() {
    offButton.disabled = true;
    try {
      const subscription = await currentSubscription();
      if (subscription) {
        await post("/api/push/unsubscribe/", { endpoint: subscription.endpoint });
        await subscription.unsubscribe();
      }
    } finally {
      offButton.disabled = false;
      await refresh();
    }
  }

  if (onButton) onButton.addEventListener("click", turnOn);
  if (offButton) offButton.addEventListener("click", turnOff);

  // Signing out: stop this device's alerts first (giving up after 2 s).
  document.querySelectorAll('form[action="/accounts/logout/"]').forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!supported || form.dataset.pushCleared) return;
      event.preventDefault();
      const done = () => {
        form.dataset.pushCleared = "1";
        form.submit();
      };
      Promise.race([
        currentSubscription().then((s) => s && post("/api/push/unsubscribe/", { endpoint: s.endpoint })
          .then(() => s.unsubscribe())),
        new Promise((resolve) => setTimeout(resolve, 2000)),
      ]).catch(() => {}).finally(done);
    });
  });

  refresh().catch(() => {});
})();
