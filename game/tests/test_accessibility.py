import re

from django.test import TestCase

PAGES = ["/", "/modes/", "/play/"]


class AccessibilityTests(TestCase):
    def html(self, url):
        return self.client.get(url).content.decode()

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

    def test_pages_have_a_status_region(self):
        for url in ["/", "/play/"]:
            with self.subTest(url=url):
                self.assertIn('role="status"', self.html(url))

    def test_mode_choices_are_buttons(self):
        html = self.html("/modes/")
        self.assertEqual(len(re.findall(r'<button[^>]*class="mode-card"', html)), 6)

    def test_flip_card_is_a_button(self):
        self.assertRegex(self.html("/play/"), r'<button[^>]*id="flip-container"')

    def test_modals_are_labelled_dialogs(self):
        html = self.html("/play/")
        for dialog_id in ["add-modal", "guide-modal"]:
            with self.subTest(dialog=dialog_id):
                self.assertRegex(html, rf'<dialog[^>]*id="{dialog_id}"[^>]*aria-labelledby=')

    def test_icon_only_buttons_have_names(self):
        self.assertRegex(self.html("/play/"), r'<button[^>]*aria-label="Close"[^>]*>\s*✖')
