function setTheme(theme) {
  document.body.className = theme;
  localStorage.setItem('game-theme', theme);
}

function loadTheme() {
  const savedTheme = localStorage.getItem('game-theme');
  if (savedTheme) {
    document.body.className = savedTheme;
  }
}

loadTheme();