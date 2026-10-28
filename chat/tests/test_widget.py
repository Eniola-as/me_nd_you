"""The chat widget: a floating icon with an unread badge that opens a chat
panel, on the play page, the space page and the mode menu only."""

import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from . import PASSWORD, make_couple

PAGES = ["/space/", "/modes/", "/play/?mode=questions", "/play/?mode=truth", "/play/?mode=spicy"]


class WidgetTests(TestCase):
    def setUp(self):
        self.couple, (self.ann, self.ben) = make_couple("ann@example.com", "ben@example.com")
        self.client = Client()
        self.client.force_login(self.ann)

    def test_it_is_on_the_play_page_space_page_and_mode_menu(self):
        for page in PAGES:
            with self.subTest(page):
                html = self.client.get(page).content.decode()
                self.assertEqual(html.count('id="chat-fab"'), 1)
                self.assertIn('id="chat-badge"', html)
                self.assertIn('id="chat-panel"', html)
                self.assertIn("js/chat-client.js", html)
                self.assertEqual(html.count("js/socket-client.js"), 1)

    def test_it_is_not_on_account_pages(self):
        for page in ["/accounts/profile/"]:
            self.assertNotIn('id="chat-fab"', self.client.get(page).content.decode())
        anonymous = Client()
        for page in ["/", "/accounts/login/", "/accounts/register/"]:
            self.assertNotIn('id="chat-fab"', anonymous.get(page).content.decode())

    def test_people_without_a_couple_get_no_chat_on_their_space_page(self):
        loner = get_user_model().objects.create_user(email="dee@example.com", password=PASSWORD)
        client = Client()
        client.force_login(loner)
        self.assertNotIn('id="chat-fab"', client.get("/space/").content.decode())

    def test_the_panel_starts_hidden_and_the_icon_says_what_it_does(self):
        html = self.client.get("/modes/").content.decode()
        self.assertRegex(html, r'<button[^>]*id="chat-fab"[^>]*aria-expanded="false"')
        self.assertRegex(html, r'<section[^>]*id="chat-panel"[^>]*hidden')
        self.assertIn('id="chat-close"', html)

    def test_the_message_box_stops_at_1000_characters(self):
        html = self.client.get("/space/").content.decode()
        self.assertRegex(html, r'<textarea[^>]*id="chat-input"[^>]*maxlength="1000"')

    def test_pages_leave_room_so_the_icon_never_covers_buttons(self):
        html = self.client.get("/play/?mode=truth").content.decode()
        self.assertIn("padding-bottom: calc(96px + env(safe-area-inset-bottom, 0px))", html)
        # On phones the page scrolls above a strip kept for the icon.
        self.assertIn("height: calc(100% - 88px - env(safe-area-inset-bottom, 0px));", html)

    def test_the_plus_box_keeps_what_you_typed_across_redraws(self):
        html = self.client.get("/modes/").content.decode()
        self.assertIn("function reactionPicker(current, onPick, draft = {})", html)
        self.assertIn("input.value = draft.value", html)

    def test_on_phones_the_panel_is_a_full_width_sheet(self):
        html = self.client.get("/play/?mode=questions").content.decode()
        self.assertIn("@media (max-width: 600px)", html)

    def test_messages_are_rendered_as_text_never_html(self):
        html = self.client.get("/modes/").content.decode()
        widget = html[html.index('id="chat-panel"'):]
        self.assertIn("textContent", widget)
        self.assertNotIn("innerHTML", widget)

    def test_on_the_space_page_it_sits_outside_the_card(self):
        # The card's backdrop-filter would make the "fixed" icon move with
        # the card (on top of Sign out) instead of staying in the corner.
        html = self.client.get("/space/").content.decode()
        self.assertLess(html.index("</main>"), html.index('id="chat-fab"'))

    def test_deleting_asks_inside_the_panel_not_with_a_browser_dialog(self):
        html = self.client.get("/modes/").content.decode()
        widget = html[html.index('id="chat-panel"'):]
        self.assertIn("Delete for both?", widget)
        self.assertNotIn("confirm(", widget)

    def test_each_page_says_where_you_are_for_presence(self):
        expected = {"/space/": 'data-chat-where="space"', "/modes/": 'data-chat-where="menu"',
                    "/play/?mode=truth": 'data-chat-where="play"'}
        for page, attribute in expected.items():
            with self.subTest(page):
                self.assertIn(attribute, self.client.get(page).content.decode())

    def test_it_shows_presence_and_typing(self):
        html = self.client.get("/modes/").content.decode()
        for element in ['id="chat-presence"', 'id="chat-typing"', 'id="chat-dot"']:
            self.assertIn(element, html)
        for words in ["In your space", "Playing ", "Last seen", "is typing"]:
            self.assertIn(words, html)

    def test_leaving_a_page_closes_its_chat_connection(self):
        # Otherwise a page kept in the back/forward cache keeps you "online".
        html = self.client.get("/modes/").content.decode()
        self.assertIn('addEventListener("pagehide", () => chat.disconnect())', html)
        self.assertIn('addEventListener("pageshow"', html)

    def test_messages_have_the_quick_reaction_row_and_a_plus_for_any_emoji(self):
        from chat.reaction_emoji import QUICK_REACTIONS

        html = self.client.get("/modes/").content.decode()
        self.assertIn("const QUICK_REACTIONS = " + json.dumps(QUICK_REACTIONS, ensure_ascii=False), html)
        self.assertIn('setAttribute("maxlength", "32")', html)
        self.assertIn("chat.react(", html)

    def test_revealed_answers_can_be_reacted_to_on_the_play_page(self):
        html = self.client.get("/play/?mode=questions").content.decode()
        for element in ['id="reveal-mine-reactions"', 'id="reveal-partner-reactions"']:
            self.assertIn(element, html)
        self.assertIn('room.act("react"', html)
