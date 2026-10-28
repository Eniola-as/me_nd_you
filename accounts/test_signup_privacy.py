"""Sign-up with an email that already has an account (option B): a generic
message on the page, an alert email to the real owner (at most one per
account per day), and at most 5 sign-up attempts per minute per client."""

import re
import threading
import time
from email.utils import parseaddr
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.utils.html import escape

PASSWORD = "a-long-passphrase-1"
# The 18+ and consent checkboxes every sign-up must tick (accounts/test_consents.py).
TICKED = {box: "on" for box in ["confirm_age", "agree_terms", "agree_sensitive", "agree_transfer"]}
GENERIC = escape("We couldn't create an account with these details. "
                 "If you already have one, sign in or reset your password.")  # As shown in the page.
ALERT_SUBJECT = "Someone tried to sign up with your email"


def wait_for_emails():
    for thread in threading.enumerate():
        if thread.name == "account-email":
            thread.join(timeout=10)


class TakenEmailTests(TestCase):
    def setUp(self):
        cache.clear()
        self.User = get_user_model()
        self.owner = self.User.objects.create_user(email="ann@example.com", password=PASSWORD, display_name="Ann")

    def register(self, email="ann@example.com"):
        response = self.client.post("/accounts/register/", {
            "display_name": "Eve", "email": email, "password1": PASSWORD, "password2": PASSWORD, **TICKED,
        })
        wait_for_emails()
        return response

    def alerts(self):
        return [m for m in mail.outbox if m.subject == ALERT_SUBJECT]

    def test_the_page_shows_a_generic_message_and_creates_nothing(self):
        response = self.register("ANN@example.com")
        self.assertContains(response, GENERIC)
        self.assertNotContains(response, "already exists")
        self.assertEqual(self.User.objects.count(), 1)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_the_owner_gets_the_approved_alert(self):
        self.register()
        alert, = self.alerts()
        self.assertEqual(alert.to, ["ann@example.com"])
        self.assertEqual(parseaddr(alert.from_email), ("Me & You", "no-reply@localhost"))
        self.assertIn("Hi Ann, someone just tried to create a Me & You account with this email. "
                      "You already have one, so nothing was created.", alert.body)
        self.assertIn("If it was you, sign in, or reset your password if you've forgotten it: "
                      "http://testserver/accounts/password/reset/", alert.body)
        self.assertIn("If it wasn't you, you can ignore this email; your account is unchanged.", alert.body)

    def test_the_html_version_is_a_minimal_reset_button(self):
        self.register()
        (html, mimetype), = self.alerts()[0].alternatives
        self.assertEqual(mimetype, "text/html")
        self.assertRegex(html, r'<a href="http://testserver/accounts/password/reset/" style="[^"]+">Reset my password</a>')
        self.assertNotIn("<img", html)
        self.assertNotIn("<style", html)
        self.assertEqual(set(re.findall(r"https?://[^\s\"'<]+", html)), {"http://testserver/accounts/password/reset/"})

    def test_the_alert_names_nothing_about_the_person_trying(self):
        self.register()
        self.assertNotIn("Eve", self.alerts()[0].body)

    def test_at_most_one_alert_per_account_per_day(self):
        self.register()
        cache_time = time.time()
        with mock.patch("time.time", return_value=cache_time + 23 * 3600):
            self.register()
        self.assertEqual(len(self.alerts()), 1)
        with mock.patch("time.time", return_value=cache_time + 24 * 3600 + 60):
            self.register()
        self.assertEqual(len(self.alerts()), 2)

    def test_the_daily_limit_is_per_account(self):
        self.User.objects.create_user(email="ben@example.com", password=PASSWORD)
        self.register("ann@example.com")
        self.register("ben@example.com")
        self.assertEqual(sorted(m.to[0] for m in self.alerts()), ["ann@example.com", "ben@example.com"])

    def test_deactivated_accounts_get_no_alert(self):
        self.User.objects.filter(pk=self.owner.pk).update(is_active=False)
        self.assertContains(self.register(), GENERIC)
        self.assertEqual(self.alerts(), [])

    def test_a_sending_failure_still_shows_the_same_page(self):
        with mock.patch("accounts.emails.EmailMultiAlternatives.send", side_effect=OSError("down")), \
                self.assertLogs("accounts.emails", "ERROR"):
            self.assertContains(self.register(), GENERIC)

    def test_new_emails_still_sign_up_normally(self):
        response = self.register("new@example.com")
        self.assertRedirects(response, "/space/", fetch_redirect_response=False)
        self.assertEqual(self.alerts(), [])

    def test_sign_up_is_limited_to_5_attempts_per_minute_per_client(self):
        statuses = [self.register(f"x{n}@example.com" if n else "ann@example.com").status_code for n in range(6)]
        self.assertNotIn(429, statuses[:5])
        self.assertEqual(statuses[-1], 429)
