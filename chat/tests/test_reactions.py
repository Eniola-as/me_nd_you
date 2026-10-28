"""Reactions on chat messages: exactly one emoji, one per person per
message, changeable or removable; only the couple's members can react."""

import importlib
from unittest import mock

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

import me_nd_you.asgi
from chat import presence, services
from chat.models import ChatMessage, ChatReaction

from . import make_couple, with_chat_key


@with_chat_key
class ReactionServiceTests(TestCase):
    def setUp(self):
        self.couple, (self.ann, self.ben) = make_couple("ann@example.com", "ben@example.com")
        self.message = services.send(self.ann, self.couple.pk, "Hi Ben", None)

    def react(self, user, emoji, message=None):
        return services.react(user, self.couple.pk, (message or self.message).pk, emoji)

    def shown(self, user):
        return services.serialize(ChatMessage.objects.get(pk=self.message.pk), user)["reactions"]

    def test_both_can_react_and_each_sees_whose_is_whose(self):
        self.react(self.ben, "❤️")
        self.react(self.ann, "😂")
        self.assertEqual(self.shown(self.ann), {"mine": "😂", "partner": "❤️"})
        self.assertEqual(self.shown(self.ben), {"mine": "❤️", "partner": "😂"})

    def test_one_reaction_per_person_changeable_and_removable(self):
        self.react(self.ben, "❤️")
        self.react(self.ben, "🔥")
        self.assertEqual(ChatReaction.objects.count(), 1)
        self.assertEqual(self.shown(self.ann), {"mine": None, "partner": "🔥"})
        self.react(self.ben, None)
        self.assertEqual(self.shown(self.ann), {"mine": None, "partner": None})
        self.assertFalse(ChatReaction.objects.exists())

    def test_any_single_emoji_from_the_keyboard_works(self):
        self.react(self.ben, "👩‍❤️‍👨")
        self.assertEqual(self.shown(self.ann)["partner"], "👩‍❤️‍👨")

    def test_anything_but_one_emoji_is_refused(self):
        for bad in ["a", "😂😂", "", "\U0001F3FD", 5]:
            with self.subTest(bad), self.assertRaises(services.Invalid):
                self.react(self.ben, bad)
        self.assertFalse(ChatReaction.objects.exists())

    def test_only_this_couples_messages(self):
        other, (cy, _) = make_couple("cy@example.com", "dee@example.com")
        theirs = services.send(cy, other.pk, "Theirs", None)
        for message_id in [theirs.pk, 999999, "x"]:
            with self.subTest(message_id), self.assertRaises(services.Invalid):
                services.react(self.ben, self.couple.pk, message_id, "❤️")
        with self.assertRaises(services.Forbidden):
            services.react(cy, self.couple.pk, self.message.pk, "❤️")

    def test_the_couple_is_told_after_commit(self):
        with mock.patch("chat.services.notify_couple") as notify, self.captureOnCommitCallbacks(execute=True):
            self.react(self.ben, "❤️")
        notify.assert_called_once_with(self.couple.pk, {"type": "chat.reaction", "id": self.message.pk})

    def test_deleting_a_message_deletes_its_reactions(self):
        self.react(self.ben, "❤️")
        services.delete(self.ann, self.couple.pk, self.message.pk)
        self.assertFalse(ChatReaction.objects.exists())

    def test_history_loads_reactions_without_a_query_per_message(self):
        for n in range(30):
            # Created directly: sending 30 more would hit the per-minute limit.
            message = ChatMessage.objects.create(couple=self.couple, author=self.ann,
                                                 body=services.crypto.encrypt(f"m{n}"))
            services.react(self.ben, self.couple.pk, message.pk, "👍")
        with CaptureQueriesContext(connection) as queries:
            page = services.history(self.ann, self.couple.pk)
        self.assertEqual(page["messages"][-1]["reactions"], {"mine": None, "partner": "👍"})
        self.assertLess(len(queries), 10)


@with_chat_key
@override_settings(ALLOWED_HOSTS=["me-nd-you.onrender.com"])
class ReactionSocketTests(TransactionTestCase):
    serialized_rollback = True

    def test_a_reaction_reaches_both_as_each_should_see_it(self):
        presence.reset()
        couple, (ann, ben) = make_couple("ann@example.com", "ben@example.com")
        message = services.send(ann, couple.pk, "Hi", None)
        cookies = []
        for user in (ann, ben):
            client = Client()
            client.force_login(user)
            cookies.append(f"sessionid={client.cookies['sessionid'].value}".encode())

        async def scenario():
            app = importlib.reload(me_nd_you.asgi).application
            pages = []
            for cookie in cookies:
                page = WebsocketCommunicator(app, "/ws/chat/", headers=[
                    (b"origin", b"https://me-nd-you.onrender.com"), (b"cookie", cookie)])
                assert (await page.connect())[0]
                pages.append(page)
            for page in pages:
                while not await page.receive_nothing(timeout=0.5):
                    await page.receive_json_from()
            a, b = pages
            await b.send_json_to({"type": "react", "id": message.pk, "emoji": "🔥"})
            got = []
            for page in (a, b):
                frames = []
                while not await page.receive_nothing(timeout=0.5):
                    frame = await page.receive_json_from()
                    if frame["type"] == "message":
                        frames.append(frame["message"]["reactions"])
                got.append(frames)
                await page.disconnect()
            return got

        ann_got, ben_got = async_to_sync(scenario)()
        self.assertEqual(ann_got, [{"mine": None, "partner": "🔥"}])
        self.assertEqual(ben_got, [{"mine": "🔥", "partner": None}])

    def test_a_refused_reaction_names_its_request_so_the_page_can_undo_it(self):
        presence.reset()
        couple, (ann, _) = make_couple("ann@example.com", "ben@example.com")
        message = services.send(ann, couple.pk, "Hi", None)
        client = Client()
        client.force_login(ann)
        cookie = f"sessionid={client.cookies['sessionid'].value}".encode()

        async def scenario():
            app = importlib.reload(me_nd_you.asgi).application
            page = WebsocketCommunicator(app, "/ws/chat/", headers=[
                (b"origin", b"https://me-nd-you.onrender.com"), (b"cookie", cookie)])
            assert (await page.connect())[0]
            while not await page.receive_nothing(timeout=0.5):
                await page.receive_json_from()
            await page.send_json_to({"type": "react", "id": message.pk, "emoji": "ab", "requestId": "tap-1"})
            frames = []
            while not await page.receive_nothing(timeout=0.5):
                frames.append(await page.receive_json_from())
            await page.disconnect()
            return frames

        errors = [f for f in async_to_sync(scenario)() if f["type"] == "error"]
        self.assertEqual([(e["reason"], e["requestId"], e["detail"]) for e in errors],
                         [("invalid", "tap-1", "Pick a single emoji.")])
