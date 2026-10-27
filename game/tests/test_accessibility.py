import re

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from couples import services

PAGES = ["/", "/modes/", "/play/?mode=questions"]


class AccessibilityTests(TestCase):
    def setUp(self):
        # The landing page is for visitors; the game pages for couple members.
        member = get_user_model().objects.create_user(email="ann@example.com", password="pw-for-tests-1")
        services.create_couple(member)
        self.member = Client()
        self.member.force_login(member)

    def html(self, url):
        client = Client() if url == "/" else self.member
        response = client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.content.decode()

    def test_pages_allow_zooming(self):
        for url in PAGES:
            with self.subTest(url=url):
                html = self.html(url)
                self.assertNotIn("user-scalable=no", html)
                self.assertNotIn("maximum-scale", html)

    def test_pages_do_not_use_alert_dialogs(self):
        for url in PAGES:
            with self.subTest(url=url):
                self.assertIsNone(re.search(r"\balert\(", self.html(url)))

    def test_every_form_field_has_a_label(self):
        for url in PAGES:
            html = self.html(url)
            for field_id in re.findall(r'<(?:input|textarea)[^>]*\bid="([^"]+)"', html):
                with self.subTest(url=url, field=field_id):
                    self.assertIn(f'for="{field_id}"', html)

    def test_play_page_has_a_status_region(self):
        self.assertIn('role="status"', self.html("/play/?mode=questions"))

    def test_mode_choices_are_buttons(self):
        html = self.html("/modes/")
        self.assertEqual(len(re.findall(r'<button[^>]*class="mode-card"', html)), 6)

    def test_flip_card_is_a_button(self):
        self.assertRegex(self.html("/play/?mode=questions"), r'<button[^>]*id="flip-container"')

    def test_modals_are_labelled_dialogs(self):
        html = self.html("/play/?mode=questions")
        for dialog_id in ["add-modal", "guide-modal"]:
            with self.subTest(dialog=dialog_id):
                self.assertRegex(html, rf'<dialog[^>]*id="{dialog_id}"[^>]*aria-labelledby=')

    def test_icon_only_buttons_have_names(self):
        self.assertRegex(self.html("/play/?mode=questions"), r'<button[^>]*aria-label="Close"[^>]*>\s*✖')
