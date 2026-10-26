from urllib.parse import parse_qs, urlparse

from django.test import TestCase

from .test_login import login


class SecretEncodingTests(TestCase):
    def test_login_redirect_encodes_special_characters(self):
        response = login(self.client, secret="us#1&x=y")
        query = parse_qs(urlparse(response.json()["redirect"]).query)
        self.assertEqual(query["secret"], ["us#1&x=y"])

    def test_mode_page_encodes_secret_in_play_link(self):
        html = self.client.get("/modes/").content.decode()
        self.assertIn("secret=${encodeURIComponent(secret)}", html)

    def test_play_page_encodes_secret_in_api_calls(self):
        html = self.client.get("/play/").content.decode()
        self.assertNotIn("?secret=${secret}", html)
        self.assertIn("?secret=${encodeURIComponent(secret)}", html)


class LoginFormTests(TestCase):
    def test_login_form_pattern_accepts_unicode_names(self):
        html = self.client.get("/").content.decode()
        self.assertNotIn('pattern="[A-Za-z ]+"', html)
