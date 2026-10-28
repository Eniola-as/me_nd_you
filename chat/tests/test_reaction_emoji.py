"""A reaction is exactly one emoji, including multi-character ones (skin
tones, flags, keycaps, ZWJ sequences), and nothing else."""

from django.test import SimpleTestCase

from chat.reaction_emoji import QUICK_REACTIONS, is_single_emoji

ACCEPTED = {
    "red heart": "❤️",
    "heart as some keyboards send it": "❤",
    "tears of joy": "😂",
    "skin tone": "👍🏽",
    "flag": "🇳🇬",
    "ZWJ couple": "👩‍❤️‍👨",
    "ZWJ family": "👩‍👩‍👧",
    "keycap": "#️⃣",
    "tag sequence flag": "🏴\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f",
    "copyright (an emoji in Unicode's list)": "©️",
}
REJECTED = {
    "letter": "a",
    "digit": "1",
    "two emoji": "😂😂",
    "emoji and text": "😂a",
    "text and emoji": "ok👍",
    "made-up ZWJ": "😂‍😂",
    "lone ZWJ": "‍",
    "lone skin tone": "\U0001F3FD",
    "space": " ",
    "padded emoji": " 😂 ",
    "empty": "",
    "too long": "😂" * 40,
    "none": None,
    "number": 5,
    "list": ["😂"],
}


class ReactionEmojiTests(SimpleTestCase):
    def test_single_emoji_are_accepted(self):
        for name, value in ACCEPTED.items():
            with self.subTest(name):
                self.assertTrue(is_single_emoji(value))

    def test_everything_else_is_refused(self):
        for name, value in REJECTED.items():
            with self.subTest(name):
                self.assertFalse(is_single_emoji(value))

    def test_the_quick_row_is_the_approved_set_and_all_valid(self):
        self.assertEqual(QUICK_REACTIONS, ["❤️", "😂", "😮", "😢", "🙏", "👍", "🔥"])
        self.assertTrue(all(is_single_emoji(e) for e in QUICK_REACTIONS))
