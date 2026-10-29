"""Stored in-app notifications and push: one unread notification per kind,
never any message or answer text, only for the person they're for, and a
push only when a new one is created and the person isn't in the app."""

import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from accounts.consents import CONSENT_KINDS, record_consents
from chat import presence
from chat import services as chat
from chat.tests import with_chat_key
from couples import services as couples
from play import modes
from play import services as play
from play.models import CoupleMode

from . import push, services
from .models import Notification, PushSubscription

VAPID = {"VAPID_PUBLIC_KEY": "BPublicKeyForTests", "VAPID_PRIVATE_KEY": "private-key-for-tests",
         "VAPID_SUBJECT": "mailto:test@example.com"}


def make_couple(*emails):
    users = [get_user_model().objects.create_user(email=e, password="a-long-passphrase-1",
                                                  display_name=e.split("@")[0].title()) for e in emails]
    for user in users:
        record_consents(user, CONSENT_KINDS)
    couple = couples.create_couple(users[0])
    for user in users[1:]:
        couples.redeem_invitation(user, couples.create_invitation(users[0]))
    return couple, users


@with_chat_key
@override_settings(**VAPID)
class NotificationSetup(TestCase):
    def setUp(self):
        presence.reset()
        self.couple, (self.ann, self.ben) = make_couple("ann@example.com", "ben@example.com")
        # Pushes run straight away in tests instead of on a thread.
        patcher = mock.patch.object(push, "run", lambda fn: fn())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.webpush = mock.patch("notifications.push.webpush").start()
        self.addCleanup(mock.patch.stopall)

    def send(self, user, text):
        with self.captureOnCommitCallbacks(execute=True):
            return chat.send(user, self.couple.pk, text, str(uuid.uuid4()))

    def client_for(self, user):
        client = Client()
        client.force_login(user)
        return client


class ChatNotificationTests(NotificationSetup):
    def test_a_message_notifies_the_partner_not_the_sender(self):
        self.send(self.ann, "Hello")
        self.assertEqual(Notification.objects.filter(user=self.ben, kind=services.CHAT).count(), 1)
        self.assertFalse(Notification.objects.filter(user=self.ann).exists())

    def test_many_messages_make_one_unread_notification(self):
        for text in ["one", "two", "three"]:
            self.send(self.ann, text)
        self.assertEqual(Notification.objects.filter(user=self.ben, read_at__isnull=True).count(), 1)

    def test_a_retried_send_makes_no_second_notification(self):
        request_id = str(uuid.uuid4())
        with self.captureOnCommitCallbacks(execute=True):
            chat.send(self.ann, self.couple.pk, "Once", request_id)
        services.mark_read(self.ben)
        with self.captureOnCommitCallbacks(execute=True):
            chat.send(self.ann, self.couple.pk, "Once", request_id)
        self.assertFalse(Notification.objects.filter(user=self.ben, read_at__isnull=True).exists())

    def test_reading_the_chat_clears_the_chat_notification(self):
        message = self.send(self.ann, "Hello")
        chat.mark_read(self.ben, self.couple.pk, message.pk)
        self.assertEqual(services.unread_count(self.ben), 0)

    def test_nothing_stored_or_shown_contains_the_message(self):
        self.send(self.ann, "The secret words")
        stored = list(Notification.objects.values())
        self.assertNotIn("secret", json.dumps(stored, default=str))
        listing = self.client_for(self.ben).get("/api/notifications/").content.decode()
        self.assertIn("Ann sent you a message", listing)
        self.assertNotIn("secret", listing)


class GameNotificationTests(NotificationSetup):
    def setUp(self):
        super().setUp()
        with mock.patch("play.modes.notify"), self.captureOnCommitCallbacks(execute=True):
            modes.start(self.ann, "spicy")
        self.room = play.room_for(self.ann, "answer_reveal", "spicy")

    def answer(self, user, text):
        self.room.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            play.apply_action(user, self.room.pk, "answer", self.room.version, str(uuid.uuid4()),
                              {"card": self.room.state["current"]["key"], "text": text})

    def test_an_answer_tells_the_partner_without_the_answer(self):
        self.answer(self.ann, "Private spicy answer")
        note = Notification.objects.get(user=self.ben)
        self.assertEqual((note.kind, note.mode), (services.ANSWERED, "spicy"))
        listing = self.client_for(self.ben).get("/api/notifications/").content.decode()
        self.assertIn("Ann answered a question in Spicy Only", listing)
        self.assertNotIn("Private spicy answer", listing)

    def test_when_both_have_answered_the_first_answerer_hears_they_are_revealed(self):
        self.answer(self.ann, "A")
        self.answer(self.ben, "B")
        self.assertTrue(Notification.objects.filter(user=self.ann, kind=services.REVEALED).exists())

    def test_a_mode_switch_request_notifies_the_partner(self):
        with mock.patch("play.modes.notify"), self.captureOnCommitCallbacks(execute=True):
            modes.request_switch(self.ann, "truth", CoupleMode.objects.get(couple=self.couple).version)
        note = Notification.objects.get(user=self.ben, kind=services.MODE_REQUESTED)
        self.assertEqual(note.mode, "truth")


class AccessTests(NotificationSetup):
    def test_people_only_see_and_open_their_own(self):
        self.send(self.ann, "Hi")
        note = Notification.objects.get(user=self.ben)
        self.assertEqual(json.loads(self.client_for(self.ann).get("/api/notifications/").content)["items"], [])
        response = self.client_for(self.ann).post(f"/notifications/{note.pk}/open/")
        self.assertEqual(response.status_code, 404)
        note.refresh_from_db()
        self.assertIsNone(note.read_at)

    def test_opening_marks_it_read_and_goes_to_the_right_place(self):
        self.send(self.ann, "Hi")
        note = Notification.objects.get(user=self.ben)
        response = self.client_for(self.ben).post(f"/notifications/{note.pk}/open/")
        self.assertRedirects(response, "/space/?chat=1", fetch_redirect_response=False)
        note.refresh_from_db()
        self.assertIsNotNone(note.read_at)

    def test_signed_out_visitors_get_nothing(self):
        self.assertEqual(Client().get("/api/notifications/").status_code, 403)
        self.assertEqual(Client().post("/api/push/subscribe/", {}, content_type="application/json").status_code,
                         403)

    def test_mark_all_read(self):
        self.send(self.ann, "Hi")
        self.client_for(self.ben).post("/notifications/read-all/")
        self.assertEqual(services.unread_count(self.ben), 0)

    def test_notifications_from_a_closed_space_are_not_shown(self):
        self.send(self.ann, "Hi")
        couples.close_couple(self.ann)
        self.assertEqual(services.unread_count(self.ben), 0)
        self.assertEqual(json.loads(self.client_for(self.ben).get("/api/notifications/").content)["items"], [])

    def test_the_space_page_lists_them(self):
        self.send(self.ann, "Hi")
        page = self.client_for(self.ben).get("/space/").content.decode()
        self.assertIn('id="notifications"', page)
        self.assertIn("Ann sent you a message", page)


class PushTests(NotificationSetup):
    def subscribe(self, user, endpoint="https://push.example/abc"):
        return self.client_for(user).post("/api/push/subscribe/", {
            "endpoint": endpoint, "keys": {"p256dh": "key", "auth": "secret"},
        }, content_type="application/json")

    def test_subscribing_stores_the_device_for_this_person(self):
        self.assertEqual(self.subscribe(self.ben).status_code, 201)
        self.assertEqual(PushSubscription.objects.get().user, self.ben)

    def test_a_device_moves_to_whoever_signs_in_on_it(self):
        self.subscribe(self.ann)
        self.subscribe(self.ben)
        self.assertEqual(list(PushSubscription.objects.values_list("user__email", flat=True)), ["ben@example.com"])

    def test_bad_subscriptions_are_refused(self):
        for body in [{}, {"endpoint": "http://insecure.example/x", "keys": {"p256dh": "k", "auth": "a"}},
                     {"endpoint": "https://push.example/x", "keys": {}}]:
            with self.subTest(body=body):
                response = self.client_for(self.ben).post("/api/push/subscribe/", body,
                                                          content_type="application/json")
                self.assertEqual(response.status_code, 400)

    def test_a_new_notification_pushes_once_with_no_names_or_content(self):
        self.subscribe(self.ben)
        self.send(self.ann, "The secret words")
        self.send(self.ann, "More secret words")
        self.assertEqual(self.webpush.call_count, 1)
        payload = self.webpush.call_args.kwargs["data"]
        self.assertIn("message", json.loads(payload)["body"])
        self.assertNotIn("secret", payload)
        self.assertNotIn("Ann", payload)

    def test_no_push_while_the_person_is_in_the_app(self):
        self.subscribe(self.ben)
        presence.join(self.ben.pk, "channel-1")
        self.send(self.ann, "Hi")
        self.webpush.assert_not_called()
        self.assertTrue(Notification.objects.filter(user=self.ben).exists())

    def test_gone_devices_are_forgotten(self):
        self.subscribe(self.ben)
        self.webpush.side_effect = push.WebPushException("gone", response=mock.Mock(status_code=410))
        self.send(self.ann, "Hi")
        self.assertFalse(PushSubscription.objects.exists())

    @override_settings(VAPID_PUBLIC_KEY="", VAPID_PRIVATE_KEY="")
    def test_without_keys_push_is_off_and_nothing_breaks(self):
        self.subscribe(self.ben)
        self.send(self.ann, "Hi")
        self.webpush.assert_not_called()
        self.assertTrue(Notification.objects.filter(user=self.ben).exists())

    def test_unsubscribing_removes_only_your_device(self):
        self.subscribe(self.ben, "https://push.example/ben")
        response = self.client_for(self.ann).post("/api/push/unsubscribe/", {"endpoint": "https://push.example/ben"},
                                                  content_type="application/json")
        self.assertEqual(response.status_code, 204)
        self.assertTrue(PushSubscription.objects.exists())
        self.client_for(self.ben).post("/api/push/unsubscribe/", {"endpoint": "https://push.example/ben"},
                                       content_type="application/json")
        self.assertFalse(PushSubscription.objects.exists())
