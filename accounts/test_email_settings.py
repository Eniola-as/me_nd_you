"""Email is sent through django-anymail's HTTPS API backends, chosen by
environment variables. Locally the console backend prints mail instead;
there is no SMTP path (Render's free tier blocks SMTP)."""

import os
import subprocess
import sys
from email.utils import parseaddr
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.mail import EmailMessage
from django.test import SimpleTestCase, override_settings

from game.tests.test_settings import PRODUCTION_ENV
from game.tests.utils import SETTINGS_ENV_KEYS, load_settings

NAMES = ["EMAIL_BACKEND", "ANYMAIL", "DEFAULT_FROM_EMAIL"]


class EmailSettingsTests(SimpleTestCase):
    def test_locally_mail_goes_to_the_console(self):
        values = load_settings({}, NAMES)
        self.assertEqual(values["EMAIL_BACKEND"], "django.core.mail.backends.console.EmailBackend")
        self.assertEqual(values["ANYMAIL"], {})

    def test_each_provider_uses_its_https_api_backend_and_key(self):
        for provider, backend, key_name in [
            ("brevo", "anymail.backends.brevo.EmailBackend", "BREVO_API_KEY"),
            ("resend", "anymail.backends.resend.EmailBackend", "RESEND_API_KEY"),
            ("postmark", "anymail.backends.postmark.EmailBackend", "POSTMARK_SERVER_TOKEN"),
        ]:
            with self.subTest(provider):
                values = load_settings({"EMAIL_PROVIDER": provider, "EMAIL_API_KEY": "fake-key"}, NAMES)
                self.assertEqual(values["EMAIL_BACKEND"], backend)
                self.assertEqual(values["ANYMAIL"], {key_name: "fake-key"})

    def test_the_provider_name_is_case_insensitive(self):
        values = load_settings({"EMAIL_PROVIDER": " Brevo ", "EMAIL_API_KEY": "k"}, NAMES)
        self.assertEqual(values["EMAIL_BACKEND"], "anymail.backends.brevo.EmailBackend")

    def test_an_unknown_provider_stops_startup(self):
        env = {k: v for k, v in os.environ.items() if k not in SETTINGS_ENV_KEYS}
        env.update({"SECRET_KEY": "test-key", "EMAIL_PROVIDER": "smtp"})
        result = subprocess.run([sys.executable, "-c", "import me_nd_you.settings"],
                                cwd=settings.BASE_DIR, env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("EMAIL_PROVIDER", result.stderr)

    def test_the_sender_is_me_and_you_at_the_configured_address(self):
        values = load_settings({"DEFAULT_FROM_EMAIL": "hello@example.com"}, NAMES)
        self.assertEqual(parseaddr(values["DEFAULT_FROM_EMAIL"]), ("Me & You", "hello@example.com"))


class _Sent(Exception):
    pass


class ProviderTransportTests(SimpleTestCase):
    """The production path is an HTTPS API request, never SMTP."""

    def test_providers_send_over_https(self):
        for backend, key_name, host in [
            ("anymail.backends.brevo.EmailBackend", "BREVO_API_KEY", "api.brevo.com"),
            ("anymail.backends.resend.EmailBackend", "RESEND_API_KEY", "api.resend.com"),
            ("anymail.backends.postmark.EmailBackend", "POSTMARK_SERVER_TOKEN", "api.postmarkapp.com"),
        ]:
            with self.subTest(backend), override_settings(EMAIL_BACKEND=backend, ANYMAIL={key_name: "fake"}), \
                    mock.patch("requests.Session.request", side_effect=_Sent) as request, \
                    mock.patch("smtplib.SMTP") as smtp:
                with self.assertRaises(Exception):
                    EmailMessage("Hi", "Body", "a@example.com", ["b@example.com"]).send()
                url = request.call_args.kwargs.get("url") or request.call_args.args[1]
                self.assertTrue(url.startswith(f"https://{host}/"), url)
                smtp.assert_not_called()


class TestRunnerTests(SimpleTestCase):
    def test_tests_capture_mail_in_memory(self):
        EmailMessage("Hi", "Body", None, ["b@example.com"]).send()
        self.assertEqual(len(mail.outbox), 1)


class EmailDeployCheckTests(SimpleTestCase):
    def deploy_check(self, **overrides):
        env = {k: v for k, v in os.environ.items() if k not in SETTINGS_ENV_KEYS}
        env.update(PRODUCTION_ENV)
        env.update(overrides)
        env = {k: v for k, v in env.items() if v is not None}
        result = subprocess.run([sys.executable, "manage.py", "check", "--deploy"],
                                cwd=settings.BASE_DIR, env=env, capture_output=True, text=True)
        return result.stderr + result.stdout

    def test_warns_when_production_would_print_mail_to_the_console(self):
        self.assertIn("accounts.W001", self.deploy_check(EMAIL_PROVIDER=None, EMAIL_API_KEY=None))

    def test_warns_when_the_provider_has_no_api_key(self):
        self.assertIn("accounts.W002", self.deploy_check(EMAIL_API_KEY=None))

    def test_warns_when_the_sender_address_is_not_set(self):
        self.assertIn("accounts.W003", self.deploy_check(DEFAULT_FROM_EMAIL=None))

    def test_a_configured_provider_passes(self):
        output = self.deploy_check()
        for check_id in ["accounts.W001", "accounts.W002", "accounts.W003"]:
            self.assertNotIn(check_id, output)
