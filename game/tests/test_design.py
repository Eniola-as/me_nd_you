"""Small fixes that keep the existing look: password fields can be shown
while typing, the play page's text boxes match the app's dark fields, and the
home-screen install steps use Apple's Share icon (not an emoji) and hide
once the app is installed."""

import re

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from couples import services

INSTALL_PAGES = ["/", "/accounts/login/", "/accounts/register/"]


class DesignFixTests(TestCase):
    def setUp(self):
        member = get_user_model().objects.create_user(email="ann@example.com", password="pw-for-tests-1")
        services.create_couple(member)
        self.member = Client()
        self.member.force_login(member)

    def test_password_fields_can_be_shown_while_typing(self):
        pages = [(Client(), "/accounts/login/"), (Client(), "/accounts/register/"),
                 (self.member, "/accounts/profile/")]
        for client, url in pages:
            with self.subTest(url=url):
                html = client.get(url).content.decode()
                self.assertIn('type="password"', html)
                self.assertIn("js/password-toggle.js", html)
                self.assertIn(".password-field .password-toggle", html)

    def test_install_steps_use_the_share_icon_not_an_emoji(self):
        for url in INSTALL_PAGES:
            with self.subTest(url=url):
                html = Client().get(url).content.decode()
                guide = html[html.index('<aside class="install-guide"'):]
                guide = guide[:guide.index("</aside>")]
                self.assertRegex(guide, r"In Safari, tap the Share\s+<span[^>]*>button <svg")
                self.assertIn("Add to Home Screen", guide)
                self.assertRegex(guide, r'<svg[^>]*class="share-icon"[^>]*aria-hidden="true"')
                for emoji in ["&#x1F5D2;", "🗒", "&#x1F4E6;", "📦"]:
                    self.assertNotIn(emoji, html)

    def test_install_steps_hide_once_the_app_is_installed(self):
        for url in INSTALL_PAGES:
            with self.subTest(url=url):
                html = Client().get(url).content.decode()
                self.assertIn("js/install-guide.js", html)
                self.assertRegex(html, r"@media \(display-mode: standalone\)\s*\{\s*\.install-guide\s*\{\s*display: none")

    def test_play_page_text_boxes_are_dark_like_the_rest_of_the_app(self):
        html = self.member.get("/play/?mode=questions").content.decode()
        rule = re.search(r"#answer-text,\s*#add-modal textarea,\s*#new-category\s*\{([^}]*)\}", html)
        self.assertIsNotNone(rule)
        self.assertIn("background: #1e1e1e", rule.group(1))
        self.assertIn("color: #fff", rule.group(1))

    def test_the_plus_opens_a_grid_of_emoji_to_tap(self):
        html = self.member.get("/modes/").content.decode()
        self.assertIn("js/emoji-picker.js", html)
        self.assertIn("EMOJI.emojiIn(group)", html)
        # "Add" stays off until something is typed in the box.
        self.assertIn("ok.disabled = !input.value.trim()", html)


class PlayPageFixTests(TestCase):
    def setUp(self):
        member = get_user_model().objects.create_user(email="ann@example.com", password="pw-for-tests-1")
        services.create_couple(member)
        client = Client()
        client.force_login(member)
        self.html = client.get("/play/?mode=questions").content.decode()

    def test_buttons_use_the_app_font(self):
        rule = re.search(r"\n      button \{([^}]*)\}", self.html)
        self.assertIn("font-family: inherit", rule.group(1))

    def test_adding_a_question_cannot_be_sent_twice_and_clears_the_box(self):
        self.assertIn("if (addingQuestion) return;", self.html)
        self.assertIn('document.getElementById("new-question").value = "";', self.html)

    def test_the_card_flips_at_its_original_speed_for_everyone(self):
        # The owner's card: 0.6s flip, with no reduced-motion shortcut.
        self.assertIn("transition: transform 0.6s ease;", self.html)
        self.assertNotIn("prefers-reduced-motion", self.html)


class ChatTapTargetTests(TestCase):
    def test_react_and_delete_are_at_least_24px_tall(self):
        member = get_user_model().objects.create_user(email="ann@example.com", password="pw-for-tests-1")
        services.create_couple(member)
        client = Client()
        client.force_login(member)
        html = client.get("/modes/").content.decode()
        rule = re.search(r"#chat-messages \.meta button \{([^}]*)\}", html)
        self.assertIn("min-height: 24px", rule.group(1))


class MobileTests(TestCase):
    """Most people play on phones."""

    def setUp(self):
        member = get_user_model().objects.create_user(email="ann@example.com", password="pw-for-tests-1")
        services.create_couple(member)
        self.member = Client()
        self.member.force_login(member)

    def test_account_fields_are_16px_so_iphones_do_not_zoom_in(self):
        html = Client().get("/accounts/login/").content.decode()
        rule = re.search(r"\n      input \{([^}]*)\}", html)
        self.assertIn("font-size: 16px", rule.group(1))

    def test_hover_colours_only_apply_with_a_mouse(self):
        # On touch screens :hover sticks after a tap, so a tapped button would
        # stay pink (and look picked).
        for url in ["/play/?mode=questions", "/modes/"]:
            with self.subTest(url=url):
                html = self.member.get(url).content.decode()
                self.assertIn("@media (hover: hover)", html)
                self.assertNotRegex(html, r"\n      (button|\.mode-card):hover")

    def test_buttons_you_cannot_use_yet_look_it(self):
        html = self.member.get("/play/?mode=questions").content.decode()
        self.assertRegex(html, r"button:disabled \{[^}]*opacity: 0\.45")

    def test_small_controls_have_44px_tap_areas(self):
        login = Client().get("/accounts/login/").content.decode()
        self.assertRegex(login, r"\.password-field \.password-toggle \{[^}]*width: 44px;[^}]*height: 44px")
        self.assertRegex(login, r"\n      summary \{[^}]*padding: 12px 0")
        self.assertRegex(login, r"\.banner \.link-button \{[^}]*min-height: 44px")
        chat = self.member.get("/modes/").content.decode()
        self.assertRegex(chat, r"#chat-panel #chat-close \{[^}]*min-width: 44px;[^}]*min-height: 44px")

    def test_the_chat_sheet_stays_above_the_phone_keyboard(self):
        html = self.member.get("/modes/").content.decode()
        self.assertIn('window.visualViewport.addEventListener("resize", liftAboveKeyboard)', html)

    def test_the_card_keeps_its_original_look_on_hover(self):
        # The general button hover must not reach the flip card.
        html = self.member.get("/play/?mode=questions").content.decode()
        self.assertIn("button:not(:disabled):not(.flip-container):hover", html)


class OnboardingTests(TestCase):
    def setUp(self):
        member = get_user_model().objects.create_user(email="ann@example.com", password="pw-for-tests-1")
        services.create_couple(member)
        self.member = Client()
        self.member.force_login(member)
        self.html = self.member.get("/space/").content.decode()

    def test_the_space_page_has_a_short_skippable_tour(self):
        self.assertRegex(self.html, r'<dialog[^>]*id="tour"[^>]*aria-labelledby=')
        self.assertIn('id="tour-skip"', self.html)
        self.assertLessEqual(self.html.count('class="tour-step"'), 5)

    def test_it_shows_once_per_device_and_can_be_replayed(self):
        self.assertIn('TOUR_SEEN = "meYouTourSeen-v1"', self.html)
        self.assertIn('id="tour-replay"', self.html)

    def test_it_covers_invites_private_answers_receipts_notifications_and_switching(self):
        text = self.html.replace("&#x27;", "'")
        for words in ["invitation link", "revealed together", "Seen", "never what anyone wrote",
                      "closes your current space"]:
            self.assertIn(words, text)

    def test_visitors_get_no_tour(self):
        self.assertNotIn('id="tour"', Client().get("/").content.decode())
