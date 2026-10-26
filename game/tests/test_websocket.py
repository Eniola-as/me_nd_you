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
