"""When a couple space closes, both members (the closer too) get a neutral
email and an in-app notice with the date until which they can ask for a
restore or download their data. 30 days after closing the space and
everything in it is permanently deleted."""

import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from django.utils.dateformat import format as format_date
from django.utils.html import strip_tags

from accounts.deletion import purge_due
from chat import services as chat
from chat.models import ChatMessage, ChatReaction
from chat.tests import with_chat_key
from couples import services
from couples.models import Couple, Invitation, Membership
from game.models import CustomQuestion
from play import services as play
from play.models import GameRoom

PASSWORD = "a-long-passphrase-1"
SECRET_QUESTION = "Our very private question?"
SECRET_MESSAGE = "Our very private message"


def make_user(email, name):
    return get_user_model().objects.create_user(email=email, password=PASSWORD, display_name=name)


def deadline(couple):
    return format_date(timezone.localtime(couple.closed_at + timedelta(days=30)), "j F Y")


@with_chat_key
@override_settings(PRIVACY_CONTACT_EMAIL="privacy@example.com")
class ClosureNoticeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.ann, self.ben = make_user("ann@example.com", "Annabel"), make_user("ben@example.com", "Benedict")
        self.couple = services.create_couple(self.ann)
        services.redeem_invitation(self.ben, services.create_invitation(self.ann))
        CustomQuestion.objects.create(space=self.couple, text=SECRET_QUESTION, mode="questions", author=self.ann)
        chat.send(self.ben, self.couple.id, SECRET_MESSAGE, str(uuid.uuid4()))
        self.clients = {}
        for user in (self.ann, self.ben):
            self.clients[user.email] = Client()
            self.clients[user.email].force_login(user)

    def leave(self, who="ann@example.com"):
        with self.captureOnCommitCallbacks(execute=True):
            self.clients[who].post("/space/", {"action": "leave_couple", "confirm": "yes"})
        self.couple.refresh_from_db()
        self.assertIsNotNone(self.couple.closed_at)

    def test_both_members_get_one_email_including_the_one_who_left(self):
        self.leave()
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["ann@example.com", "ben@example.com"])
        self.assertTrue(all(m.subject == "Your Me & You couple space has closed" for m in mail.outbox))

    def test_the_email_has_the_approved_wording_and_date(self):
        self.leave()
        date = deadline(self.couple)
        message = next(m for m in mail.outbox if m.to == ["ben@example.com"])
        for line in [
            "Hi Benedict,",
            "Your couple space on Me & You has closed. It's no longer visible in the app.",
            f"If this was a mistake, you and your partner can contact us before {date} to ask for it to be restored.",
            f"You can download your data from it until {date}. After that, everything in the space will be "
            "permanently deleted.",
            "To download your data, go to your profile page: http://testserver/accounts/profile/#download",
            "Questions? Contact us at privacy@example.com.",
        ]:
            self.assertIn(line, " ".join(message.body.split()).replace("\n", " "))
        html = message.alternatives[0][0]
        self.assertIn("Download my data", html)
        self.assertIn('href="http://testserver/accounts/profile/#download"', html)
        self.assertIn(date, html)

    def test_the_email_never_says_who_closed_it_why_or_what_was_in_it(self):
        self.leave("ann@example.com")
        for message in mail.outbox:
            own, other = ("Annabel", "Benedict") if message.to == ["ann@example.com"] else ("Benedict", "Annabel")
            other_email = "ben@example.com" if own == "Annabel" else "ann@example.com"
            self.assertIn(f"Hi {own},", message.body)
            # The HTML's visible text (its styles may say "margin-left").
            for text in [message.subject, message.body, strip_tags(message.alternatives[0][0])]:
                for leaked in [other, other_email, SECRET_QUESTION, SECRET_MESSAGE, "left", "their account",
                               "your partner closed", "you closed", "because"]:
                    self.assertNotIn(leaked, text)

    def test_without_a_display_name_it_just_says_hi(self):
        get_user_model().objects.filter(pk=self.ben.pk).update(display_name="")
        self.leave()
        message = next(m for m in mail.outbox if m.to == ["ben@example.com"])
        self.assertTrue(message.body.startswith("Hi,\n"), message.body[:40])

    def test_both_members_see_the_notice_on_the_space_page_until_the_date(self):
        self.leave()
        date = deadline(self.couple)
        for who in self.clients:
            with self.subTest(who):
                html = " ".join(self.clients[who].get("/space/").content.decode().split())
                self.assertIn(
                    "Your couple space has closed. If this was a mistake, you and your partner can contact us "
                    f"before {date} to ask for it to be restored. You can download your data from it until {date}.",
                    html,
                )
                self.assertIn('href="/accounts/profile/#download"', html)
                self.assertNotIn("Annabel" if who == "ben@example.com" else "Benedict", html)
        Couple.objects.filter(pk=self.couple.pk).update(closed_at=timezone.now() - timedelta(days=31))
        self.assertNotContains(self.clients["ben@example.com"].get("/space/"), "Your couple space has closed.")

    def test_the_leave_warning_says_restoring_is_only_possible_for_30_days(self):
        html = " ".join(self.clients["ann@example.com"].get("/space/").content.decode().split())
        self.assertIn("an admin can only restore it within 30 days", html)
        self.assertIn("permanently deleted", html)
        self.assertNotIn("Nothing is deleted", html)


@with_chat_key
@override_settings(PRIVACY_CONTACT_EMAIL="privacy@example.com")
class ClosedByAccountDeletionTests(TestCase):
    """When the space closes because a partner deletes their account, the
    other partner gets the neutral closure notice at once, since the deletion
    can still be cancelled. Only when it becomes final (the purge after 7
    days) are they told their partner deleted their account (2026-10-29)."""

    def setUp(self):
        cache.clear()
        self.ann, self.ben = make_user("ann@example.com", "Annabel"), make_user("ben@example.com", "Benedict")
        self.couple = services.create_couple(self.ann)
        services.redeem_invitation(self.ben, services.create_invitation(self.ann))
        CustomQuestion.objects.create(space=self.couple, text=SECRET_QUESTION, mode="questions", author=self.ann)
        chat.send(self.ann, self.couple.id, SECRET_MESSAGE, str(uuid.uuid4()))
        ann_client = Client()
        ann_client.force_login(self.ann)
        with self.captureOnCommitCallbacks(execute=True):
            ann_client.post("/accounts/profile/delete/", {"password": PASSWORD, "confirm": "yes"})
        self.couple.refresh_from_db()
        self.ben_client = Client()
        self.ben_client.force_login(self.ben)

    def emails_to_ben(self):
        return [m for m in mail.outbox if m.to == ["ben@example.com"]]

    def make_final(self):
        """Seven days pass and the purge runs."""
        from accounts.deletion import purge_due

        get_user_model().objects.filter(pk=self.ann.pk).update(
            deletion_requested_at=timezone.now() - timedelta(days=8))
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            purge_due()

    def test_at_once_the_partner_gets_only_the_neutral_closure_email(self):
        emails = self.emails_to_ben()
        self.assertEqual([m.subject for m in emails], ["Your Me & You couple space has closed"])
        body = " ".join(emails[0].body.split())
        date = deadline(self.couple)
        self.assertIn(f"If this was a mistake, you and your partner can contact us before {date}", body)
        self.assertIn(f"You can download your data from it until {date}.", body)
        for text in [body, strip_tags(emails[0].alternatives[0][0])]:
            for leaked in ["deleted their", "their account", "Annabel", "ann@example.com", SECRET_QUESTION,
                           SECRET_MESSAGE]:
                self.assertNotIn(leaked, text)
        # The one deleting gets only their deletion email.
        self.assertEqual([m.subject for m in mail.outbox if m.to == ["ann@example.com"]],
                         ["Your Me & You account will be deleted"])

    def test_while_it_can_be_cancelled_the_app_shows_the_neutral_notice(self):
        html = " ".join(self.ben_client.get("/space/").content.decode().split())
        self.assertIn("Your couple space has closed. If this was a mistake", html)
        self.assertNotIn("deleted their", html)

    def test_when_the_deletion_is_final_the_partner_is_told(self):
        self.make_final()
        d30 = deadline(self.couple)
        emails = self.emails_to_ben()
        self.assertEqual([m.subject for m in emails], ["Your partner's Me & You account has been deleted"])
        body = " ".join(emails[0].body.split())
        for line in [
            "Hi Benedict,",
            "Your partner deleted their Me & You account, and it has now been permanently deleted, with their "
            "messages, reactions and the questions they wrote.",
            f"Your own messages and the rest of your closed couple space stay until {d30}. You can download your "
            "data until then. After that, everything in the space will be permanently deleted.",
            f"To download your data, go to your profile page: {settings.SITE_URL}/accounts/profile/#download",
            "Questions? Contact us at privacy@example.com.",
        ]:
            self.assertIn(line, body)
        self.assertIn("Download my data", emails[0].alternatives[0][0])
        for text in [body, strip_tags(emails[0].alternatives[0][0])]:
            for leaked in ["Annabel", "ann@example.com", SECRET_QUESTION, SECRET_MESSAGE]:
                self.assertNotIn(leaked, text)

    def test_when_the_deletion_is_final_the_app_says_so(self):
        self.make_final()
        html = " ".join(self.ben_client.get("/space/").content.decode().split())
        self.assertIn("Your partner deleted their Me &amp; You account, so your couple space has closed.", html)
        self.assertIn("Their messages, reactions and the questions they wrote have been permanently deleted.", html)
        self.assertIn(f"Your own messages and the rest of the space stay until {deadline(self.couple)}.", html)
        self.assertNotIn("Annabel", html)

    def test_if_the_deletion_is_cancelled_the_partner_is_never_told_it_happened(self):
        Client().post("/accounts/login/", {"username": "ann@example.com", "password": PASSWORD})
        mail.outbox.clear()
        from accounts.deletion import purge_due

        with self.captureOnCommitCallbacks(execute=True):
            purge_due()
        self.assertEqual(mail.outbox, [])
        html = " ".join(self.ben_client.get("/space/").content.decode().split())
        self.assertNotIn("deleted their", html)
        self.assertIn("Your couple space has closed. If this was a mistake", html)
        # Cancelling restores the account, not the space: it stays closed.
        self.couple.refresh_from_db()
        self.assertIsNotNone(self.couple.closed_at)

    def test_the_space_remembers_why_it_closed(self):
        # It must outlive the deleted account (closed_by is cleared then).
        self.assertEqual(self.couple.closed_reason, Couple.CLOSED_BY_ACCOUNT_DELETION)
        other = services.create_couple(make_user("cat@example.com", "Cat"))
        with self.captureOnCommitCallbacks(execute=True):
            services.close_couple(get_user_model().objects.get(email="cat@example.com"))
        other.refresh_from_db()
        self.assertEqual(other.closed_reason, Couple.CLOSED_BY_LEAVING)


@with_chat_key
class ClosedSpaceRetentionTests(TestCase):
    def make_couple(self, n, closed_days_ago=None):
        ann, ben = make_user(f"a{n}@example.com", "A"), make_user(f"b{n}@example.com", "B")
        couple = services.create_couple(ann)
        services.redeem_invitation(ben, services.create_invitation(ann))
        CustomQuestion.objects.create(space=couple, text="Q?", mode="questions", author=ann)
        message = chat.send(ann, couple.id, "Hello", str(uuid.uuid4()))
        chat.react(ben, couple.id, message.id, "❤️")
        play.room_for(ann, "questions", "questions")
        if closed_days_ago is not None:
            with self.captureOnCommitCallbacks(execute=True):
                services.close_couple(ann)
            Couple.objects.filter(pk=couple.pk).update(closed_at=timezone.now() - timedelta(days=closed_days_ago))
        return couple, (ann, ben)

    def test_spaces_closed_over_30_days_ago_are_deleted_with_everything_in_them(self):
        old, (ann, ben) = self.make_couple(1, closed_days_ago=31)
        recent, _ = self.make_couple(2, closed_days_ago=29)
        active, _ = self.make_couple(3)
        result = purge_due()
        self.assertEqual(result["couple_spaces"], 1)
        self.assertFalse(Couple.objects.filter(pk=old.pk).exists())
        for model, field in [(CustomQuestion, "space"), (ChatMessage, "couple"), (GameRoom, "couple"),
                             (Membership, "couple"), (Invitation, "couple")]:
            self.assertFalse(model.objects.filter(**{field: old.pk}).exists(), model.__name__)
        self.assertFalse(ChatReaction.objects.filter(message__couple=old.pk).exists())
        # The accounts themselves stay; only the space went.
        self.assertTrue(get_user_model().objects.filter(pk__in=[ann.pk, ben.pk]).count() == 2)
        for kept in (recent, active):
            self.assertTrue(Couple.objects.filter(pk=kept.pk).exists())
            self.assertTrue(CustomQuestion.objects.filter(space=kept).exists())
