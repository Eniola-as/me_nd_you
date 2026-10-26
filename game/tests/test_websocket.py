import importlib

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.test import SimpleTestCase, override_settings

import me_nd_you.asgi

PATH = "/ws/game/room/questions/"


async def connect(origin):
    # The origin validator reads ALLOWED_HOSTS when asgi.py is imported, so
    # rebuild the app inside each test's override_settings.
    application = importlib.reload(me_nd_you.asgi).application
    communicator = WebsocketCommunicator(application, PATH, headers=[(b"origin", origin)])
    connected, _ = await communicator.connect()
    return communicator, connected


@override_settings(ALLOWED_HOSTS=["me-nd-you.onrender.com"])
class WebSocketOriginTests(SimpleTestCase):
    def test_same_site_origin_can_connect(self):
        async def run():
            communicator, connected = await connect(b"https://me-nd-you.onrender.com")
            await communicator.disconnect()
            return connected

        self.assertTrue(async_to_sync(run)())

    def test_other_site_origin_is_rejected(self):
        async def run():
            communicator, connected = await connect(b"https://evil.example")
            await communicator.disconnect()
            return connected

        self.assertFalse(async_to_sync(run)())


@override_settings(ALLOWED_HOSTS=["me-nd-you.onrender.com"])
class WebSocketMessageSizeTests(SimpleTestCase):
    def test_oversized_message_closes_the_connection(self):
        async def run():
            communicator, _ = await connect(b"https://me-nd-you.onrender.com")
            await communicator.send_to(text_data="x" * 20_000)
            output = await communicator.receive_output(timeout=1)
            await communicator.disconnect()
            return output

        output = async_to_sync(run)()
        self.assertEqual(output["type"], "websocket.close")
        self.assertEqual(output["code"], 1009)


ORIGIN = b"https://me-nd-you.onrender.com"


async def partners(path=PATH):
    """Two pages for the same couple and mode, connected to one room."""
    application = importlib.reload(me_nd_you.asgi).application
    pages = []
    for _ in range(2):
        page = WebsocketCommunicator(application, path, headers=[(b"origin", ORIGIN)])
        connected, _ = await page.connect()
        assert connected
        pages.append(page)
    return pages


async def close(*pages):
    for page in pages:
        await page.disconnect()


@override_settings(ALLOWED_HOSTS=["me-nd-you.onrender.com"])
class MessageContractTests(SimpleTestCase):
    def relay(self, message):
        """Send from page A; return what page B receives."""

        async def run():
            a, b = await partners()
            await a.send_json_to(message)
            received = await b.receive_json_from(timeout=1)
            await close(a, b)
            return received

        return async_to_sync(run)()

    def test_question_reaches_the_partner(self):
        message = {"type": "question", "userId": "page-a", "question": "What made you smile?"}
        self.assertEqual(self.relay(message), message)

    def test_reset_reaches_the_partner(self):
        message = {"type": "reset", "userId": "page-a", "seed": 42}
        self.assertEqual(self.relay(message), message)

    def test_sync_request_reaches_the_partner(self):
        message = {"type": "sync_request", "userId": "page-a"}
        self.assertEqual(self.relay(message), message)

    def test_sync_response_reaches_the_partner(self):
        message = {
            "type": "sync_response", "userId": "page-a", "seed": 42, "currentQuestion": "Q?",
        }
        self.assertEqual(self.relay(message), message)

    def test_sync_response_may_have_no_current_question(self):
        message = {"type": "sync_response", "userId": "page-a", "seed": None, "currentQuestion": None}
        self.assertEqual(self.relay(message), message)

    def test_relayed_messages_drop_unexpected_fields(self):
        received = self.relay({
            "type": "sync_response", "userId": "page-a", "seed": 1, "currentQuestion": "Q?",
            "seenTexts": ["a"] * 10, "html": "<script>",
        })
        self.assertEqual(set(received), {"type", "userId", "seed", "currentQuestion"})

    def test_rooms_for_different_couples_are_isolated(self):
        async def run():
            application = importlib.reload(me_nd_you.asgi).application
            ours = WebsocketCommunicator(application, PATH, headers=[(b"origin", ORIGIN)])
            theirs = WebsocketCommunicator(
                application, "/ws/game/other-couple/questions/", headers=[(b"origin", ORIGIN)]
            )
            await ours.connect()
            await theirs.connect()
            await ours.send_json_to({"type": "question", "userId": "a", "question": "Ours?"})
            nothing = await theirs.receive_nothing(timeout=0.5)
            await close(ours, theirs)
            return nothing

        self.assertTrue(async_to_sync(run)())


@override_settings(ALLOWED_HOSTS=["me-nd-you.onrender.com"])
class MalformedMessageTests(SimpleTestCase):
    MALFORMED = {
        "not JSON": "hello",
        "JSON array": "[1, 2]",
        "JSON string": '"question"',
        "unknown type": '{"type": "dance", "userId": "a"}',
        "missing type": '{"userId": "a", "questions": ["Old shape?"]}',
        "missing userId": '{"type": "question", "question": "Q?"}',
        "empty userId": '{"type": "question", "userId": "", "question": "Q?"}',
        "long userId": '{"type": "sync_request", "userId": "%s"}' % ("u" * 65),
        "question not text": '{"type": "question", "userId": "a", "question": 5}',
        "empty question": '{"type": "question", "userId": "a", "question": ""}',
        "question too long": '{"type": "question", "userId": "a", "question": "%s"}' % ("q" * 501),
        "reset seed not integer": '{"type": "reset", "userId": "a", "seed": "42"}',
        "reset seed boolean": '{"type": "reset", "userId": "a", "seed": true}',
        "reset without seed": '{"type": "reset", "userId": "a"}',
        "sync currentQuestion not text": '{"type": "sync_response", "userId": "a", "seed": 1, "currentQuestion": 7}',
    }

    def test_sender_gets_an_error_and_the_partner_gets_nothing(self):
        for label, raw in self.MALFORMED.items():
            with self.subTest(label):

                async def run():
                    a, b = await partners()
                    await a.send_to(text_data=raw)
                    error = await a.receive_json_from(timeout=1)
                    partner_heard_nothing = await b.receive_nothing(timeout=0.3)
                    await close(a, b)
                    return error, partner_heard_nothing

                error, partner_heard_nothing = async_to_sync(run)()
                self.assertEqual(error, {"type": "error", "reason": "invalid_message"})
                self.assertTrue(partner_heard_nothing)

    def test_connection_keeps_working_after_a_malformed_message(self):
        async def run():
            a, b = await partners()
            await a.send_to(text_data="hello")
            await a.receive_json_from(timeout=1)  # The error.
            message = {"type": "question", "userId": "a", "question": "Still there?"}
            await a.send_json_to(message)
            received = await b.receive_json_from(timeout=1)
            await close(a, b)
            return received

        self.assertEqual(async_to_sync(run)()["question"], "Still there?")
