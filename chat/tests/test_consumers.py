"""The chat socket: history on connect, live messages to both members,
membership re-checked on every message, and cut off at once when the
couple closes or a password is reset."""

import asyncio
import importlib
import uuid

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.test import Client, TransactionTestCase, override_settings

import me_nd_you.asgi
from accounts.sessions import sign_out_everywhere
from chat import services
from couples import services as couples
from couples.models import Membership

from . import make_couple, with_chat_key

ORIGIN = b"https://me-nd-you.onrender.com"
PATH = "/ws/chat/"


def cookie_for(user):
    client = Client()
    client.force_login(user)
    return f"sessionid={client.cookies['sessionid'].value}".encode()


def send(text, request_id=None):
    return {"type": "send", "text": text, "requestId": request_id or str(uuid.uuid4())}


@with_chat_key
@override_settings(ALLOWED_HOSTS=["me-nd-you.onrender.com"])
class ChatSocketTests(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        self.couple, (self.ann, self.ben) = make_couple("ann@example.com", "ben@example.com")
        self.cookies = {"ann": cookie_for(self.ann), "ben": cookie_for(self.ben)}

    def run_async(self, scenario):
        async def wrapper():
            return await scenario(importlib.reload(me_nd_you.asgi).application)
        return async_to_sync(wrapper)()

    @staticmethod
    def page(app, cookie=None):
        headers = [(b"origin", ORIGIN)] + ([(b"cookie", cookie)] if cookie else [])
        return WebsocketCommunicator(app, PATH, headers=headers)

    async def open(self, app, who):
        page = self.page(app, self.cookies[who])
        connected, _ = await page.connect()
        assert connected, who
        return page, await page.receive_json_from(timeout=2)

    @staticmethod
    async def everything(page, timeout=1):
        messages = []
        while not await page.receive_nothing(timeout=timeout):
            messages.append(await page.receive_json_from(timeout=timeout))
        return messages

    def test_connecting_sends_the_recent_history(self):
        services.send(self.ann, self.couple.pk, "Earlier", None)

        async def scenario(app):
            page, first = await self.open(app, "ben")
            await page.disconnect()
            return first

        first = self.run_async(scenario)
        self.assertEqual(first["type"], "history")
        self.assertEqual([m["text"] for m in first["messages"]], ["Earlier"])
        self.assertFalse(first["has_more"])

    def test_a_message_reaches_both_and_the_author_can_match_it(self):
        async def scenario(app):
            (a, _), (b, _) = await self.open(app, "ann"), await self.open(app, "ben")
            await a.send_json_to(send("Hello Ben", "11111111-1111-4111-8111-111111111111"))
            got_a, got_b = await self.everything(a), await self.everything(b)
            await a.disconnect(); await b.disconnect()
            return got_a, got_b

        got_a, got_b = self.run_async(scenario)
        (mine,), (theirs,) = got_a, got_b
        self.assertEqual((mine["type"], mine["message"]["text"], mine["message"]["mine"]), ("message", "Hello Ben", True))
        self.assertEqual(mine["message"]["requestId"], "11111111-1111-4111-8111-111111111111")
        self.assertEqual((theirs["message"]["text"], theirs["message"]["mine"]), ("Hello Ben", False))
        self.assertNotIn("requestId", theirs["message"])

    def test_signed_out_visitors_and_people_without_a_couple_cannot_connect(self):
        loner = type(self.ann).objects.create_user(email="dee@example.com", password="a-long-passphrase-1")
        loner_cookie = cookie_for(loner)

        async def scenario(app):
            results = []
            for cookie in [None, loner_cookie]:
                page = self.page(app, cookie)
                connected, _ = await page.connect()
                results.append(connected)
            return results

        self.assertEqual(self.run_async(scenario), [False, False])

    def test_another_couple_never_receives_this_couples_messages(self):
        _, (cy,) = make_couple("cy@example.com")
        services.send(self.ann, self.couple.pk, "Before", None)
        cy_cookie = cookie_for(cy)

        async def scenario(app):
            other = self.page(app, cy_cookie)
            assert (await other.connect())[0]
            first = await other.receive_json_from(timeout=2)
            a, _ = await self.open(app, "ann")
            await a.send_json_to(send("Only for Ben"))
            got = await self.everything(other)
            await a.disconnect(); await other.disconnect()
            return first, got

        first, got = self.run_async(scenario)
        self.assertEqual(first["messages"], [])
        self.assertEqual(got, [])

    def test_errors_go_to_the_sender_only(self):
        async def scenario(app):
            (a, _), (b, _) = await self.open(app, "ann"), await self.open(app, "ben")
            for message in [send(""), send("x" * 1001), {"type": "send", "text": "Hi", "requestId": "nope"},
                            {"type": "dance"}, "not json"]:
                if isinstance(message, str):
                    await a.send_to(text_data=message)
                else:
                    await a.send_json_to(message)
            got_a, got_b = await self.everything(a), await self.everything(b)
            await a.disconnect(); await b.disconnect()
            return got_a, got_b

        got_a, got_b = self.run_async(scenario)
        self.assertEqual([m["reason"] for m in got_a], ["invalid"] * 5)
        self.assertEqual(got_b, [])

    def test_the_31st_message_in_a_minute_is_refused(self):
        async def scenario(app):
            (a, _), (b, _) = await self.open(app, "ann"), await self.open(app, "ben")
            for n in range(31):
                await a.send_json_to(send(f"m{n}"))
            got_a = await self.everything(a, timeout=2)
            await a.disconnect(); await b.disconnect()
            return got_a

        got_a = self.run_async(scenario)
        self.assertEqual([m.get("reason") for m in got_a if m["type"] == "error"], ["rate_limited"])

    def test_older_history_on_request(self):
        for n in range(60):
            services.send(self.ben, self.couple.pk, f"m{n}", None) if n % 2 else \
                services.send(self.ann, self.couple.pk, f"m{n}", None)

        async def scenario(app):
            page, first = await self.open(app, "ann")
            await page.send_json_to({"type": "history", "before": first["messages"][0]["id"]})
            older = await page.receive_json_from(timeout=2)
            await page.disconnect()
            return first, older

        first, older = self.run_async(scenario)
        self.assertEqual(len(first["messages"]), 50)
        self.assertEqual(older["type"], "history")
        self.assertEqual([m["text"] for m in older["messages"]], [f"m{n}" for n in range(10)])

    def test_deleting_reaches_both(self):
        message = services.send(self.ann, self.couple.pk, "Oops", None)

        async def scenario(app):
            (a, _), (b, _) = await self.open(app, "ann"), await self.open(app, "ben")
            await b.send_json_to({"type": "delete", "id": message.pk})  # Not Ben's.
            refused = await self.everything(b)
            await a.send_json_to({"type": "delete", "id": message.pk})
            got_a, got_b = await self.everything(a), await self.everything(b)
            await a.disconnect(); await b.disconnect()
            return refused, got_a, got_b

        refused, got_a, got_b = self.run_async(scenario)
        self.assertEqual([m["reason"] for m in refused], ["invalid"])
        self.assertEqual(got_a, [{"type": "deleted", "id": message.pk}])
        self.assertEqual(got_b, [{"type": "deleted", "id": message.pk}])

    def test_closing_the_couple_cuts_chat_off_at_once(self):
        async def scenario(app):
            (a, _), (b, _) = await self.open(app, "ann"), await self.open(app, "ben")
            await asyncio.get_running_loop().run_in_executor(None, couples.close_couple, self.ann)
            replies = []
            for page in [a, b]:
                replies.append(await page.receive_json_from(timeout=2))
                replies.append(await page.receive_output(timeout=2))
            again = self.page(app, self.cookies["ben"])
            reconnected, _ = await again.connect()
            return replies, reconnected

        replies, reconnected = self.run_async(scenario)
        self.assertEqual([r.get("reason") for r in replies[0::2]], ["forbidden", "forbidden"])
        self.assertEqual([r["type"] for r in replies[1::2]], ["websocket.close", "websocket.close"])
        self.assertFalse(reconnected)

    def test_membership_is_rechecked_on_every_message(self):
        async def scenario(app):
            (a, _), (b, _) = await self.open(app, "ann"), await self.open(app, "ben")
            # Ben's membership ends without any notification reaching the socket.
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: Membership.objects.filter(user=self.ben).update(left_at="2026-10-28T00:00:00Z"))
            await b.send_json_to(send("Am I still here?"))
            reply = await b.receive_json_from(timeout=2)
            closed = await b.receive_output(timeout=2)
            await a.send_json_to(send("Ann's message"))
            ann_got = await self.everything(a)
            await a.disconnect()
            return reply, closed, ann_got

        reply, closed, ann_got = self.run_async(scenario)
        self.assertEqual(reply["reason"], "forbidden")
        self.assertEqual(closed["type"], "websocket.close")
        self.assertNotIn("Am I still here?", str(ann_got))

    def test_a_password_reset_closes_that_users_chat(self):
        async def scenario(app):
            (a, _), (b, _) = await self.open(app, "ann"), await self.open(app, "ben")
            await asyncio.get_running_loop().run_in_executor(None, sign_out_everywhere, self.ann)
            reply = await a.receive_json_from(timeout=2)
            closed = await a.receive_output(timeout=2)
            ben_quiet = await b.receive_nothing(timeout=0.5)
            await b.disconnect()
            return reply, closed, ben_quiet

        reply, closed, ben_quiet = self.run_async(scenario)
        self.assertEqual((reply["reason"], closed["type"]), ("forbidden", "websocket.close"))
        self.assertTrue(ben_quiet)

    def test_without_a_key_sending_reports_chat_unavailable(self):
        async def scenario(app):
            page, _ = await self.open(app, "ann")
            with override_settings(CHAT_ENCRYPTION_KEYS=[]):
                await page.send_json_to(send("Hi"))
                reply = await page.receive_json_from(timeout=2)
            await page.disconnect()
            return reply

        self.assertEqual(self.run_async(scenario)["reason"], "unavailable")

    def test_reading_on_one_device_clears_the_badge_on_the_other_but_not_the_partners(self):
        message = services.send(self.ben, self.couple.pk, "Unread", None)
        ann_cookie_2 = cookie_for(self.ann)

        async def scenario(app):
            (phone, first), (b, _) = await self.open(app, "ann"), await self.open(app, "ben")
            laptop = self.page(app, ann_cookie_2)
            assert (await laptop.connect())[0]
            await laptop.receive_json_from(timeout=2)
            await phone.send_json_to({"type": "read", "upTo": message.pk})
            got_phone, got_laptop, got_ben = await self.everything(phone), await self.everything(laptop), \
                await self.everything(b)
            for page in [phone, laptop, b]:
                await page.disconnect()
            return first, got_phone, got_laptop, got_ben

        first, got_phone, got_laptop, got_ben = self.run_async(scenario)
        self.assertEqual(first["unread"], 1)
        self.assertEqual(got_laptop, [{"type": "read", "upTo": message.pk}])
        self.assertEqual(got_phone, [{"type": "read", "upTo": message.pk}])
        self.assertEqual(got_ben, [])
