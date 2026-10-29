"""The "+" emoji picker (static/js/emoji-picker.js) only offers emoji the
server accepts, so tapping any of them works."""

import json
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from chat.reaction_emoji import is_single_emoji

PICKER = Path(settings.BASE_DIR) / "static" / "js" / "emoji-picker.js"


def picker_groups():
    source = PICKER.read_text(encoding="utf-8")
    match = re.search(r"const EMOJI_GROUPS = (\[.*?\]);\n", source, re.S)
    return json.loads(match.group(1))


class EmojiPickerTests(SimpleTestCase):
    def test_every_offered_emoji_is_accepted_by_the_server(self):
        for group in picker_groups():
            for emoji in group["emoji"].split(" "):
                with self.subTest(group=group["name"], emoji=emoji):
                    self.assertTrue(is_single_emoji(emoji))

    def test_groups_have_a_name_an_icon_and_plenty_of_emoji(self):
        groups = picker_groups()
        self.assertGreaterEqual(len(groups), 6)
        for group in groups:
            with self.subTest(group=group["name"]):
                self.assertTrue(group["name"])
                self.assertTrue(is_single_emoji(group["icon"]))
                self.assertGreaterEqual(len(group["emoji"].split(" ")), 16)

    def test_no_emoji_is_offered_twice(self):
        offered = [e for group in picker_groups() for e in group["emoji"].split(" ")]
        self.assertEqual(len(offered), len(set(offered)))
