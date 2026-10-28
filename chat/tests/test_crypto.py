"""Chat message text is encrypted at rest (Fernet, keys from
CHAT_ENCRYPTION_KEYS); a missing or wrong key never crashes the chat."""

import os
import subprocess
import sys
from io import StringIO

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings

from chat import crypto, services
from chat.models import ChatMessage
from game.tests.test_settings import PRODUCTION_ENV
from game.tests.utils import SETTINGS_ENV_KEYS, load_settings

from . import TEST_KEY, make_couple, with_chat_key

TEXTS = ["Hi there", "Je t'aime ❤️ 👩🏽‍❤️‍👨🏻", "x" * 1000, "Line one\nLine two"]


@with_chat_key
class EncryptionTests(TestCase):
    def setUp(self):
        self.couple, (self.ann, self.ben) = make_couple("ann@example.com", "ben@example.com")

    def stored(self, message):
        with connection.cursor() as cursor:
            cursor.execute("SELECT body FROM chat_chatmessage WHERE id = %s", [message.pk])
            return cursor.fetchone()[0]

    def test_the_database_never_holds_the_plain_text(self):
        for text in TEXTS:
            with self.subTest(text[:12]):
                raw = self.stored(services.send(self.ann, self.couple.pk, text, None))
                self.assertNotIn(text, raw)
                self.assertNotIn(text[:6], raw)
                self.assertTrue(raw.startswith("gAAAA"))  # A Fernet token.

    def test_it_decrypts_back_exactly(self):
        for text in TEXTS:
            with self.subTest(text[:12]):
                message = services.send(self.ann, self.couple.pk, text, None)
                self.assertEqual(services.serialize(message, self.ben)["text"], text)

    def test_the_same_text_encrypts_differently_each_time(self):
        a = self.stored(services.send(self.ann, self.couple.pk, "Same", None))
        b = self.stored(services.send(self.ann, self.couple.pk, "Same", None))
        self.assertNotEqual(a, b)

    def test_a_wrong_key_shows_the_placeholder_instead_of_failing(self):
        message = services.send(self.ann, self.couple.pk, "Secret", None)
        with override_settings(CHAT_ENCRYPTION_KEYS=[Fernet.generate_key().decode()]):
            shown = services.serialize(ChatMessage.objects.get(pk=message.pk), self.ben)
        self.assertEqual(shown["text"], crypto.UNREADABLE)
        self.assertTrue(shown["unreadable"])

    def test_a_tampered_value_shows_the_placeholder(self):
        message = services.send(self.ann, self.couple.pk, "Secret", None)
        ChatMessage.objects.filter(pk=message.pk).update(body=message.body[:-4] + "AAAA")
        shown = services.serialize(ChatMessage.objects.get(pk=message.pk), self.ben)
        self.assertEqual(shown["text"], crypto.UNREADABLE)

    def test_without_a_key_sending_is_refused_cleanly(self):
        with override_settings(CHAT_ENCRYPTION_KEYS=[]), self.assertRaises(crypto.ChatKeyMissing):
            services.send(self.ann, self.couple.pk, "Hi", None)
        self.assertFalse(ChatMessage.objects.exists())


@with_chat_key
class RotationTests(TestCase):
    def test_rotation_re_encrypts_everything_with_the_new_key(self):
        couple, (ann, ben) = make_couple("ann@example.com", "ben@example.com")
        for text in TEXTS:
            services.send(ann, couple.pk, text, None)
        new_key = Fernet.generate_key().decode()
        out = StringIO()
        with override_settings(CHAT_ENCRYPTION_KEYS=[new_key, TEST_KEY]):
            call_command("rotate_chat_keys", stdout=out)
        self.assertIn("Re-encrypted 4 messages", out.getvalue())
        with override_settings(CHAT_ENCRYPTION_KEYS=[new_key]):  # The old key is gone.
            texts = [services.serialize(m, ben)["text"] for m in ChatMessage.objects.order_by("id")]
        self.assertEqual(texts, TEXTS)
        with override_settings(CHAT_ENCRYPTION_KEYS=[TEST_KEY]):  # The old key alone can't read them.
            self.assertTrue(all(services.serialize(m, ben)["unreadable"] for m in ChatMessage.objects.all()))

    def test_rotation_reports_unreadable_messages_and_leaves_them(self):
        couple, (ann, _) = make_couple("ann@example.com", "ben@example.com")
        services.send(ann, couple.pk, "Readable", None)
        lost = services.send(ann, couple.pk, "Lost", None)
        ChatMessage.objects.filter(pk=lost.pk).update(body="gAAAAAbroken")
        out = StringIO()
        call_command("rotate_chat_keys", stdout=out)
        self.assertIn("Re-encrypted 1 messages; 1 could not be decrypted and were left as they are", out.getvalue())
        self.assertEqual(ChatMessage.objects.get(pk=lost.pk).body, "gAAAAAbroken")


class KeySettingsTests(SimpleTestCase):
    def start(self, **env):
        child = {k: v for k, v in os.environ.items() if k not in SETTINGS_ENV_KEYS}
        # Empty unless a test sets it: a developer's .env must not leak in.
        child.update({"SECRET_KEY": "test-key", "CHAT_ENCRYPTION_KEYS": "", **env})
        return subprocess.run([sys.executable, "-c", "import me_nd_you.settings"],
                              cwd=settings.BASE_DIR, env=child, capture_output=True, text=True)

    def test_production_refuses_to_start_without_a_key(self):
        result = self.start(DEBUG="False")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CHAT_ENCRYPTION_KEYS", result.stderr)

    def test_a_malformed_key_stops_startup_without_printing_it(self):
        result = self.start(DEBUG="True", CHAT_ENCRYPTION_KEYS="not-a-real-key-value")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CHAT_ENCRYPTION_KEYS", result.stderr)
        self.assertNotIn("not-a-real-key-value", result.stderr)

    def test_keys_come_from_the_environment_first_one_encrypts(self):
        keys = [Fernet.generate_key().decode() for _ in range(2)]
        values = load_settings({"CHAT_ENCRYPTION_KEYS": f" {keys[0]} , {keys[1]} "}, ["CHAT_ENCRYPTION_KEYS"])
        self.assertEqual(values["CHAT_ENCRYPTION_KEYS"], keys)

    def test_the_key_is_not_derived_from_secret_key(self):
        values = load_settings({"CHAT_ENCRYPTION_KEYS": ""} | {"DEBUG": "True"}, ["CHAT_ENCRYPTION_KEYS"])
        self.assertEqual(values["CHAT_ENCRYPTION_KEYS"], [])

    def test_local_development_warns_while_no_key_is_set(self):
        result = subprocess.run([sys.executable, "manage.py", "check"], cwd=settings.BASE_DIR, capture_output=True,
                                text=True, env={**{k: v for k, v in os.environ.items() if k not in SETTINGS_ENV_KEYS},
                                                "SECRET_KEY": "test-key", "DEBUG": "True",
                                                "CHAT_ENCRYPTION_KEYS": ""})
        self.assertIn("chat.W001", result.stdout + result.stderr)

    def test_the_render_blueprint_takes_the_keys_from_the_dashboard(self):
        render_yaml = (settings.BASE_DIR / "render.yaml").read_text()
        self.assertRegex(render_yaml, r"key: CHAT_ENCRYPTION_KEYS\s+sync: false")

    def test_production_settings_in_the_deploy_tests_have_a_key(self):
        self.assertIn("CHAT_ENCRYPTION_KEYS", PRODUCTION_ENV)

    def test_env_example_explains_how_to_make_a_local_key(self):
        example = (settings.BASE_DIR / ".env.example").read_text(encoding="utf-8")
        self.assertIn("CHAT_ENCRYPTION_KEYS=", example)
        self.assertIn("Fernet.generate_key()", example)
