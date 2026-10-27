"""Email verification is a reminder only: unverified users can do
everything. Links look like /accounts/verify/#<token>, so the token never
reaches server or proxy logs, and work for 3 days."""

import re
import time
from email.utils import parseaddr
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase

from accounts import emails
from couples.services import create_couple

PASSWORD = "a-long-passphrase-1"
LINK = re.compile(r"http://testserver/accounts/verify/#([\w:.-]+)")


def later(seconds):
    """Patch the clock that signed tokens and the cache read."""
    now = time.time() + seconds
    return mock.patch("time.time", return_value=now)


class VerificationTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.User = get_user_model()

    def make_user(self, email="ann@example.com", **extra):
        return self.User.objects.create_user(email=email, password=PASSWORD, display_name="Ann", **extra)

    def token_from(self, message):
        return LINK.search(message.body).group(1)

    def verify(self, token):
        return self.client.post("/accounts/verify/", {"token": token})


class RegistrationSendsVerificationTests(VerificationTestCase):
    def register(self, email="new@example.com"):
        return self.client.post("/accounts/register/", {
            "display_name": "Ann", "email": email, "password1": PASSWORD, "password2": PASSWORD,
        })

    def test_new_users_start_unverified(self):
        self.assertIsNone(self.make_user().email_verified_at)

    def test_signing_up_sends_one_verification_email(self):
        self.register()
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["new@example.com"])
        self.assertEqual(message.subject, "Confirm your email for Me & You")
        self.assertEqual(parseaddr(message.from_email), ("Me & You", "no-reply@localhost"))

    def test_the_email_uses_the_approved_wording(self):
        self.register()
        body = mail.outbox[0].body
        self.assertIn("Hi Ann,", body)
        self.assertIn("tap the link below to confirm this is your email. It works for 3 days.", body)
        self.assertIn("If you didn't create a Me & You account, you can ignore this email.", body)
        self.assertRegex(body, LINK)

    def test_the_html_version_is_a_minimal_button_with_the_same_link(self):
        self.register()
        message = mail.outbox[0]
        (html, mimetype), = message.alternatives
        self.assertEqual(mimetype, "text/html")
        token = self.token_from(message)
        self.assertRegex(html, rf'<a href="http://testserver/accounts/verify/#{re.escape(token)}" style="[^"]+">')
        self.assertNotIn("<img", html)
        self.assertNotIn("<style", html)  # Inline styles only.
        self.assertNotIn("<link", html)
        # No tracking or other outside addresses: the only URL is the link.
        self.assertEqual(set(re.findall(r"https?://[^\s\"'<]+", html)),
                         {f"http://testserver/accounts/verify/#{token}"})

    def test_users_can_play_straight_away_even_if_sending_fails(self):
        with mock.patch("accounts.emails.EmailMultiAlternatives.send", side_effect=OSError("down")), \
                self.assertLogs("accounts.emails", "ERROR"):
            response = self.register()
        self.assertRedirects(response, "/space/", fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]),
                         self.User.objects.get(email="new@example.com").pk)


class VerifyLinkTests(VerificationTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.token = emails.verification_token(self.user)

    def test_the_link_page_posts_the_token_from_after_the_hash(self):
        response = self.client.get("/accounts/verify/")
        self.assertContains(response, 'action="/accounts/verify/"')
        self.assertContains(response, "location.hash")
        self.assertContains(response, "history.replaceState")

    def test_a_valid_link_verifies_the_email_without_signing_in(self):
        response = self.verify(self.token)
        self.assertContains(response, "Your email is verified")
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.email_verified_at)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_using_it_again_keeps_the_first_time(self):
        self.verify(self.token)
        first = self.User.objects.get().email_verified_at
        self.assertContains(self.verify(self.token), "Your email is verified")
        self.assertEqual(self.User.objects.get().email_verified_at, first)

    def test_links_work_for_3_days(self):
        with later(3 * 24 * 3600 - 60):
            self.assertContains(self.verify(self.token), "Your email is verified")

    def test_older_links_are_refused(self):
        with later(3 * 24 * 3600 + 60):
            response = self.verify(self.token)
        self.assertContains(response, "This link has expired or isn't valid")
        self.assertIsNone(self.User.objects.get().email_verified_at)

    def test_a_link_for_a_previous_address_is_refused(self):
        self.User.objects.filter(pk=self.user.pk).update(email="other@example.com")
        self.assertContains(self.verify(self.token), "This link has expired or isn't valid")
        self.assertIsNone(self.User.objects.get().email_verified_at)

    def test_a_tampered_link_is_refused(self):
        for token in [self.token[:-2] + "xx", "", "nonsense", "x" * 5000]:
            with self.subTest(token=token[:20]):
                self.assertContains(self.verify(token), "This link has expired or isn't valid")
        self.assertIsNone(self.User.objects.get().email_verified_at)

    def test_link_posts_are_rate_limited(self):
        statuses = [self.verify("nonsense").status_code for _ in range(6)]
        self.assertNotIn(429, statuses[:5])
        self.assertEqual(statuses[-1], 429)


class ResendTests(VerificationTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.client.force_login(self.user)

    def resend(self, next_url="/space/"):
        return self.client.post("/accounts/verify/resend/", {"next": next_url})

    def test_signed_out_visitors_cannot_resend(self):
        self.client.logout()
        response = self.resend()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/accounts/login/"))
        self.assertEqual(mail.outbox, [])

    def test_resend_sends_a_fresh_link_and_returns_to_the_page(self):
        response = self.resend("/accounts/profile/")
        self.assertRedirects(response, "/accounts/profile/", fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ann@example.com"])
        self.verify(self.token_from(mail.outbox[0]))
        self.assertIsNotNone(self.User.objects.get().email_verified_at)

    def test_only_safe_local_pages_are_returned_to(self):
        self.assertRedirects(self.resend("https://evil.example/"), "/space/", fetch_redirect_response=False)

    def test_one_email_per_account_every_2_minutes(self):
        self.resend()
        response = self.client.post("/accounts/verify/resend/", {"next": "/space/"}, follow=True)
        self.assertContains(response, "We just sent you a link")
        self.assertEqual(len(mail.outbox), 1)
        with later(121):
            self.resend()
        self.assertEqual(len(mail.outbox), 2)

    def test_the_cooldown_is_per_account(self):
        self.resend()
        self.client.force_login(self.make_user(email="ben@example.com"))
        self.resend()
        self.assertEqual([m.to for m in mail.outbox], [["ann@example.com"], ["ben@example.com"]])

    def test_verified_users_get_no_email(self):
        self.verify(emails.verification_token(self.user))
        response = self.client.post("/accounts/verify/resend/", {"next": "/space/"}, follow=True)
        self.assertContains(response, "Your email is already verified")
        self.assertEqual(mail.outbox, [])

    def test_resend_is_rate_limited_per_client(self):
        statuses = [self.resend().status_code for _ in range(6)]
        self.assertNotIn(429, statuses[:5])
        self.assertEqual(statuses[-1], 429)

    def test_only_post_is_allowed(self):
        self.assertEqual(self.client.get("/accounts/verify/resend/").status_code, 405)


class BannerTests(VerificationTestCase):
    BANNER = "Please verify your email"

    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.client.force_login(self.user)

    def test_unverified_users_see_it_on_the_space_and_profile_pages(self):
        for page in ["/space/", "/accounts/profile/"]:
            with self.subTest(page):
                response = self.client.get(page)
                self.assertContains(response, self.BANNER)
                self.assertContains(response, 'action="/accounts/verify/resend/"')
                self.assertContains(response, f'name="next" value="{page}"')

    def test_verified_users_do_not(self):
        self.verify(emails.verification_token(self.user))
        for page in ["/space/", "/accounts/profile/"]:
            self.assertNotContains(self.client.get(page), self.BANNER)

    def test_it_is_not_on_other_pages(self):
        create_couple(self.user)
        for page in ["/modes/", "/play/?mode=questions"]:
            self.assertNotContains(self.client.get(page), self.BANNER)

    def test_dismissing_hides_it_until_the_next_sign_in(self):
        response = self.client.post("/accounts/verify/dismiss/", {"next": "/accounts/profile/"})
        self.assertRedirects(response, "/accounts/profile/", fetch_redirect_response=False)
        for page in ["/space/", "/accounts/profile/"]:
            self.assertNotContains(self.client.get(page), self.BANNER)
        self.client.post("/accounts/logout/")
        self.client.post("/accounts/login/", {"username": "ann@example.com", "password": PASSWORD})
        self.assertContains(self.client.get("/space/"), self.BANNER)

    def test_dismiss_needs_a_signed_in_post(self):
        self.assertEqual(self.client.get("/accounts/verify/dismiss/").status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post("/accounts/verify/dismiss/").status_code, 302)
