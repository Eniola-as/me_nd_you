"""Reactions are exactly one emoji, checked against Unicode's emoji list
(the `emoji` library, pinned in requirements.txt). That covers emoji made of
several code points (skin tones, flags, keycaps, ZWJ sequences) and refuses
anything else. Emoji newer than the library are refused until it's updated.
"""

import emoji

# The quick row; "+" lets people pick any other emoji from their keyboard.
QUICK_REACTIONS = ["❤️", "😂", "😮", "😢", "🙏", "👍", "🔥"]
MAX_LENGTH = 32  # Code points; the longest real emoji are well under this.


def is_single_emoji(value):
    if not isinstance(value, str) or not value or len(value) > MAX_LENGTH:
        return False
    data = emoji.EMOJI_DATA.get(value)
    # A lone skin tone or hair style is a "component", not something to send.
    return data is not None and data["status"] != emoji.STATUS["component"]
