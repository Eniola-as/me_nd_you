"""The couple's game mode is shared (owner, 2026-10-29). The first mode starts
straight away; after that a switch is a request the other partner must
accept, and nothing changes while it's pending. Declined or cancelled keeps
the current mode. Accepted: the new mode starts (fresh if never played), and
every mode keeps its progress for when the couple switches back. Leaving a
mode deletes its unrevealed answers and picks (as Next does). Both partners
are told live, on every member page."""

import importlib
import json
import uuid
from unittest import mock

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils.html import strip_tags

import me_nd_you.asgi
from chat.tests import with_chat_key
from couples import services as couples
from play import modes, services
from play.groups import mode_group_name
from play.models import GameRoom

PASSWORD = "a-long-passphrase-1"


def make_couple():
    ann, ben = [get_user_model().objects.create_user(email=e, password=PASSWORD, display_name=n)
                for e, n in (("ann@example.com", "Annie"), ("ben@example.com", "Benny"))]
    couple = couples.create_couple(ann)
    couples.redeem_invitation(ben, couples.create_invitation(ann))
    return couple, ann, ben


class ModeServiceTests(TestCase):
    def setUp(self):
        self.couple, self.ann, self.ben = make_couple()
        self.sent = []
        patcher = mock.patch("play.modes.notify", side_effect=lambda user_id, event: self.sent.append((user_id, event)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_commit(self, function, *args, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            return function(*args, **kwargs)

    def test_each_mode_has_its_game_and_turn_rules(self):
        self.assertEqual(modes.MODE_GAMES, {
            "questions": "answer_reveal", "would": "pick_reveal",
            "truth": "truth_or_dare", "challenge": "challenge_turns",
            "spicy": "questions", "mixed": "questions",
        })

    def test_the_first_mode_starts_at_once_and_both_are_told(self):
        state = self.run_commit(modes.start, self.ann, "truth")
        self.assertEqual((state["mode"], state["pending"]), ("truth", None))
        self.assertEqual(sorted(user for user, _ in self.sent), sorted([self.ann.pk, self.ben.pk]))
        self.assertTrue(all(event["event"] == "started" and event["mode"] == "truth" for _, event in self.sent))

    def test_once_a_mode_is_set_start_never_changes_it(self):
        self.run_commit(modes.start, self.ann, "truth")
        self.assertEqual(self.run_commit(modes.start, self.ben, "spicy")["mode"], "truth")

    def test_a_switch_is_only_a_request_until_the_partner_accepts(self):
        version = self.run_commit(modes.start, self.ann, "truth")["version"]
        self.sent.clear()
        state = self.run_commit(modes.request_switch, self.ann, "challenge", version)
        self.assertEqual(state["mode"], "truth")  # Nothing changes yet.
        self.assertEqual(state["pending"], {"mode": "challenge", "by_you": True})
        ben_view = modes.snapshot(self.couple, self.ben)
        self.assertEqual(ben_view["pending"], {"mode": "challenge", "by_you": False})
        self.assertEqual({e["event"] for _, e in self.sent}, {"requested"})

    def test_only_one_request_at_a_time(self):
        version = self.run_commit(modes.start, self.ann, "truth")["version"]
        version = self.run_commit(modes.request_switch, self.ann, "challenge", version)["version"]
        with self.assertRaises(modes.Invalid):
            self.run_commit(modes.request_switch, self.ben, "spicy", version)

    def test_the_requester_cannot_accept_their_own_request(self):
        version = self.run_commit(modes.start, self.ann, "truth")["version"]
        version = self.run_commit(modes.request_switch, self.ann, "challenge", version)["version"]
        with self.assertRaises(modes.Invalid):
            self.run_commit(modes.respond, self.ann, True, version)

    def test_accepting_switches_for_both(self):
        version = self.run_commit(modes.start, self.ann, "truth")["version"]
        version = self.run_commit(modes.request_switch, self.ann, "challenge", version)["version"]
        self.sent.clear()
        state = self.run_commit(modes.respond, self.ben, True, version)
        self.assertEqual((state["mode"], state["pending"]), ("challenge", None))
        self.assertEqual({e["event"] for _, e in self.sent}, {"switched"})
        self.assertEqual(modes.snapshot(self.couple, self.ann)["mode"], "challenge")

    def test_declining_or_cancelling_keeps_the_current_mode(self):
        version = self.run_commit(modes.start, self.ann, "truth")["version"]
        version = self.run_commit(modes.request_switch, self.ann, "challenge", version)["version"]
        state = self.run_commit(modes.respond, self.ben, False, version)
        self.assertEqual((state["mode"], state["pending"]), ("truth", None))
        version = self.run_commit(modes.request_switch, self.ben, "spicy", state["version"])["version"]
        state = self.run_commit(modes.cancel, self.ben, version)
        self.assertEqual((state["mode"], state["pending"]), ("truth", None))

    def test_a_stale_version_changes_nothing_and_returns_the_latest(self):
        version = self.run_commit(modes.start, self.ann, "truth")["version"]
        self.run_commit(modes.request_switch, self.ann, "challenge", version)
        with self.assertRaises(modes.Stale) as stale:
            self.run_commit(modes.respond, self.ben, True, version)  # Old version.
        self.assertEqual(stale.exception.snapshot["pending"], {"mode": "challenge", "by_you": False})
        self.assertEqual(modes.snapshot(self.couple, self.ben)["mode"], "truth")

    def test_a_pending_request_never_touches_the_current_game(self):
        self.run_commit(modes.start, self.ann, "truth")
        room = services.room_for(self.ann, "truth_or_dare", "truth")
        before = (room.version, room.state)
        version = modes.snapshot(self.couple, self.ann)["version"]
        self.run_commit(modes.request_switch, self.ann, "challenge", version)
        room.refresh_from_db()
        self.assertEqual((room.version, room.state), before)

    def test_leaving_a_mode_deletes_its_unrevealed_answers(self):
        version = self.run_commit(modes.start, self.ann, "questions")["version"]
        room = services.room_for(self.ann, "answer_reveal", "questions")
        card = room.state["current"]["key"]
        self.run_commit(services.apply_action, self.ann, room.pk, "answer", room.version, str(uuid.uuid4()),
                        {"card": card, "text": "My private answer"})
        version = self.run_commit(modes.request_switch, self.ann, "spicy", version)["version"]
        self.run_commit(modes.respond, self.ben, True, version)
        room.refresh_from_db()
        self.assertEqual(room.state["answers"], {})
        self.assertNotIn("My private answer", json.dumps(room.state))

    def test_every_mode_keeps_its_progress_for_when_you_switch_back(self):
        version = self.run_commit(modes.start, self.ann, "spicy")["version"]
        room = services.room_for(self.ann, "questions", "spicy")
        self.run_commit(services.apply_action, self.ann, room.pk, "next", room.version, str(uuid.uuid4()))
        room.refresh_from_db()
        position = room.state["position"]
        version = self.run_commit(modes.request_switch, self.ann, "truth", version)["version"]
        version = self.run_commit(modes.respond, self.ben, True, version)["version"]
        version = self.run_commit(modes.request_switch, self.ben, "spicy", version)["version"]
        self.run_commit(modes.respond, self.ann, True, version)
        self.assertEqual(services.room_for(self.ann, "questions", "spicy").state["position"], position)

    def test_a_new_mode_starts_fresh(self):
        version = self.run_commit(modes.start, self.ann, "spicy")["version"]
        version = self.run_commit(modes.request_switch, self.ann, "mixed", version)["version"]
        self.run_commit(modes.respond, self.ben, True, version)
        self.assertFalse(GameRoom.objects.filter(couple=self.couple, variant="mixed").exclude(version=1).exists())

    def test_only_the_couples_current_mode_can_be_played(self):
        version = self.run_commit(modes.start, self.ann, "spicy")["version"]
        room = services.room_for(self.ann, "questions", "spicy")
        version = self.run_commit(modes.request_switch, self.ann, "mixed", version)["version"]
        self.run_commit(modes.respond, self.ben, True, version)
        # A page still showing Spicy Only can't move its deck any more.
        room.refresh_from_db()
        with self.assertRaises(services.Invalid):
            services.apply_action(self.ann, room.pk, "next", room.version, str(uuid.uuid4()))

    def test_unknown_modes_and_non_members_are_refused(self):
        with self.assertRaises(modes.Invalid):
            modes.start(self.ann, "poker")
        outsider = get_user_model().objects.create_user(email="cat@example.com", password=PASSWORD)
        with self.assertRaises(modes.Forbidden):
            modes.start(outsider, "truth")


class ModeApiTests(TestCase):
    def setUp(self):
        self.couple, self.ann, self.ben = make_couple()
        self.clients = {}
        for user in (self.ann, self.ben):
            self.clients[user.email] = Client()
            self.clients[user.email].force_login(user)

    def post(self, who, **data):
        with mock.patch("play.modes.notify"):
            return self.clients[who].post("/api/space/mode/", data, content_type="application/json")

    def test_request_accept_through_the_api(self):
        version = self.post("ann@example.com", action="start", mode="truth").json()["version"]
        response = self.post("ann@example.com", action="request", mode="would", version=version)
        self.assertEqual(response.status_code, 200)
        response = self.post("ben@example.com", action="accept", version=response.json()["version"])
        self.assertEqual(response.json()["mode"], "would")

    def test_a_stale_request_returns_409_with_the_latest_state(self):
        version = self.post("ann@example.com", action="start", mode="truth").json()["version"]
        self.post("ann@example.com", action="request", mode="would", version=version)
        response = self.post("ben@example.com", action="decline", version=version)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["state"]["pending"]["mode"], "would")

    def test_outsiders_get_403(self):
        outsider = get_user_model().objects.create_user(email="cat@example.com", password=PASSWORD)
        client = Client()
        client.force_login(outsider)
        response = client.post("/api/space/mode/", {"action": "start", "mode": "truth"}, content_type="application/json")
        self.assertEqual(response.status_code, 403)


class ModePageTests(TestCase):
    def setUp(self):
        self.couple, self.ann, self.ben = make_couple()
        self.client.force_login(self.ann)

    def test_opening_a_mode_with_none_set_starts_it(self):
        with mock.patch("play.modes.notify"), self.captureOnCommitCallbacks(execute=True):
            response = self.client.get("/play/?mode=challenge")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(modes.snapshot(self.couple, self.ann)["mode"], "challenge")
        self.assertContains(response, 'data-game="challenge_turns"')

    def test_opening_another_mode_shows_the_couples_current_mode(self):
        with mock.patch("play.modes.notify"), self.captureOnCommitCallbacks(execute=True):
            modes.start(self.ben, "truth")
        response = self.client.get("/play/?mode=spicy")
        self.assertRedirects(response, "/play/?mode=truth", fetch_redirect_response=False)

    def test_member_pages_say_what_is_playing_and_any_pending_request(self):
        with mock.patch("play.modes.notify"), self.captureOnCommitCallbacks(execute=True):
            version = modes.start(self.ben, "truth")["version"]
            modes.request_switch(self.ben, "would", version)
        for page in ["/space/", "/modes/", "/play/?mode=truth"]:
            with self.subTest(page):
                html = " ".join(strip_tags(self.client.get(page).content.decode()).split())  # Visible text.
                self.assertIn("Now playing: Truth or Dare", html)
                self.assertIn("Benny wants to switch to Would You Rather.", html)


@with_chat_key
@override_settings(ALLOWED_HOSTS=["me-nd-you.onrender.com"])
class LiveNoticeTests(TransactionTestCase):
    serialized_rollback = True

    def test_both_partners_open_pages_hear_about_a_change(self):
        couple, ann, ben = make_couple()
        client = Client()
        client.force_login(ben)
        cookie = f"sessionid={client.cookies['sessionid'].value}".encode()

        async def scenario():
            app = importlib.reload(me_nd_you.asgi).application
            page = WebsocketCommunicator(app, "/ws/chat/", headers=[(b"origin", b"https://me-nd-you.onrender.com"),
                                                                     (b"cookie", cookie)])
            assert (await page.connect())[0]
            while not await page.receive_nothing(timeout=0.3):
                await page.receive_output(timeout=1)
            await get_channel_layer().group_send(mode_group_name(ben.pk), {
                "type": "couple.mode", "event": "requested", "mode": "would", "by_you": False, "partner": "Annie"})
            frames = []
            while not await page.receive_nothing(timeout=0.5):
                data = json.loads((await page.receive_output(timeout=1))["text"])
                if data["type"] not in ("presence", "typing"):
                    frames.append(data)
            await page.disconnect()
            return frames

        frames = async_to_sync(scenario)()
        self.assertEqual(frames, [{"type": "mode", "event": "requested", "mode": "would", "by_you": False,
                                   "partner": "Annie"}])
