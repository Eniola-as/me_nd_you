"""Chat messages: only the two members of the active couple can read or
send, membership is checked on every call, and a closed couple's messages
are hidden from everyone until an admin reopens it."""

import datetime
import uuid
from unittest import mock

from django.contrib import admin
from django.test import TestCase
from django.utils import timezone

from chat import services
from chat.models import ChatMessage
from couples import services as couples

from . import make_couple, with_chat_key


@with_chat_key
class ChatServiceTestCase(TestCase):
    def setUp(self):
        self.couple, (self.ann, self.ben) = make_couple("ann@example.com", "ben@example.com")

    def send(self, user, text="Hi", request_id=None, couple=None):
        return services.send(user, (couple or self.couple).pk, text, request_id)

    def texts(self, user, **kwargs):
        return [m["text"] for m in services.history(user, self.couple.pk, **kwargs)["messages"]]


class SendTests(ChatServiceTestCase):
    def test_members_send_and_both_read(self):
        self.send(self.ann, "Hello Ben")
        self.send(self.ben, "Hello Ann")
        self.assertEqual(self.texts(self.ann), ["Hello Ben", "Hello Ann"])
        self.assertEqual(self.texts(self.ben), ["Hello Ben", "Hello Ann"])

    def test_each_reader_sees_which_messages_are_theirs(self):
        self.send(self.ann, "Mine")
        shown = services.history(self.ben, self.couple.pk)["messages"][0]
        self.assertFalse(shown["mine"])
        self.assertTrue(services.history(self.ann, self.couple.pk)["messages"][0]["mine"])

    def test_text_is_trimmed_and_limited_to_1000_characters(self):
        self.assertEqual(services.serialize(self.send(self.ann, "  hi  "), self.ann)["text"], "hi")
        self.send(self.ann, "x" * 1000)
        for bad in ["", "   ", "x" * 1001, None, 5, ["hi"]]:
            with self.subTest(str(bad)[:10]), self.assertRaises(services.Invalid):
                self.send(self.ann, bad)

    def test_30_messages_per_minute_per_person(self):
        for n in range(30):
            self.send(self.ann, f"m{n}")
        with self.assertRaises(services.RateLimited):
            self.send(self.ann, "one too many")
        self.send(self.ben, "Ben still can")  # Per person.
        later = timezone.now() + datetime.timedelta(seconds=61)
        with mock.patch("django.utils.timezone.now", return_value=later):
            self.send(self.ann, "a minute later")

    def test_a_retried_request_is_saved_once(self):
        request_id = str(uuid.uuid4())
        first = self.send(self.ann, "Once", request_id)
        again = self.send(self.ann, "Once", request_id)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(ChatMessage.objects.count(), 1)

    def test_a_bad_request_id_is_refused(self):
        with self.assertRaises(services.Invalid):
            self.send(self.ann, "Hi", "not-a-uuid")

    def test_outsiders_cannot_send_or_read(self):
        _, (cy,) = make_couple("cy@example.com")
        loner = type(self.ann).objects.create_user(email="dee@example.com", password="a-long-passphrase-1")
        for user in [cy, loner]:
            with self.subTest(user.email):
                with self.assertRaises(services.Forbidden):
                    self.send(user, "Let me in")
                with self.assertRaises(services.Forbidden):
                    services.history(user, self.couple.pk)

    def test_a_member_cannot_post_into_another_couple(self):
        other, _ = make_couple("cy@example.com", "dee@example.com")
        with self.assertRaises(services.Forbidden):
            self.send(self.ann, "Wrong room", couple=other)

    def test_membership_is_checked_on_every_call(self):
        self.send(self.ann, "Before")
        couples.close_couple(self.ben)
        with self.assertRaises(services.Forbidden):
            self.send(self.ann, "After")

    def test_the_partner_is_told_only_after_commit(self):
        with mock.patch("chat.services.notify_couple") as notify:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                message = self.send(self.ann, "Hi")
            notify.assert_not_called()
            for callback in callbacks:
                callback()
        notify.assert_called_once_with(self.couple.pk, {"type": "chat.message", "id": message.pk})

    def test_a_failed_save_tells_nobody(self):
        with mock.patch("chat.services.notify_couple") as notify, \
                mock.patch("chat.models.ChatMessage.objects.create", side_effect=RuntimeError("disk full")), \
                self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(RuntimeError):
                self.send(self.ann, "Hi")
        notify.assert_not_called()


class HistoryTests(ChatServiceTestCase):
    def test_the_last_50_load_first_and_older_ones_on_request(self):
        for n in range(120):
            ChatMessage.objects.create(couple=self.couple, author=self.ann, body=services.crypto.encrypt(f"m{n}"))
        page = services.history(self.ben, self.couple.pk)
        self.assertEqual([m["text"] for m in page["messages"]], [f"m{n}" for n in range(70, 120)])
        self.assertTrue(page["has_more"])
        older = services.history(self.ben, self.couple.pk, before=page["messages"][0]["id"])
        self.assertEqual([m["text"] for m in older["messages"]], [f"m{n}" for n in range(20, 70)])
        oldest = services.history(self.ben, self.couple.pk, before=older["messages"][0]["id"])
        self.assertEqual(len(oldest["messages"]), 20)
        self.assertFalse(oldest["has_more"])

    def test_a_bad_cursor_is_refused(self):
        for bad in ["x", -1, 1.5, True]:
            with self.subTest(bad), self.assertRaises(services.Invalid):
                services.history(self.ann, self.couple.pk, before=bad)


class DeleteTests(ChatServiceTestCase):
    def test_you_can_delete_your_own_message_for_both(self):
        message = self.send(self.ann, "Oops")
        services.delete(self.ann, self.couple.pk, message.pk)
        self.assertEqual(self.texts(self.ben), [])
        self.assertFalse(ChatMessage.objects.filter(pk=message.pk).exists())

    def test_you_cannot_delete_your_partners_message(self):
        message = self.send(self.ann, "Mine")
        with self.assertRaises(services.Invalid):
            services.delete(self.ben, self.couple.pk, message.pk)
        self.assertEqual(self.texts(self.ann), ["Mine"])

    def test_deleting_tells_the_partner_after_commit(self):
        message = self.send(self.ann, "Oops")
        with mock.patch("chat.services.notify_couple") as notify, self.captureOnCommitCallbacks(execute=True):
            services.delete(self.ann, self.couple.pk, message.pk)
        notify.assert_called_once_with(self.couple.pk, {"type": "chat.deleted", "id": message.pk})

    def test_unknown_or_other_couples_messages_are_refused(self):
        other, (cy, _) = make_couple("cy@example.com", "dee@example.com")
        theirs = services.send(cy, other.pk, "Theirs", None)
        for message_id in [theirs.pk, 999999, "x"]:
            with self.subTest(message_id), self.assertRaises(services.Invalid):
                services.delete(self.ann, self.couple.pk, message_id)
        self.assertTrue(ChatMessage.objects.filter(pk=theirs.pk).exists())


class ClosedCoupleTests(ChatServiceTestCase):
    def test_closing_hides_messages_from_both_and_reopening_brings_them_back(self):
        self.send(self.ann, "Ours")
        couples.close_couple(self.ann)
        for user in [self.ann, self.ben]:
            with self.assertRaises(services.Forbidden):
                services.history(user, self.couple.pk)
        self.assertTrue(ChatMessage.objects.exists())  # Hidden, not deleted.
        couples.reopen_couple(self.couple)
        self.assertEqual(self.texts(self.ben), ["Ours"])

    def test_a_new_couple_never_sees_an_old_couples_messages(self):
        self.send(self.ann, "Old couple")
        couples.close_couple(self.ann)
        new = couples.create_couple(self.ann)
        self.assertEqual(services.history(self.ann, new.pk)["messages"], [])

    def test_messages_are_not_in_the_admin(self):
        self.assertFalse(any(model._meta.app_label == "chat" for model in admin.site._registry))
