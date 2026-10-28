"""Without CHAT_ENCRYPTION_KEYS (a local setup that skipped it), chat fails
gracefully everywhere: placeholders for messages, a clear "unavailable"
for sending, a clear error from the rotate command; never a traceback."""

import importlib

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, TransactionTestCase, override_settings

import me_nd_you.asgi
from chat import crypto, presence, services
from chat.models import ChatMessage

from . import make_couple, with_chat_key

NO_KEY = override_settings(CHAT_ENCRYPTION_KEYS=[])


class MissingKeyServiceTests(TestCase):
    def setUp(self):
        self.couple, (self.ann, self.ben) = make_couple("ann@example.com", "ben@example.com")
        with with_chat_key:
            services.send(self.ann, self.couple.pk, "Written while a key was set", None)

    @NO_KEY
    def test_history_shows_placeholders(self):
        message, = services.history(self.ben, self.couple.pk)["messages"]
        self.assertEqual((message["text"], message["unreadable"]), (crypto.UNREADABLE, True))

    @NO_KEY
    def test_sending_is_refused_with_a_clear_error(self):
        with self.assertRaises(crypto.ChatKeyMissing):
            services.send(self.ann, self.couple.pk, "Hi", None)

    @NO_KEY
    def test_the_rotate_command_stops_with_a_clear_message(self):
        with self.assertRaisesMessage(CommandError, "CHAT_ENCRYPTION_KEYS is not set"):
            call_command("rotate_chat_keys")
        self.assertTrue(ChatMessage.objects.get().body.startswith("gAAAA"))  # Untouched.


@override_settings(ALLOWED_HOSTS=["me-nd-you.onrender.com"], CHAT_ENCRYPTION_KEYS=[])
class MissingKeySocketTests(TransactionTestCase):
    serialized_rollback = True

    def test_connecting_with_old_messages_works_and_sending_says_unavailable(self):
        presence.reset()
        couple, (ann, _) = make_couple("ann@example.com", "ben@example.com")
        with with_chat_key:
            services.send(ann, couple.pk, "Old", None)
        client = Client()
        client.force_login(ann)
        cookie = f"sessionid={client.cookies['sessionid'].value}".encode()

        async def scenario():
            app = importlib.reload(me_nd_you.asgi).application
            page = WebsocketCommunicator(app, "/ws/chat/", headers=[
                (b"origin", b"https://me-nd-you.onrender.com"), (b"cookie", cookie)])
            connected, _ = await page.connect()
            history = await page.receive_json_from(timeout=2)
            await page.send_json_to({"type": "send", "text": "Hi", "requestId": None})
            frames = []
            while not await page.receive_nothing(timeout=0.5):
                frames.append(await page.receive_json_from())
            await page.disconnect()
            return connected, history, frames

        connected, history, frames = async_to_sync(scenario)()
        self.assertTrue(connected)
        self.assertEqual(history["messages"][0]["text"], crypto.UNREADABLE)
        errors = [f for f in frames if f["type"] == "error"]
        self.assertEqual([e["reason"] for e in errors], ["unavailable"])
        self.assertIn("isn't set up", errors[0]["detail"])
