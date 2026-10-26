import importlib
import re
from datetime import timedelta
from urllib.parse import quote

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone

import me_nd_you.asgi
from game.consumers import room_group_name
from game.models import CoupleSession

PATH = "/ws/game/room/questions/"


def couple_secrets():
    """Every secret the WebSocket tests connect with. A real couple can't
    have a secret over 100 characters, so longer ones are naming-only."""
    fixed = ["room", "other-couple", "love_truth", "love"]
    return fixed + [s for s in SPECIAL_SECRETS.values() if len(s) <= 100 and s not in fixed]


class CoupleRoomsTestCase(TransactionTestCase):
    """Rooms only open for an existing, unexpired couple session.

    TransactionTestCase, not TestCase: the consumer reads the database
    through database_sync_to_async, which closes connections that are
    inside a transaction. SQLite's in-memory test database ignores that
    close; PostgreSQL doesn't, so TestCase only worked on SQLite.
    """

    serialized_rollback = True  # Restore the question bank for later tests.

    def setUp(self):
        for n, secret in enumerate(couple_secrets()):
            CoupleSession.objects.create(
                partner1_name=f"Partner{n}a", partner2_name=f"Partner{n}b", secret_word=secret
            )


async def connect(origin):
    # The origin validator reads ALLOWED_HOSTS when asgi.py is imported, so
    # rebuild the app inside each test's override_settings.
    application = importlib.reload(me_nd_you.asgi).application
    communicator = WebsocketCommunicator(application, PATH, headers=[(b"origin", origin)])
    connected, _ = await communicator.connect()
    return communicator, connected


@override_settings(ALLOWED_HOSTS=["me-nd-you.onrender.com"])
class WebSocketOriginTests(CoupleRoomsTestCase):
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
class WebSocketMessageSizeTests(CoupleRoomsTestCase):
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
class MessageContractTests(CoupleRoomsTestCase):
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
class MalformedMessageTests(CoupleRoomsTestCase):
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


# Channels' own rule for group names (channels/layers.py).
GROUP_NAME_RE = re.compile(r"^[a-zA-Z\d\-_.]+$")
GROUP_NAME_MAX = 100  # Names must be shorter than this.

SPECIAL_SECRETS = {
    "plain": "sunflower",
    "space": "our song",
    "hash": "us#1",
    "ampersand": "you&me",
    "punctuation": "love? yes! (always) 100% <3 ;-)",
    "accent": "José & Zoë",
    "emoji": "us two 💕🌙",
    "100 characters": "s" * 100,
    "1,000 characters": "long secret " * 84,
}


class RoomGroupNameTests(SimpleTestCase):
    def test_names_are_always_valid_channels_group_names(self):
        for label, secret in SPECIAL_SECRETS.items():
            for mode in ["questions", "truth", "weird mode #&é💕", "m" * 300]:
                with self.subTest(secret=label, mode=mode[:20]):
                    name = room_group_name(secret, mode)
                    self.assertRegex(name, GROUP_NAME_RE)
                    self.assertLess(len(name), GROUP_NAME_MAX)

    def test_same_secret_and_mode_always_give_the_same_name(self):
        self.assertEqual(room_group_name("our song", "truth"), room_group_name("our song", "truth"))

    def test_different_secrets_give_different_names(self):
        names = {room_group_name(secret, "questions") for secret in SPECIAL_SECRETS.values()}
        self.assertEqual(len(names), len(SPECIAL_SECRETS))

    def test_same_secret_in_different_modes_gives_different_names(self):
        modes = ["questions", "truth", "challenge", "spicy", "mixed", "would"]
        self.assertEqual(len({room_group_name("sunflower", m) for m in modes}), len(modes))

    def test_secret_and_mode_cannot_be_shifted_into_each_other(self):
        # The old "game_{secret}_{mode}" naming put these two in one room.
        self.assertNotEqual(
            room_group_name("love_truth", "questions"), room_group_name("love", "truth_questions")
        )

    def test_name_never_contains_the_raw_secret(self):
        for secret in ["sunflower", "lovebirds", "s" * 100]:
            with self.subTest(secret=secret[:20]):
                self.assertNotIn(secret, room_group_name(secret, "questions"))

    def test_name_is_keyed_by_the_server_secret_key(self):
        with override_settings(SECRET_KEY="one-test-key"):
            first = room_group_name("sunflower", "questions")
        with override_settings(SECRET_KEY="another-test-key"):
            second = room_group_name("sunflower", "questions")
        self.assertNotEqual(first, second)


def encoded_path(secret, mode="questions"):
    """The path the page builds with encodeURIComponent."""
    return f"/ws/game/{quote(secret, safe='')}/{quote(mode, safe='')}/"


@override_settings(ALLOWED_HOSTS=["me-nd-you.onrender.com"])
class RoomIsolationTests(CoupleRoomsTestCase):
    def exchange(self, sender_path, receiver_path):
        """Send a question on one path; return what the other path receives."""

        async def run():
            application = importlib.reload(me_nd_you.asgi).application
            sender = WebsocketCommunicator(application, sender_path, headers=[(b"origin", ORIGIN)])
            receiver = WebsocketCommunicator(application, receiver_path, headers=[(b"origin", ORIGIN)])
            assert (await sender.connect())[0] and (await receiver.connect())[0]
            await sender.send_json_to({"type": "question", "userId": "s", "question": "Private?"})
            try:
                received = await receiver.receive_json_from(timeout=0.5)
            except Exception:
                received = None
            await close(sender, receiver)
            return received

        return async_to_sync(run)()

    def test_partners_with_special_secrets_can_play_together(self):
        for label, secret in SPECIAL_SECRETS.items():
            if len(secret) > 100:
                continue  # No real couple can have it; covered by naming tests.
            with self.subTest(secret=label):
                path = encoded_path(secret)
                self.assertEqual(self.exchange(path, path)["question"], "Private?")

    def test_crafted_mode_cannot_eavesdrop_on_another_couple(self):
        victim = encoded_path("love_truth", "questions")
        eavesdropper = encoded_path("love", "truth_questions")
        self.assertIsNone(self.exchange(victim, eavesdropper))

    def test_same_secret_in_another_mode_is_a_separate_room(self):
        self.assertIsNone(self.exchange(encoded_path("sunflower", "questions"),
                                        encoded_path("sunflower", "truth")))


async def try_connect(path):
    application = importlib.reload(me_nd_you.asgi).application
    page = WebsocketCommunicator(application, path, headers=[(b"origin", ORIGIN)])
    connected, code = await page.connect()
    if connected:
        await page.disconnect()
    return connected, code


@override_settings(ALLOWED_HOSTS=["me-nd-you.onrender.com"])
class SessionAccessTests(CoupleRoomsTestCase):
    """Audit A6: only an existing, unexpired session may open a room."""

    def connect(self, secret):
        return async_to_sync(try_connect)(encoded_path(secret))

    def test_unknown_secret_cannot_open_a_room(self):
        self.assertFalse(self.connect("nobody-has-this-secret")[0])

    def test_expired_session_cannot_open_a_room(self):
        CoupleSession.objects.filter(secret_word="room").update(
            last_active=timezone.now() - timedelta(days=31)
        )
        self.assertFalse(self.connect("room")[0])

    def test_expired_and_unknown_are_rejected_identically(self):
        CoupleSession.objects.filter(secret_word="room").update(
            last_active=timezone.now() - timedelta(days=31)
        )
        self.assertEqual(self.connect("room"), self.connect("nobody-has-this-secret"))

    def test_connecting_counts_as_activity(self):
        CoupleSession.objects.filter(secret_word="room").update(
            last_active=timezone.now() - timedelta(days=10)
        )
        self.assertTrue(self.connect("room")[0])
        last_active = CoupleSession.objects.get(secret_word="room").last_active
        self.assertLess(timezone.now() - last_active, timedelta(minutes=1))
