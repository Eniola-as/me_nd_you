"""Leaving a couple closes it for both partners. Nothing is deleted; access
through pages, the API and WebSockets ends; an admin can reopen it."""

import hashlib
import importlib
import uuid
from datetime import timedelta
from unittest import mock

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

import me_nd_you.asgi
from couples import services
from couples.models import Couple, Invitation, Membership
from game.models import CustomQuestion
from play import services as play
from play.cards import DatabaseCards
from play.models import GameRoom, RoomEvent

PASSWORD = "a-long-passphrase-1"


def make_user(email, name=""):
    return get_user_model().objects.create_user(email=email, password=PASSWORD, display_name=name)


def make_couple(a_email="ann@example.com", b_email="ben@example.com"):
    ann, ben = make_user(a_email, "Ann"), make_user(b_email, "Ben")
    couple = services.create_couple(ann)
    services.redeem_invitation(ben, services.create_invitation(ann))
    return couple, ann, ben


def signed_in(user):
    client = Client()
    client.force_login(user)
    return client


class CloseCoupleServiceTests(TestCase):
    def setUp(self):
        self.couple, self.ann, self.ben = make_couple()
        self.question = CustomQuestion.objects.create(space=self.couple, text="Ours?", mode="questions")
        self.room = play.room_for(self.ann, "questions", "questions")
        play.apply_action(self.ann, self.room.id, "next", expected_version=1, request_id=str(uuid.uuid4()))

    def close(self, user=None):
        with self.captureOnCommitCallbacks(execute=True):
            services.close_couple(user or self.ann)

    def test_both_memberships_end_and_the_couple_is_closed(self):
        self.close()
        self.couple.refresh_from_db()
        self.assertIsNotNone(self.couple.closed_at)
        self.assertEqual(self.couple.closed_by, self.ann)
        self.assertFalse(Membership.objects.active().filter(couple=self.couple).exists())
        self.assertIsNone(services.active_couple(self.ann))
        self.assertIsNone(services.active_couple(self.ben))

    def test_nothing_is_deleted(self):
        self.close()
        self.assertTrue(Couple.objects.filter(pk=self.couple.pk).exists())
        self.assertTrue(CustomQuestion.objects.filter(pk=self.question.pk).exists())
        self.assertEqual(Membership.objects.filter(couple=self.couple).count(), 2)
        self.assertEqual(RoomEvent.objects.filter(room=self.room).count(), 1)

    def test_rooms_close_and_other_couples_are_unaffected(self):
        cy = make_user("cy@example.com")
        other_couple = services.create_couple(cy)
        token = services.create_invitation(cy)
        self.close()
        self.assertEqual(GameRoom.objects.get(pk=self.room.pk).status, GameRoom.CLOSED)
        self.assertEqual(services.redeem_invitation(make_user("di@example.com"), token), other_couple)

    def test_pending_invitation_of_the_closed_couple_stops_working(self):
        Membership.objects.filter(user=self.ben).update(left_at=timezone.now())  # Room for one more.
        token = services.create_invitation(self.ann)
        self.close()
        with self.assertRaises(services.InvalidInvitation):
            services.redeem_invitation(make_user("cy@example.com"), token)

    def test_a_planted_invitation_to_a_closed_couple_is_refused(self):
        self.close()
        Invitation.objects.create(couple=self.couple, created_by=self.ann,
                                  token_hash=hashlib.sha256(b"planted").hexdigest(),
                                  expires_at=timezone.now() + timedelta(days=1))
        with self.assertRaises(services.InvalidInvitation):
            services.redeem_invitation(make_user("cy@example.com"), "planted")

    def test_live_connections_are_told_only_after_commit(self):
        with mock.patch("couples.services.notify_room_closed") as notify:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                services.close_couple(self.ann)
            notify.assert_not_called()
            for callback in callbacks:
                callback()
            notify.assert_called_once_with(self.room.id)

    def test_only_a_member_can_close(self):
        with self.assertRaises(services.NotInCouple):
            services.close_couple(make_user("cy@example.com"))

    def test_both_can_start_again_afterwards(self):
        self.close()
        self.assertNotEqual(services.create_couple(self.ann), self.couple)
        self.assertNotEqual(services.create_couple(self.ben), self.couple)


class LeavePageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.couple, self.ann, self.ben = make_couple()
        self.client = signed_in(self.ann)

    def test_page_explains_that_both_lose_access(self):
        page = self.client.get("/space/").content.decode()
        self.assertIn("both of you lose access", page)

    def test_leaving_without_confirming_changes_nothing(self):
        self.client.post("/space/", {"action": "leave_couple"})
        self.assertEqual(services.active_couple(self.ben), self.couple)

    def test_confirmed_leave_closes_the_couple(self):
        self.client.post("/space/", {"action": "leave_couple", "confirm": "yes"})
        self.assertIsNone(services.active_couple(self.ben))

    def test_old_urls_and_api_stop_working_for_both(self):
        self.client.post("/space/", {"action": "leave_couple", "confirm": "yes"})
        partner = signed_in(self.ben)
        added = partner.post("/api/space/custom-questions/", {"text": "Still here?", "mode": "questions"},
                             content_type="application/json")
        self.assertEqual(added.status_code, 403)
        self.assertRedirects(partner.get("/play/?mode=questions"), "/space/", fetch_redirect_response=False)
        self.assertNotIn("share this space", partner.get("/space/").content.decode())
        with self.assertRaises(play.Forbidden):
            play.room_for(self.ben, "questions", "questions")


class AdminRecoveryTests(TestCase):
    def setUp(self):
        self.couple, self.ann, self.ben = make_couple()
        CustomQuestion.objects.create(space=self.couple, text="Ours?", mode="questions")
        with self.captureOnCommitCallbacks(execute=True):
            services.close_couple(self.ann)

    def test_reopening_restores_both_members_and_their_questions(self):
        restored = services.reopen_couple(self.couple)
        self.assertEqual(sorted(u.email for u in restored), ["ann@example.com", "ben@example.com"])
        self.couple.refresh_from_db()
        self.assertIsNone(self.couple.closed_at)
        self.assertEqual(services.active_couple(self.ben), self.couple)
        texts = [card["text"] for card in DatabaseCards(services.active_couple(self.ben), "questions").all()]
        self.assertIn("Ours?", texts)

    def test_a_member_now_in_another_couple_is_not_pulled_back(self):
        new_couple = services.create_couple(self.ben)
        restored = services.reopen_couple(self.couple)
        self.assertEqual([u.email for u in restored], ["ann@example.com"])
        self.assertEqual(services.active_couple(self.ben), new_couple)

    def test_admin_action_reopens(self):
        admin = get_user_model().objects.create_superuser(email="admin@example.com", password=PASSWORD)
        client = signed_in(admin)
        client.post("/admin/couples/couple/", {"action": "reopen_couples", "_selected_action": [str(self.couple.pk)]})
        self.couple.refresh_from_db()
        self.assertIsNone(self.couple.closed_at)


@override_settings(ALLOWED_HOSTS=["me-nd-you.onrender.com"])
class LiveConnectionTests(TransactionTestCase):
    serialized_rollback = True
    ORIGIN = b"https://me-nd-you.onrender.com"

    def test_open_game_connections_are_closed_when_the_couple_closes(self):
        couple, ann, ben = make_couple()
        client = signed_in(ben)
        cookie = f"sessionid={client.cookies['sessionid'].value}".encode()

        async def scenario():
            app = importlib.reload(me_nd_you.asgi).application
            page = WebsocketCommunicator(app, "/ws/room/questions/questions/",
                                         headers=[(b"origin", self.ORIGIN), (b"cookie", cookie)])
            assert (await page.connect())[0]
            await page.receive_json_from(timeout=2)  # The snapshot.
            import asyncio
            await asyncio.get_running_loop().run_in_executor(None, services.close_couple, ann)
            reply = await page.receive_json_from(timeout=2)
            closed = await page.receive_output(timeout=2)
            return reply, closed

        reply, closed = async_to_sync(scenario)()
        self.assertEqual(reply["reason"], "forbidden")
        self.assertEqual(closed["type"], "websocket.close")

    def test_the_old_space_relay_socket_is_gone(self):
        couple, ann, _ = make_couple()
        client = signed_in(ann)
        cookie = f"sessionid={client.cookies['sessionid'].value}".encode()

        async def scenario():
            app = importlib.reload(me_nd_you.asgi).application
            page = WebsocketCommunicator(app, "/ws/space/questions/",
                                         headers=[(b"origin", self.ORIGIN), (b"cookie", cookie)])
            try:
                connected, _ = await page.connect()
            except ValueError:  # No route.
                connected = False
            return connected

        self.assertFalse(async_to_sync(scenario)())
