"""Password reset on Django's reset tokens and forms. Links look like
/accounts/password/reset/confirm/#<uid>.<token> (kept out of logs) and work
for 1 hour. The request page answers identically whether or not the email
has an account. A reset signs the user out everywhere and closes their open
game connections."""

import asyncio
import datetime
import importlib
import re
import threading
from email.utils import parseaddr
from unittest import mock

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.contrib.sessions.models import Session
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, TransactionTestCase, override_settings

import me_nd_you.asgi
from couples import services as couples

PASSWORD = "a-long-passphrase-1"
NEW_PASSWORD = "a-brand-new-passphrase-2"
LINK = re.compile(r"http://testserver/accounts/password/reset/confirm/#([\w.-]+)")
CSRF = re.compile(r'name="csrfmiddlewaretoken" value="[^"]+"')


def wait_for_emails():
    """Reset emails are sent from a background thread; wait for them."""
    for thread in threading.enumerate():
        if thread.name == "account-email":
            thread.join(timeout=10)


class ResetTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.User = get_user_model()
        self.user = self.User.objects.create_user(email="ann@example.com", password=PASSWORD, display_name="Ann")

    def request_reset(self, email="ann@example.com", client=None):
        response = (client or self.client).post("/accounts/password/reset/", {"email": email})
        wait_for_emails()
        return response

    def reset_token(self):
        self.request_reset()
        return LINK.search(mail.outbox[-1].body).group(1)

    def open_link(self, token, client=None):
        return (client or self.client).post("/accounts/password/reset/confirm/", {"token": token})

    def set_password(self, password=NEW_PASSWORD, client=None):
        return (client or self.client).post(
            "/accounts/password/reset/confirm/", {"new_password1": password, "new_password2": password}
        )


class RequestTests(ResetTestCase):
    def test_the_sign_in_page_links_to_it(self):
        response = self.client.get("/accounts/login/")
        self.assertContains(response, 'href="/accounts/password/reset/"')
        self.assertNotContains(response, "secret word")

    def test_a_reset_email_is_sent_with_the_approved_wording(self):
        response = self.request_reset("ANN@example.com")
        self.assertRedirects(response, "/accounts/password/reset/sent/", fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["ann@example.com"])
        self.assertEqual(message.subject, "Reset your Me & You password")
        self.assertEqual(parseaddr(message.from_email), ("Me & You", "no-reply@localhost"))
        self.assertIn("Someone asked to reset the password for this email. "
                      "If it was you, tap the link within 1 hour:", message.body)
        self.assertIn("If it wasn't you, ignore this email; your password stays the same.", message.body)
        self.assertRegex(message.body, LINK)

    def test_the_html_version_is_a_minimal_button_with_the_same_link(self):
        token = self.reset_token()
        (html, mimetype), = mail.outbox[0].alternatives
        self.assertEqual(mimetype, "text/html")
        url = f"http://testserver/accounts/password/reset/confirm/#{token}"
        self.assertRegex(html, rf'<a href="{re.escape(url)}" style="[^"]+">')
        self.assertNotIn("<img", html)
        self.assertNotIn("<style", html)
        self.assertEqual(set(re.findall(r"https?://[^\s\"'<]+", html)), {url})

    def test_the_answer_is_identical_whether_or_not_the_email_has_an_account(self):
        self.User.objects.create_user(email="off@example.com", password=PASSWORD, is_active=False)
        self.User.objects.create_user(email="nopass@example.com")  # Unusable password.

        def answer(email):
            cache.clear()  # Keep the rate limit out of the comparison.
            client = Client()
            response = self.request_reset(email, client)
            page = client.get(response["Location"])
            return response.status_code, response["Location"], page.status_code, CSRF.sub("", page.content.decode())

        known = answer("ann@example.com")
        for email in ["nobody@example.com", "off@example.com", "nopass@example.com"]:
            with self.subTest(email):
                self.assertEqual(answer(email), known)
        self.assertEqual([m.to for m in mail.outbox], [["ann@example.com"]])

    def test_a_malformed_address_gets_a_form_error(self):
        response = self.request_reset("not-an-email")
        self.assertContains(response, "Enter a valid email address.")
        self.assertEqual(mail.outbox, [])

    def test_the_sent_page_does_not_say_whether_an_account_exists(self):
        page = self.client.get("/accounts/password/reset/sent/")
        self.assertContains(page, "If an account uses that email")

    def test_a_sending_failure_gives_the_same_answer_and_is_logged(self):
        with mock.patch("accounts.emails.EmailMultiAlternatives.send", side_effect=OSError("down")), \
                self.assertLogs("accounts.emails", "ERROR"):
            response = self.request_reset()
        self.assertRedirects(response, "/accounts/password/reset/sent/", fetch_redirect_response=False)

    def test_requests_are_rate_limited_per_client(self):
        statuses = [self.client.post("/accounts/password/reset/", {"email": f"x{n}@example.com"}).status_code
                    for n in range(6)]
        self.assertNotIn(429, statuses[:5])
        self.assertEqual(statuses[-1], 429)


class ConfirmTests(ResetTestCase):
    def test_the_link_page_posts_the_token_from_after_the_hash(self):
        response = self.client.get("/accounts/password/reset/confirm/")
        self.assertContains(response, 'action="/accounts/password/reset/confirm/"')
        self.assertContains(response, "location.hash")
        self.assertContains(response, "history.replaceState")

    def test_a_valid_link_asks_for_a_new_password_without_echoing_the_token(self):
        token = self.reset_token()
        response = self.open_link(token)
        self.assertContains(response, 'name="new_password1"')
        self.assertNotContains(response, token.split(".")[1])

    def test_setting_a_new_password_sends_people_to_sign_in(self):
        self.open_link(self.reset_token())
        response = self.set_password()
        self.assertRedirects(response, "/accounts/login/", fetch_redirect_response=False)
        self.assertContains(self.client.get("/accounts/login/"), "Your password is changed")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_a_completed_reset_verifies_the_email(self):
        self.open_link(self.reset_token())
        self.set_password()
        self.assertIsNotNone(self.User.objects.get().email_verified_at)

    def test_links_work_once(self):
        token = self.reset_token()
        self.open_link(token)
        self.set_password()
        self.assertContains(self.open_link(token), "This reset link has expired or isn't valid")

    def test_links_work_for_1_hour(self):
        token = self.reset_token()
        now = datetime.datetime.now()
        with mock.patch.object(PasswordResetTokenGenerator, "_now", return_value=now + datetime.timedelta(minutes=59)):
            self.assertContains(self.open_link(token), 'name="new_password1"')
        with mock.patch.object(PasswordResetTokenGenerator, "_now", return_value=now + datetime.timedelta(minutes=61)):
            self.assertContains(self.open_link(token), "This reset link has expired or isn't valid")

    def test_bad_links_are_refused(self):
        token = self.reset_token()
        cache.clear()  # Only the link posts below count towards the limit.
        for bad in ["", "nonsense", token[:-2] + "xx", token.replace(".", ""), "x" * 5000]:
            with self.subTest(bad[:20]):
                self.assertContains(self.open_link(bad), "This reset link has expired or isn't valid")

    def test_a_new_password_needs_an_opened_link(self):
        response = self.set_password()
        self.assertContains(response, "This reset link has expired or isn't valid")
        self.assertTrue(self.User.objects.get().check_password(PASSWORD))

    def test_the_password_rules_still_apply(self):
        self.open_link(self.reset_token())
        response = self.set_password("ann@example.com")
        self.assertContains(response, 'name="new_password1"')
        self.assertTrue(self.User.objects.get().check_password(PASSWORD))

    def test_every_session_of_that_user_is_signed_out(self):
        phone, laptop, partner = Client(), Client(), Client()
        phone.force_login(self.user)
        laptop.force_login(self.user)
        partner.force_login(self.User.objects.create_user(email="ben@example.com", password=PASSWORD))
        self.open_link(self.reset_token())
        self.set_password()
        for device in [phone, laptop]:
            self.assertRedirects(device.get("/space/"), "/accounts/login/?next=/space/",
                                 fetch_redirect_response=False)
        self.assertEqual(partner.get("/space/").status_code, 200)
        users = [s.get_decoded().get("_auth_user_id") for s in Session.objects.all()]
        self.assertNotIn(str(self.user.pk), users)

    def test_resetting_while_signed_in_on_this_browser_also_works(self):
        self.client.force_login(self.user)
        self.open_link(self.reset_token())
        response = self.set_password()
        self.assertRedirects(response, "/accounts/login/", fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_link_posts_are_rate_limited(self):
        statuses = [self.open_link("nonsense").status_code for _ in range(6)]
        self.assertNotIn(429, statuses[:5])
        self.assertEqual(statuses[-1], 429)


@override_settings(ALLOWED_HOSTS=["testserver", "me-nd-you.onrender.com"])
class OpenGameConnectionTests(TransactionTestCase):
    serialized_rollback = True
    ORIGIN = b"https://me-nd-you.onrender.com"

    def test_a_reset_closes_that_users_open_game_connections_only(self):
        users = [get_user_model().objects.create_user(email=e, password=PASSWORD)
                 for e in ["ann@example.com", "ben@example.com"]]
        couples.create_couple(users[0])
        couples.redeem_invitation(users[1], couples.create_invitation(users[0]))
        cookies = []
        for user in users:
            client = Client()
            client.force_login(user)
            cookies.append(f"sessionid={client.cookies['sessionid'].value}".encode())

        def reset_ann():
            cache.clear()
            client = Client()
            client.post("/accounts/password/reset/", {"email": "ann@example.com"})
            wait_for_emails()
            client.post("/accounts/password/reset/confirm/", {"token": LINK.search(mail.outbox[-1].body).group(1)})
            client.post("/accounts/password/reset/confirm/",
                        {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD})

        async def scenario():
            app = importlib.reload(me_nd_you.asgi).application
            pages = []
            for cookie in cookies:
                page = WebsocketCommunicator(app, "/ws/room/questions/questions/",
                                             headers=[(b"origin", self.ORIGIN), (b"cookie", cookie)])
                assert (await page.connect())[0]
                await page.receive_json_from(timeout=2)  # The snapshot.
                pages.append(page)
            await asyncio.get_running_loop().run_in_executor(None, reset_ann)
            ann, ben = pages
            reply = await ann.receive_json_from(timeout=2)
            closed = await ann.receive_output(timeout=2)
            ben_untouched = await ben.receive_nothing(timeout=0.5)
            await ben.disconnect()
            # Ann's old session can't reconnect either.
            again = WebsocketCommunicator(app, "/ws/room/questions/questions/",
                                          headers=[(b"origin", self.ORIGIN), (b"cookie", cookies[0])])
            reconnected, _ = await again.connect()
            return reply, closed, ben_untouched, reconnected

        reply, closed, ben_untouched, reconnected = async_to_sync(scenario)()
        self.assertEqual(reply["reason"], "forbidden")
        self.assertEqual(closed, {"type": "websocket.close", "code": 4403})
        self.assertTrue(ben_untouched)
        self.assertFalse(reconnected)
