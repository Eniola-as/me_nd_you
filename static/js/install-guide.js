// The home-screen install steps (accounts/_install_guide.html). Hidden once
// the app runs from the home screen: CSS covers browsers that report
// display-mode, navigator.standalone covers iOS Safari. Where the browser
// offers its own install prompt, the "Install App" button shows it.
(function () {
  const guide = document.querySelector(".install-guide");
  if (!guide) return;

  function installed() {
    return window.navigator.standalone === true ||
      (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches);
  }

  if (installed()) {
    guide.classList.add("is-installed");
    return;
  }

  const installButton = document.getElementById("installBtn");
  let deferredPrompt = null;

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt = event;
    if (installButton) installButton.classList.add("show");
  });

  if (installButton) {
    installButton.addEventListener("click", async () => {
      if (!deferredPrompt) return;
      deferredPrompt.prompt();
      await deferredPrompt.userChoice;
      deferredPrompt = null;
      installButton.classList.remove("show");
    });
  }

  window.addEventListener("appinstalled", () => guide.classList.add("is-installed"));
})();
