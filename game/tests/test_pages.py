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


class PlayPageSocketTests(TestCase):
    def setUp(self):
        self.html = self.client.get("/play/").content.decode()

    def test_play_page_uses_the_shared_message_contract(self):
        self.assertIn("js/game-messages.js", self.html)
        self.assertIn("GameMessages.question(", self.html)
        self.assertIn("GameMessages.parse(", self.html)
        self.assertNotIn("questions: [", self.html)  # The old untyped shape.

    def test_play_page_handles_reset_and_sync(self):
        for handled in ['case "reset"', 'case "sync_request"', 'case "sync_response"']:
            with self.subTest(handled):
                self.assertIn(handled, self.html)

    def test_play_page_requests_a_sync_on_every_connection(self):
        self.assertRegex(self.html, r"onOpen\(\)\s*\{[^}]*GameMessages\.syncRequest\(")

    def test_loading_does_not_replace_a_question_already_adopted(self):
        # The sync reply can arrive before the question list finishes
        # loading; the local first question must not then overwrite it.
        self.assertIn("else if (showFirst && (announce || !currentQuestionText))", self.html)

    def test_question_announced_while_offline_is_not_overridden_by_sync(self):
        # nextQuestion must note announcements made while disconnected, and
        # the reconnect must not adopt the partner's question in that case.
        self.assertIn("if (!socketClient.isOpen) ownQuestionPending = true;", self.html)
        self.assertRegex(self.html, r"onOpen\(\)\s*\{[^}]*acceptSync = !ownQuestionPending;")
