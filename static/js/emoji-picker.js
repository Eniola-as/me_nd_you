// The emoji the reaction picker's "+" offers, in groups like the iPhone's
// emoji keyboard. Every one is checked against the server's list
// (chat/tests/test_emoji_picker.py), so any tap works. People can still
// type any other emoji from their keyboard.
(function (root) {
  const EMOJI_GROUPS = [
    {"name": "Smileys", "icon": "😀", "emoji": "😀 😃 😄 😁 😆 😅 🤣 😂 🙂 🙃 🫠 😉 😊 😇 🥰 😍 🤩 😘 😗 😚 😋 😛 😜 🤪 😝 🤗 🤭 🫣 🤫 🤔 🫡 😐 😏 😒 🙄 😬 😌 😔 😴 🥹 🥺 😢 😭 😤 😠 😳 😱 😮 🤯 🥵 🥶 😎 🤓 😈 💀 🤡"},
    {"name": "Hearts", "icon": "❤️", "emoji": "❤️ 🩷 🧡 💛 💚 💙 🩵 💜 🤎 🖤 🩶 🤍 ❤️‍🔥 ❤️‍🩹 💕 💞 💓 💗 💖 💘 💝 💟 ❣️ 💔 💋 💌 😻 💑 💏"},
    {"name": "Gestures", "icon": "👍", "emoji": "👍 👎 👏 🙌 🫶 🙏 🤝 👌 🤌 🤞 ✌️ 🤟 🤘 👋 🤙 💪 👀 🫦 🤷 🤦 🙈 🙉 🙊 💁 🙋 💃 🕺 👯 🫂 ☝️"},
    {"name": "Celebrate", "icon": "🎉", "emoji": "🎉 🥳 🎊 🎈 🎁 🏆 🥇 ⭐ 🌟 ✨ 💫 🔥 💯 🎯 🎲 🎮 🃏 🎵 🎶 📸 💡 💎 👑 🌈 ☀️ 🌙 ⚡ 💥"},
    {"name": "Food", "icon": "🍓", "emoji": "🍓 🍒 🍑 🍆 🍌 🍉 🍕 🍔 🍟 🌮 🍿 🍩 🍪 🎂 🧁 🍫 🍦 ☕ 🍵 🍷 🥂 🍾 🍸 🍹 🍺 🧃"},
    {"name": "Nature", "icon": "🌹", "emoji": "🌹 🌷 🌸 🌺 🌻 💐 🍀 🌿 🌴 🌵 🌊 ❄️ 🐶 🐱 🐰 🦊 🐻 🐼 🐨 🦋 🐝 🦄 🐢 🐙"},
    {"name": "Symbols", "icon": "✅", "emoji": "✅ ❌ ❓ ❗ ‼️ 💤 💢 💦 💨 🆗 🆒 🔞 ♾️ ☮️ 🫧 💬 💭 🔔 🎀 🪄 🧿 🌀"}
  ];

  function emojiIn(group) {
    return group.emoji.split(" ");
  }

  if (typeof module === "object" && module.exports) {
    module.exports = { EMOJI_GROUPS, emojiIn };
  } else {
    root.meYouEmoji = { EMOJI_GROUPS, emojiIn };
  }
})(typeof self !== "undefined" ? self : this);
