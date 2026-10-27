"""The room WebSocket: snapshots on connect, actions, broadcasts, and access
re-checked on every action and every update."""

import asyncio
import importlib
import uuid

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

import me_nd_you.asgi
from couples import services as couples
from couples.models import Membership
from play.models import GameRoom

ORIGIN = b"https://me-nd-you.onrender.com"
PATH = "/ws/room/questions/questions/"


def make_couple(*emails):
    users = [get_user_model().objects.create_user(email=e, password="a-long-passphrase-1") for e in emails]
    couple = couples.create_couple(users[0])
    for user in users[1:]:
        couples.redeem_invitation(user, couples.create_invitation(users[0]))
    return couple, users


def cookie_for(user):
    client = Client()
    client.force_login(user)
    return f"sessionid={client.cookies['sessionid'].value}".encode()


def action(name, version, request_id=None, payload=None):
    message = {"type": "action", "action": name, "expectedVersion": version,
               "requestId": request_id or str(uuid.uuid4())}
    if payload is not None:
        message["payload"] = payload
    return message


@override_settings(ALLOWED_HOSTS=["me-nd-you.onrender.com"])
class RoomSocketTests(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        self.couple, (self.ann, self.ben) = make_couple("ann@example.com", "ben@example.com")
        self.cookies = {"ann": cookie_for(self.ann), "ben": cookie_for(self.ben)}

    def run_async(self, scenario):
        async def wrapper():
            application = importlib.reload(me_nd_you.asgi).application
            return await scenario(application)

        return async_to_sync(wrapper)()

    @staticmethod
    def page(application, cookie=None, path=PATH):
        headers = [(b"origin", ORIGIN)] + ([(b"cookie", cookie)] if cookie else [])
        return WebsocketCommunicator(application, path, headers=headers)

    async def open(self, application, who, path=PATH):
        page = self.page(application, self.cookies[who], path)
        connected, _ = await page.connect()
        assert connected, who
        return page, await page.receive_json_from(timeout=2)

    async def latest_state(self, page, timeout=1):
        """Drain messages; return the last state and any errors seen.
        Uses receive_nothing: a timed-out receive would cancel the test
        connection, breaking later steps that reuse it."""
        state, errors = None, []
        while not await page.receive_nothing(timeout=timeout):
            message = await page.receive_json_from(timeout=timeout)
            if message["type"] == "state":
                state = message
            else:
                errors.append(message)
        return state, errors

    def test_both_partners_get_the_same_snapshot_on_connect(self):
        async def scenario(app):
            (a, sa), (b, sb) = await self.open(app, "ann"), await self.open(app, "ben")
            await a.disconnect(); await b.disconnect()
            return sa, sb

        sa, sb = self.run_async(scenario)
        self.assertEqual(sa["type"], "state")
        self.assertEqual(sa, sb)
        self.assertNotIn("deck", sa["state"])

    def test_next_reaches_both_with_the_same_card(self):
        async def scenario(app):
            (a, sa), (b, _) = await self.open(app, "ann"), await self.open(app, "ben")
            await a.send_json_to(action("next", sa["version"]))
            fa, _ = await self.latest_state(a)
            fb, _ = await self.latest_state(b)
            await a.disconnect(); await b.disconnect()
            return sa, fa, fb

        start, fa, fb = self.run_async(scenario)
        self.assertEqual((fa["version"], fb["version"]), (start["version"] + 1,) * 2)
        self.assertEqual(fa["state"]["current"], fb["state"]["current"])
        self.assertNotEqual(fa["state"]["current"], start["state"]["current"])

    def test_simultaneous_next_advances_once_and_both_agree(self):
        async def scenario(app):
            (a, sa), (b, _) = await self.open(app, "ann"), await self.open(app, "ben")
            await asyncio.gather(a.send_json_to(action("next", sa["version"])),
                                 b.send_json_to(action("next", sa["version"])))
            fa, ea = await self.latest_state(a)
            fb, eb = await self.latest_state(b)
            await a.disconnect(); await b.disconnect()
            return sa, fa, fb, ea + eb

        start, fa, fb, errors = self.run_async(scenario)
        self.assertEqual(fa, fb)
        self.assertEqual(fa["version"], start["version"] + 1)
        self.assertEqual(fa["state"]["position"], start["state"]["position"] + 1)
        self.assertEqual([e["reason"] for e in errors], ["stale"])
        self.assertEqual(GameRoom.objects.get().version, start["version"] + 1)

    def test_duplicate_request_does_not_advance_twice(self):
        async def scenario(app):
            a, sa = await self.open(app, "ann")
            request = action("next", sa["version"])
            await a.send_json_to(request)
            await a.send_json_to(request)  # Retried after a hiccup.
            final, errors = await self.latest_state(a)
            await a.disconnect()
            return sa, final, errors

        start, final, errors = self.run_async(scenario)
        self.assertEqual(final["version"], start["version"] + 1)
        self.assertEqual(errors, [])
        self.assertEqual(GameRoom.objects.get().version, start["version"] + 1)

    def test_stale_action_gets_the_latest_state_without_a_transition(self):
        async def scenario(app):
            a, sa = await self.open(app, "ann")
            await a.send_json_to(action("next", sa["version"]))
            await self.latest_state(a)
            await a.send_json_to(action("next", sa["version"]))  # Based on an old version.
            final, errors = await self.latest_state(a)
            await a.disconnect()
            return sa, final, errors

        start, final, errors = self.run_async(scenario)
        self.assertEqual([e["reason"] for e in errors], ["stale"])
        self.assertEqual(GameRoom.objects.get().version, start["version"] + 1)
        self.assertTrue(final is None or final["version"] == start["version"] + 1)

    def test_reconnect_restores_the_server_state(self):
        async def scenario(app):
            a, sa = await self.open(app, "ann")
            await a.disconnect()
            b, sb = await self.open(app, "ben")
            await b.send_json_to(action("next", sb["version"]))
            await b.send_json_to(action("next", sb["version"] + 1))
            moved, _ = await self.latest_state(b)
            await b.disconnect()
            a2, back = await self.open(app, "ann")  # Refresh or reconnect.
            await a2.disconnect()
            return moved, back

        moved, back = self.run_async(scenario)
        self.assertEqual(back, moved)

    def test_revoked_member_is_refused_and_gets_no_more_updates(self):
        async def scenario(app):
            (a, sa), (b, _) = await self.open(app, "ann"), await self.open(app, "ben")
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: Membership.objects.filter(user=self.ben).update(left_at=timezone.now()))
            await a.send_json_to(action("next", sa["version"]))
            await self.latest_state(a)
            b_messages = []
            while not await b.receive_nothing(timeout=1):
                b_messages.append(await b.receive_output(timeout=1))
            await a.disconnect()
            return b_messages

        b_messages = self.run_async(scenario)
        self.assertFalse(any('"type": "state"' in m.get("text", "") for m in b_messages))
        self.assertTrue(any(m["type"] == "websocket.close" for m in b_messages))

    def test_revoked_member_cannot_act(self):
        async def scenario(app):
            b, sb = await self.open(app, "ben")
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: Membership.objects.filter(user=self.ben).update(left_at=timezone.now()))
            await b.send_json_to(action("next", sb["version"]))
            reply = await b.receive_json_from(timeout=1)
            closed = await b.receive_output(timeout=1)
            return reply, closed

        reply, closed = self.run_async(scenario)
        self.assertEqual(reply["reason"], "forbidden")
        self.assertEqual(closed["type"], "websocket.close")
        self.assertEqual(GameRoom.objects.get().version, 1)

    def test_closed_room_refuses_connections_and_actions(self):
        async def scenario(app):
            a, sa = await self.open(app, "ann")
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: GameRoom.objects.update(status=GameRoom.CLOSED))
            await a.send_json_to(action("next", sa["version"]))
            reply = await a.receive_json_from(timeout=1)
            return reply

        reply = self.run_async(scenario)
        self.assertEqual(reply["reason"], "forbidden")
        self.assertEqual(GameRoom.objects.get().version, 1)

    def test_outsiders_and_anonymous_visitors_are_refused(self):
        _, (cy,) = make_couple("cy@example.com")
        cy_cookie = cookie_for(cy)

        async def scenario(app):
            results = []
            for cookie in (None, cy_cookie):
                page = self.page(app, cookie)
                connected, _ = await page.connect()
                results.append(connected)
                if connected:
                    await page.disconnect()
            return results

        self.assertEqual(self.run_async(scenario), [False, True])
        # Cy connects to *Cy's own* room, never Ann and Ben's.
        self.assertEqual(GameRoom.objects.filter(couple=self.couple).count(), 0)

    def test_malformed_messages_are_rejected_without_closing(self):
        async def scenario(app):
            a, sa = await self.open(app, "ann")
            replies = []
            for raw in ["hello", "[]", '{"type": "action"}', '{"type": "action", "action": "next", "expectedVersion": "1"}']:
                await a.send_to(text_data=raw)
                replies.append(await a.receive_json_from(timeout=1))
            await a.send_json_to(action("next", sa["version"]))
            final, _ = await self.latest_state(a)
            await a.disconnect()
            return replies, final, sa

        replies, final, start = self.run_async(scenario)
        self.assertEqual({r["reason"] for r in replies}, {"invalid"})
        self.assertEqual(final["version"], start["version"] + 1)

    def test_hidden_answers_never_reach_the_partner_early(self):
        path = "/ws/room/answer_reveal/questions/"

        async def scenario(app):
            (a, sa), (b, _) = await self.open(app, "ann", path), await self.open(app, "ben", path)
            await a.send_json_to(action("answer", sa["version"], payload={"text": "Ann's secret answer"}))
            b_before, _ = await self.latest_state(b)
            await b.send_json_to(action("answer", sa["version"] + 1, payload={"text": "Ben's answer"}))
            b_after, _ = await self.latest_state(b)
            await a.disconnect(); await b.disconnect()
            return b_before, b_after

        b_before, b_after = self.run_async(scenario)
        self.assertNotIn("Ann's secret answer", str(b_before))
        self.assertTrue(b_before["state"]["partner_answered"])
        self.assertEqual(b_after["state"]["partner_answer"], "Ann's secret answer")

    def test_truth_or_dare_turns_over_the_socket(self):
        path = "/ws/room/truth_or_dare/truth/"

        async def scenario(app):
            (a, sa), (b, sb) = await self.open(app, "ann", path), await self.open(app, "ben", path)
            player, partner = (a, b) if sa["state"]["your_turn"] else (b, a)
            await partner.send_json_to(action("choose", sa["version"], payload={"kind": "dare"}))
            _, refused = await self.latest_state(partner)
            await player.send_json_to(action("choose", sa["version"], payload={"kind": "dare"}))
            fp, _ = await self.latest_state(player)
            fq, _ = await self.latest_state(partner)
            await a.disconnect(); await b.disconnect()
            return sa, sb, refused, fp, fq

        sa, sb, refused, fp, fq = self.run_async(scenario)
        self.assertNotEqual(sa["state"]["your_turn"], sb["state"]["your_turn"])
        self.assertEqual([e.get("detail") for e in refused], ["It's not your turn."])
        self.assertEqual(fp["state"]["current"], fq["state"]["current"])
        self.assertEqual(fp["state"]["current"]["kind"], "dare")
        self.assertEqual((fp["state"]["your_turn"], fq["state"]["your_turn"]), (False, True))
        self.assertNotIn("dares", fp["state"])
