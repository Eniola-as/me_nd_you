"""Deleting an account: closed at once (signed out everywhere, couple space
closed for both), a 7-day window in which signing in cancels it, then
everything the user wrote is permanently deleted. Purging runs in the app
at most hourly and on every deploy."""

import uuid
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from django.utils.dateformat import format as format_date

from accounts import deletion
from accounts.models import Consent
from chat import services as chat
from chat.models import ChatMessage, ChatReaction
from chat.tests import with_chat_key
from couples import services as couples
from couples.models import Membership
from game.models import CustomQuestion

PASSWORD = "a-long-passphrase-1"
URL = "/accounts/profile/delete/"
POLICY_WORDING = ("Your account is closed immediately. After a 7-day cancellation period, it is permanently "
                  "deleted, usually within a day, and always within 30 days.")


def make_user(email, name):
    return get_user_model().objects.create_user(email=email, password=PASSWORD, display_name=name)


def signed_in(user):
    client = Client()
    client.force_login(user)
    return client


def squash(html):
    return " ".join(html.split())


@with_chat_key
@override_settings(PRIVACY_CONTACT_EMAIL="privacy@example.com")
class DeleteAccountTests(TestCase):
    def setUp(self):
        cache.clear()
        self.ann, self.ben = make_user("ann@example.com", "Ann"), make_user("ben@example.com", "Ben")
        self.couple = couples.create_couple(self.ann)
        couples.redeem_invitation(self.ben, couples.create_invitation(self.ann))
        self.client = signed_in(self.ann)

    def delete(self, password=PASSWORD, confirm="yes", client=None):
        with self.captureOnCommitCallbacks(execute=True):
            return (client or self.client).post(URL, {"password": password, "confirm": confirm})

    def test_the_profile_explains_deletion_with_the_policy_wording(self):
        html = squash(self.client.get("/accounts/profile/").content.decode())
        self.assertIn(f'action="{URL}"', html)
        self.assertIn(POLICY_WORDING, html)
        self.assertIn("closes your couple space for both of you", html)

    def test_a_wrong_password_or_no_confirmation_changes_nothing(self):
        for password, confirm in [("wrong-password", "yes"), (PASSWORD, "")]:
            with self.subTest(password=password, confirm=confirm):
                response = self.delete(password, confirm)
                self.assertEqual(response.status_code, 200)
                self.ann.refresh_from_db()
                self.assertTrue(self.ann.is_active)
                self.assertIsNone(self.ann.deletion_requested_at)
        self.assertEqual(mail.outbox, [])

    def test_deleting_closes_the_account_at_once_everywhere(self):
        other_device = signed_in(self.ann)
        response = self.delete()
        self.assertRedirects(response, "/accounts/deleted/", fetch_redirect_response=False)
        self.ann.refresh_from_db()
        self.assertFalse(self.ann.is_active)
        self.assertIsNotNone(self.ann.deletion_requested_at)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(other_device.get("/space/").status_code, 302)  # Signed out there too.
        self.assertFalse(any(s.get_decoded().get("_auth_user_id") == str(self.ann.pk) for s in Session.objects.all()))
        self.assertEqual(Client().get("/accounts/deleted/").status_code, 200)

    def test_deleting_closes_the_couple_space_for_both(self):
        self.delete()
        self.couple.refresh_from_db()
        self.assertIsNotNone(self.couple.closed_at)
        self.assertFalse(Membership.objects.active().filter(couple=self.couple).exists())
        # The partner is told it was a deletion (couples/test_closure_notice.py);
        # the one deleting gets only the deletion email, which says so.
        self.assertEqual([m.to[0] for m in mail.outbox if "couple space has closed" in m.subject],
                         ["ben@example.com"])
        deletion_email = next(m for m in mail.outbox if m.to == ["ann@example.com"])
        self.assertIn("Your couple space has closed for both of you.", squash(deletion_email.body))

    def test_a_confirmation_email_gives_the_date_and_how_to_cancel(self):
        self.delete()
        message = next(m for m in mail.outbox if m.subject == "Your Me & You account will be deleted")
        self.assertEqual(message.to, ["ann@example.com"])
        self.ann.refresh_from_db()
        date = format_date(timezone.localtime(self.ann.deletion_requested_at + timedelta(days=7)), "j F Y")
        body = squash(message.body)
        self.assertIn(date, body)
        self.assertIn(f"sign in before {date}", body)
        self.assertIn("http://testserver/accounts/login/", body)
        self.assertIn("privacy@example.com", body)
        self.assertNotIn("Ben", body)
        self.assertIn(date, message.alternatives[0][0])

    def test_signing_in_within_7_days_cancels_the_deletion(self):
        self.delete()
        with mock.patch("django.utils.timezone.now", return_value=timezone.now() + timedelta(days=6, hours=23)):
            client = Client()
            response = client.post("/accounts/login/", {"username": "ann@example.com", "password": PASSWORD},
                                   follow=True)
        self.ann.refresh_from_db()
        self.assertTrue(self.ann.is_active)
        self.assertIsNone(self.ann.deletion_requested_at)
        self.assertContains(response, "Your account deletion is cancelled.")
        self.assertEqual(client.get("/accounts/profile/").status_code, 200)

    def test_a_wrong_password_never_cancels_it(self):
        self.delete()
        Client().post("/accounts/login/", {"username": "ann@example.com", "password": "wrong-password"})
        self.ann.refresh_from_db()
        self.assertFalse(self.ann.is_active)

    def test_after_7_days_signing_in_no_longer_works(self):
        self.delete()
        with mock.patch("django.utils.timezone.now", return_value=timezone.now() + timedelta(days=7, minutes=1)):
            response = Client().post("/accounts/login/", {"username": "ann@example.com", "password": PASSWORD})
        self.assertEqual(response.status_code, 200)  # The form again, with the usual error.
        self.ann.refresh_from_db()
        self.assertFalse(self.ann.is_active)

    def test_accounts_switched_off_by_an_admin_are_not_switched_back_on(self):
        get_user_model().objects.filter(pk=self.ben.pk).update(is_active=False)
        Client().post("/accounts/login/", {"username": "ben@example.com", "password": PASSWORD})
        self.ben.refresh_from_db()
        self.assertFalse(self.ben.is_active)

    def test_the_consent_page_also_offers_deletion(self):
        Consent.objects.filter(user=self.ann).delete()
        html = squash(self.client.get("/accounts/consent/").content.decode())
        self.assertIn(f'action="{URL}"', html)
        response = self.delete()
        self.assertRedirects(response, "/accounts/deleted/", fetch_redirect_response=False)


@with_chat_key
class PurgeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.ann, self.ben = make_user("ann@example.com", "Ann"), make_user("ben@example.com", "Ben")
        self.couple = couples.create_couple(self.ann)
        couples.redeem_invitation(self.ben, couples.create_invitation(self.ann))
        self.anns = chat.send(self.ann, self.couple.id, "Ann wrote this", str(uuid.uuid4()))
        self.bens = chat.send(self.ben, self.couple.id, "Ben wrote this", str(uuid.uuid4()))
        chat.react(self.ann, self.couple.id, self.bens.id, "❤️")
        chat.react(self.ben, self.couple.id, self.anns.id, "😂")
        CustomQuestion.objects.create(space=self.couple, text="Ann's?", mode="questions", author=self.ann)
        CustomQuestion.objects.create(space=self.couple, text="Ben's?", mode="questions", author=self.ben)
        CustomQuestion.objects.create(space=self.couple, text="Nobody knows?", mode="questions")
        with self.captureOnCommitCallbacks(execute=True):
            deletion.request_deletion(self.ann)

    def age(self, days):
        get_user_model().objects.filter(pk=self.ann.pk).update(
            deletion_requested_at=timezone.now() - timedelta(days=days))

    def test_nothing_is_purged_during_the_7_days(self):
        self.age(6)
        self.assertEqual(deletion.purge_due()["accounts"], 0)
        self.assertTrue(get_user_model().objects.filter(pk=self.ann.pk).exists())

    def test_after_7_days_everything_the_user_wrote_is_deleted(self):
        self.age(8)
        self.assertEqual(deletion.purge_due()["accounts"], 1)
        self.assertFalse(get_user_model().objects.filter(email="ann@example.com").exists())
        self.assertFalse(Consent.objects.filter(user_id=self.ann.pk).exists())
        self.assertEqual(list(ChatMessage.objects.values_list("pk", flat=True)), [self.bens.pk])
        self.assertEqual(list(ChatReaction.objects.values_list("emoji", flat=True)), [])  # Ben's was on Ann's.
        self.assertEqual(sorted(CustomQuestion.objects.values_list("text", flat=True)), ["Ben's?", "Nobody knows?"])
        self.assertFalse(Membership.objects.filter(user_id=self.ann.pk).exists())
        # The partner's account is untouched.
        self.assertTrue(get_user_model().objects.filter(pk=self.ben.pk, is_active=True).exists())

    def test_other_inactive_accounts_are_never_purged(self):
        get_user_model().objects.filter(pk=self.ben.pk).update(is_active=False)
        self.age(8)
        deletion.purge_due()
        self.assertTrue(get_user_model().objects.filter(pk=self.ben.pk).exists())

    def test_the_app_purges_at_most_once_an_hour(self):
        self.age(8)
        with mock.patch("accounts.deletion.purge_due", wraps=deletion.purge_due) as purge:
            Client().get("/")
            Client().get("/privacy/")
            self.assertEqual(purge.call_count, 1)
            cache.delete(deletion.LAST_PURGE_KEY)  # An hour later.
            Client().get("/")
            self.assertEqual(purge.call_count, 2)
        self.assertFalse(get_user_model().objects.filter(pk=self.ann.pk).exists())

    def test_a_failing_purge_never_breaks_the_page(self):
        with mock.patch("accounts.deletion.purge_due", side_effect=RuntimeError("boom")):
            self.assertEqual(Client().get("/").status_code, 200)

    def test_the_deploy_command_purges(self):
        self.age(8)
        out = StringIO()
        call_command("purge_deleted_accounts", stdout=out)
        self.assertIn("1 account", out.getvalue())
        self.assertFalse(get_user_model().objects.filter(pk=self.ann.pk).exists())

    def test_render_runs_the_purge_on_every_deploy(self):
        render_yaml = (Path(settings.BASE_DIR) / "render.yaml").read_text()
        self.assertIn("preDeployCommand: python manage.py migrate --noinput && python manage.py "
                      "purge_deleted_accounts", render_yaml)
