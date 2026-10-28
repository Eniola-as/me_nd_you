"""Consent is enforced everywhere, not only on page loads: the game and chat
sockets refuse to connect AND refuse every action from a user missing a
required consent (closing the socket, like a lost membership), including
after the policy version changes under an open socket. The automatic
consents for test users exist only under the test runner."""

import importlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase, override_settings

import me_nd_you.asgi
from accounts.consents import CONSENT_KINDS, record_consents
from accounts.models import Consent
from accounts.testing import without_auto_consent
from chat.models import ChatMessage
from chat.tests import with_chat_key
from couples import services as couples
from game.tests.utils import SETTINGS_ENV_KEYS
from play.models import GameRoom

PASSWORD = "a-long-passphrase-1"
ORIGIN = b"https://me-nd-you.onrender.com"
GAME = "/ws/room/questions/questions/"
CHAT = "/ws/chat/"


def cookie_for(user):
    client = Client()
    client.force_login(user)
    return f"sessionid={client.cookies['sessionid'].value}".encode()


def game_action(version):
    return {"type": "action", "action": "next", "expectedVersion": version, "requestId": str(uuid.uuid4())}


def chat_message(text):
    return {"type": "send", "text": text, "requestId": str(uuid.uuid4())}


@with_chat_key
@override_settings(ALLOWED_HOSTS=["me-nd-you.onrender.com"])
class OpenSocketConsentTests(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        self.ann = get_user_model().objects.create_user(email="ann@example.com", password=PASSWORD)
        couples.create_couple(self.ann)  # Ann has the current consents (test runner).
        self.cookie = cookie_for(self.ann)

    def run_async(self, scenario):
        async def wrapper():
            return await scenario(importlib.reload(me_nd_you.asgi).application)
        return async_to_sync(wrapper)()

    async def connect(self, app, path):
        page = WebsocketCommunicator(app, path, headers=[(b"origin", ORIGIN), (b"cookie", self.cookie)])
        connected, _ = await page.connect()
        assert connected, path
        first = await page.receive_json_from(timeout=2)
        while not await page.receive_nothing(timeout=0.3):  # Let the connection settle.
            await page.receive_output(timeout=1)
        return page, first

    @staticmethod
    async def until_closed(page):
        """Every message (but presence and typing) up to the close."""
        frames = []
        while True:
            output = await page.receive_output(timeout=2)
            if output["type"] != "websocket.send":
                return frames, output["type"]
            data = json.loads(output["text"])
            if data["type"] not in ("presence", "typing"):
                frames.append(data)

    @staticmethod
    async def in_thread(function, *args):
        import asyncio

        return await asyncio.get_running_loop().run_in_executor(None, function, *args)

    def test_a_game_action_without_consent_is_refused_and_the_socket_closes(self):
        async def scenario(app):
            page, state = await self.connect(app, GAME)
            await self.in_thread(lambda: Consent.objects.filter(user=self.ann).delete())
            await page.send_json_to(game_action(state["version"]))
            return state, await self.until_closed(page)

        state, (frames, ending) = self.run_async(scenario)
        self.assertEqual([f.get("reason") for f in frames], ["forbidden"])
        self.assertEqual(ending, "websocket.close")
        self.assertEqual(GameRoom.objects.get().version, state["version"])  # Nothing happened.

    def test_a_chat_message_without_consent_is_refused_and_the_socket_closes(self):
        async def scenario(app):
            page, _ = await self.connect(app, CHAT)
            await self.in_thread(lambda: Consent.objects.filter(user=self.ann).delete())
            await page.send_json_to(chat_message("Can I still send?"))
            return await self.until_closed(page)

        frames, ending = self.run_async(scenario)
        self.assertEqual([f.get("reason") for f in frames], ["forbidden"])
        self.assertEqual(ending, "websocket.close")
        self.assertFalse(ChatMessage.objects.exists())

    def test_a_new_policy_version_refuses_open_sockets_until_accepted(self):
        async def scenario(app):
            game, state = await self.connect(app, GAME)
            chat, _ = await self.connect(app, CHAT)
            with override_settings(POLICY_VERSION="2027-01-01"):
                await game.send_json_to(game_action(state["version"]))
                await chat.send_json_to(chat_message("After the change"))
                results = [await self.until_closed(game), await self.until_closed(chat)]
                # Accepting the new version lets them back in.
                await self.in_thread(record_consents, self.ann, CONSENT_KINDS)
                again = WebsocketCommunicator(app, GAME, headers=[(b"origin", ORIGIN), (b"cookie", self.cookie)])
                reconnected, _ = await again.connect()
                await again.disconnect()
            return results, reconnected

        results, reconnected = self.run_async(scenario)
        for frames, ending in results:
            self.assertEqual([f.get("reason") for f in frames], ["forbidden"])
            self.assertEqual(ending, "websocket.close")
        self.assertFalse(ChatMessage.objects.exists())
        self.assertTrue(reconnected)


@with_chat_key
@override_settings(ALLOWED_HOSTS=["me-nd-you.onrender.com", "testserver"])
class RealUserWithoutConsentTests(TransactionTestCase):
    serialized_rollback = True

    def test_a_user_with_no_consent_records_is_blocked_from_pages_and_sockets(self):
        # Created the way the app creates users outside sign-up (no runner help).
        with without_auto_consent():
            ann = get_user_model().objects.create_user(email="ann@example.com", password=PASSWORD)
        couples.create_couple(ann)
        self.assertEqual(Consent.objects.filter(user=ann).count(), 0)
        client = Client()
        client.force_login(ann)
        for page in ["/space/", "/modes/", "/play/?mode=questions", "/accounts/profile/"]:
            response = client.get(page)
            self.assertEqual(response.status_code, 302, page)
            self.assertTrue(response["Location"].startswith("/accounts/consent/"), page)
        api = client.post("/api/space/custom-questions/", {"mode": "questions", "text": "Hi?"},
                          content_type="application/json")
        self.assertEqual(api.status_code, 403)
        cookie = f"sessionid={client.cookies['sessionid'].value}".encode()

        async def scenario():
            app = importlib.reload(me_nd_you.asgi).application
            refused = {}
            for path in [GAME, CHAT]:
                page = WebsocketCommunicator(app, path, headers=[(b"origin", ORIGIN), (b"cookie", cookie)])
                refused[path] = not (await page.connect())[0]
                await page.disconnect()
            return refused

        self.assertEqual(async_to_sync(scenario)(), {GAME: True, CHAT: True})


class AutoConsentIsTestOnlyTests(SimpleTestCase):
    """accounts/testing.py gives test users consents. Only the test runner
    (TEST_RUNNER, used by `manage.py test` alone) switches it on."""

    SCRIPT = (
        "import os, django; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'me_nd_you.settings'); "
        "django.setup(); import me_nd_you.urls, me_nd_you.asgi; {extra}"
        "from django.contrib.auth import get_user_model; from django.db.models.signals import post_save; "
        "print(post_save.disconnect(sender=get_user_model(), dispatch_uid='accounts.testing.auto_consent'))"
    )

    def connected_in_fresh_process(self, extra=""):
        env = {k: v for k, v in os.environ.items() if k not in SETTINGS_ENV_KEYS}
        env.update({"SECRET_KEY": "test-key", "DEBUG": "True"})
        return subprocess.run(
            [sys.executable, "-c", self.SCRIPT.format(extra=extra)], cwd=settings.BASE_DIR, env=env,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    def test_the_app_never_gives_automatic_consents(self):
        # The full app loaded (URLs, ASGI) as a server would: not connected.
        self.assertEqual(self.connected_in_fresh_process(), "False")

    def test_the_check_above_would_see_it_if_it_were_on(self):
        extra = "from accounts.testing import ConsentingTestRunner; ConsentingTestRunner().setup_test_environment(); "
        self.assertEqual(self.connected_in_fresh_process(extra), "True")

    def test_only_settings_name_the_test_runner(self):
        roots = [Path(settings.BASE_DIR) / d for d in ["accounts", "couples", "game", "play", "chat", "me_nd_you"]]
        users = sorted(
            str(p.relative_to(settings.BASE_DIR)) for root in roots for p in root.rglob("*.py")
            if "accounts.testing" in p.read_text(encoding="utf-8") or "from .testing" in p.read_text(encoding="utf-8")
            if not (p.name.startswith("test") or "tests" in p.parts)
        )
        self.assertEqual(users, [str(Path("me_nd_you/settings.py"))])
