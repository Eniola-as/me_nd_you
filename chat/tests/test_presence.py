"""Presence ("Online", "In your space", "Playing <mode>", "Last seen ...")
and the typing indicator. Both go only to the partner; typing is never
stored, and last seen is one stored time per member."""

import importlib

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.test import Client, SimpleTestCase, TransactionTestCase, override_settings

import me_nd_you.asgi
from chat import presence
from chat.models import ChatMessage
from couples.models import Membership

from . import make_couple, with_chat_key

ORIGIN = b"https://me-nd-you.onrender.com"


def cookie_for(user):
    client = Client()
    client.force_login(user)
    return f"sessionid={client.cookies['sessionid'].value}".encode()


class RegistryTests(SimpleTestCase):
    def setUp(self):
        presence.reset()

    def test_online_while_any_connection_is_open_and_where_is_the_latest(self):
        self.assertEqual(presence.status(1), {"online": False, "where": None})
        presence.join(1, "phone")
        presence.update(1, "phone", "space")
        presence.join(1, "laptop")
        presence.update(1, "laptop", "play:truth")
        self.assertEqual(presence.status(1), {"online": True, "where": "play:truth"})
        self.assertFalse(presence.leave(1, "laptop"))  # The phone is still open.
        self.assertEqual(presence.status(1), {"online": True, "where": "space"})
        self.assertTrue(presence.leave(1, "phone"))  # That was the last one.
        self.assertEqual(presence.status(1), {"online": False, "where": None})

    def test_only_known_places_are_accepted(self):
        for where in ["space", "menu", "play:questions", "play:truth", "play:would"]:
            self.assertTrue(presence.valid_where(where), where)
        for where in ["", "play:", "play:nope", "kitchen", None, 5, "space " * 3]:
            self.assertFalse(presence.valid_where(where), where)


@with_chat_key
@override_settings(ALLOWED_HOSTS=["me-nd-you.onrender.com"])
class PresenceSocketTests(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        presence.reset()
        self.couple, (self.ann, self.ben) = make_couple("ann@example.com", "ben@example.com")
        self.cookies = {"ann": cookie_for(self.ann), "ben": cookie_for(self.ben)}

    def run_async(self, scenario):
        async def wrapper():
            return await scenario(importlib.reload(me_nd_you.asgi).application)
        return async_to_sync(wrapper)()

    async def open(self, app, who, where=None):
        page = WebsocketCommunicator(app, "/ws/chat/", headers=[(b"origin", ORIGIN), (b"cookie", self.cookies[who])])
        assert (await page.connect())[0]
        await page.receive_json_from(timeout=2)  # History.
        if where:
            await page.send_json_to({"type": "presence", "where": where})
        return page

    @staticmethod
    async def everything(page, timeout=1):
        messages = []
        while not await page.receive_nothing(timeout=timeout):
            messages.append(await page.receive_json_from(timeout=timeout))
        return messages

    @staticmethod
    def presences(messages):
        return [m["partner"] for m in messages if m["type"] == "presence"]

    def test_you_learn_where_your_partner_is_and_when_they_leave(self):
        async def scenario(app):
            a = await self.open(app, "ann", "space")
            first = await self.everything(a)  # Ben is offline.
            b = await self.open(app, "ben", "play:truth")
            ann_saw = await self.everything(a)
            ben_saw = await self.everything(b)
            await b.send_json_to({"type": "presence", "where": "menu"})
            moved = await self.everything(a)
            await b.disconnect()
            gone = await self.everything(a)
            await a.disconnect()
            return first, ann_saw, ben_saw, moved, gone

        first, ann_saw, ben_saw, moved, gone = self.run_async(scenario)
        self.assertEqual(self.presences(first)[-1], {"online": False, "where": None, "lastSeen": None})
        self.assertEqual(self.presences(ann_saw)[-1], {"online": True, "where": "play:truth", "lastSeen": None})
        self.assertEqual(self.presences(ben_saw)[-1]["where"], "space")
        self.assertEqual(self.presences(moved)[-1]["where"], "menu")
        offline = self.presences(gone)[-1]
        self.assertEqual((offline["online"], offline["where"]), (False, None))
        self.assertIsNotNone(offline["lastSeen"])
        stored = Membership.objects.get(user=self.ben).last_seen_at
        self.assertEqual(offline["lastSeen"], stored.isoformat())

    def test_you_stay_online_until_your_last_connection_closes(self):
        async def scenario(app):
            a = await self.open(app, "ann", "space")
            phone = await self.open(app, "ben", "space")
            laptop = await self.open(app, "ben", "play:questions")
            await self.everything(a)
            await laptop.disconnect()
            after_one = await self.everything(a)
            await phone.disconnect()
            after_both = await self.everything(a)
            await a.disconnect()
            return after_one, after_both

        after_one, after_both = self.run_async(scenario)
        self.assertEqual(self.presences(after_one)[-1]["online"], True)
        self.assertEqual(self.presences(after_both)[-1]["online"], False)

    def test_an_unknown_place_is_refused(self):
        async def scenario(app):
            a = await self.open(app, "ann")
            await a.send_json_to({"type": "presence", "where": "the moon"})
            got = await self.everything(a)
            await a.disconnect()
            return got

        self.assertEqual([m["reason"] for m in self.run_async(scenario) if m["type"] == "error"], ["invalid"])

    def test_typing_reaches_only_the_partner_and_is_never_stored(self):
        async def scenario(app):
            a, b = await self.open(app, "ann", "space"), await self.open(app, "ben", "space")
            await self.everything(a), await self.everything(b)
            await a.send_json_to({"type": "typing"})
            return await self.everything(a), await self.everything(b), a, b

        async def run(app):
            ann_got, ben_got, a, b = await scenario(app)
            await a.disconnect(); await b.disconnect()
            return ann_got, ben_got

        ann_got, ben_got = self.run_async(run)
        self.assertEqual(ben_got, [{"type": "typing"}])
        self.assertEqual(ann_got, [])
        self.assertFalse(ChatMessage.objects.exists())

    def test_a_member_who_left_gets_no_presence_or_typing_and_is_cut_off(self):
        async def scenario(app):
            a, b = await self.open(app, "ann", "space"), await self.open(app, "ben", "space")
            await self.everything(a), await self.everything(b)
            from asyncio import get_running_loop
            await get_running_loop().run_in_executor(
                None, lambda: Membership.objects.filter(user=self.ben).update(left_at="2026-10-28T00:00:00Z"))
            await a.send_json_to({"type": "typing"})
            ben_got = []
            while True:
                output = await b.receive_output(timeout=2)
                ben_got.append(output)
                if output["type"] == "websocket.close":
                    break
            await a.disconnect()
            return ben_got

        ben_got = self.run_async(scenario)
        texts = [o.get("text", "") for o in ben_got]
        self.assertFalse(any('"typing"' in t for t in texts))
        self.assertIn('"forbidden"', texts[-2])
        self.assertEqual(ben_got[-1]["type"], "websocket.close")
