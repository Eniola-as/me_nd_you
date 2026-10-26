import threading
import uuid
from unittest import mock, skipUnless

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from couples import services as couples
from couples.models import Membership
from game.models import CustomQuestion, Question
from play import services
from play.models import GameRoom, RoomEvent


def make_couple(*emails):
    users = [get_user_model().objects.create_user(email=e, password="a-long-passphrase-1") for e in emails]
    couple = couples.create_couple(users[0])
    for user in users[1:]:
        couples.redeem_invitation(user, couples.create_invitation(users[0]))
    return couple, users


class RoomSetupTests(TestCase):
    def setUp(self):
        self.couple, (self.ann, self.ben) = make_couple("ann@example.com", "ben@example.com")

    def test_room_is_created_once_per_couple_and_mode(self):
        room = services.room_for(self.ann, "questions", "truth")
        self.assertEqual(services.room_for(self.ben, "questions", "truth"), room)
        self.assertNotEqual(services.room_for(self.ann, "questions", "spicy"), room)
        self.assertEqual(room.version, 1)

    def test_deck_uses_the_mode_and_the_couples_own_questions(self):
        CustomQuestion.objects.create(space=self.couple, text="Ours?", mode="truth")
        room = services.room_for(self.ann, "questions", "truth")
        self.assertEqual(len(room.state["deck"]), Question.objects.filter(mode="truth").count() + 1)

    def test_snapshot_is_the_same_for_both_partners(self):
        room = services.room_for(self.ann, "questions", "questions")
        a, b = services.snapshot(room, self.ann), services.snapshot(room, self.ben)
        self.assertEqual(a, b)
        self.assertEqual(a["version"], 1)
        self.assertNotIn("deck", a["state"])

    def test_outsiders_get_no_room(self):
        _, (cy,) = make_couple("cy@example.com")
        room = services.room_for(self.ann, "questions", "questions")
        with self.assertRaises(services.Forbidden):
            services.snapshot(room, cy)
        loner = get_user_model().objects.create_user(email="lo@example.com", password="x-long-passphrase-1")
        with self.assertRaises(services.Forbidden):
            services.room_for(loner, "questions", "questions")

    def test_unknown_game_or_mode_is_refused(self):
        for game, variant in [("chess", "questions"), ("questions", "not-a-mode")]:
            with self.subTest(game=game, variant=variant), self.assertRaises(services.Invalid):
                services.room_for(self.ann, game, variant)


class ActionTests(TestCase):
    def setUp(self):
        self.couple, (self.ann, self.ben) = make_couple("ann@example.com", "ben@example.com")
        self.room = services.room_for(self.ann, "questions", "questions")

    def act(self, user, action="next", version=None, request_id=None, payload=None):
        return services.apply_action(
            user, self.room.id, action,
            expected_version=self.room.version if version is None else version,
            request_id=request_id or str(uuid.uuid4()), payload=payload,
        )

    def test_next_advances_once_and_records_an_event(self):
        before = self.room.state["position"]
        room = self.act(self.ann)
        self.assertEqual((room.version, room.state["position"]), (2, before + 1))
        event = RoomEvent.objects.get(room=room, version=2)
        self.assertEqual((event.kind, event.actor), ("next", self.ann))

    def test_stale_version_changes_nothing_and_returns_the_latest_state(self):
        self.act(self.ann)  # version 2
        with self.assertRaises(services.Stale) as caught:
            self.act(self.ben, version=1)
        self.assertEqual(caught.exception.snapshot["version"], 2)
        self.assertEqual(GameRoom.objects.get().version, 2)
        self.assertEqual(RoomEvent.objects.count(), 1)

    def test_duplicate_request_is_applied_once(self):
        request_id = str(uuid.uuid4())
        first = self.act(self.ann, request_id=request_id)
        again = self.act(self.ann, version=1, request_id=request_id)  # A retry.
        self.assertEqual(again.version, first.version)
        self.assertEqual(GameRoom.objects.get().state["position"], 1)
        self.assertEqual(RoomEvent.objects.count(), 1)

    def test_membership_is_rechecked_on_every_action(self):
        Membership.objects.filter(user=self.ben).update(left_at=timezone.now())
        with self.assertRaises(services.Forbidden):
            self.act(self.ben)
        self.assertEqual(GameRoom.objects.get().version, 1)

    def test_closed_room_refuses_actions(self):
        GameRoom.objects.update(status=GameRoom.CLOSED)
        with self.assertRaises(services.Forbidden):
            self.act(self.ann)

    def test_invalid_action_changes_nothing(self):
        with self.assertRaises(services.Invalid):
            self.act(self.ann, action="jump")
        self.assertEqual(GameRoom.objects.get().version, 1)

    def test_broadcast_happens_only_after_commit(self):
        with mock.patch("play.services.notify_room") as notify:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                self.act(self.ann)
            notify.assert_not_called()  # Nothing sent before commit.
            for callback in callbacks:
                callback()
            notify.assert_called_once_with(self.room.id, 2)

    def test_failed_transaction_sends_nothing_and_keeps_the_state(self):
        with mock.patch("play.services.notify_room") as notify, \
             mock.patch("play.models.RoomEvent.objects.create", side_effect=RuntimeError("disk full")):
            with self.captureOnCommitCallbacks(execute=True):
                with self.assertRaises(RuntimeError):
                    self.act(self.ann)
            notify.assert_not_called()
        self.assertEqual(GameRoom.objects.get().version, 1)

    def test_custom_question_reaches_open_rooms_once(self):
        with self.captureOnCommitCallbacks(execute=True):
            question = CustomQuestion.objects.create(space=self.couple, text="Ours?", mode="questions")
            services.add_custom_card(question)
        room = GameRoom.objects.get()
        self.assertEqual((room.version, room.state["deck"].count(f"c:{question.pk}")), (2, 1))


class HiddenAnswerTests(TestCase):
    def setUp(self):
        self.couple, (self.ann, self.ben) = make_couple("ann@example.com", "ben@example.com")
        self.room = services.room_for(self.ann, "answer_reveal", "questions")

    def answer(self, user, text):
        room = GameRoom.objects.get(pk=self.room.pk)
        return services.apply_action(user, room.id, "answer", expected_version=room.version,
                                     request_id=str(uuid.uuid4()), payload={"text": text})

    def test_partner_never_receives_an_unrevealed_answer(self):
        room = self.answer(self.ann, "Only Ann knows this")
        self.assertNotIn("Only Ann knows this", str(services.snapshot(room, self.ben)))
        self.assertIn("Only Ann knows this", str(services.snapshot(room, self.ann)))

    def test_both_answers_are_shared_after_both_answer(self):
        self.answer(self.ann, "Ann's answer")
        room = self.answer(self.ben, "Ben's answer")
        self.assertIn("Ann's answer", str(services.snapshot(room, self.ben)))
        self.assertIn("Ben's answer", str(services.snapshot(room, self.ann)))


@skipUnless(connection.vendor == "postgresql", "Real concurrency needs PostgreSQL.")
class SimultaneousActionTests(TransactionTestCase):
    serialized_rollback = True

    def test_simultaneous_next_advances_exactly_once(self):
        couple, (ann, ben) = make_couple("ann@example.com", "ben@example.com")
        room = services.room_for(ann, "questions", "questions")
        barrier, outcomes = threading.Barrier(2), []

        def press(user):
            try:
                barrier.wait()
                services.apply_action(user, room.id, "next", expected_version=1,
                                      request_id=str(uuid.uuid4()))
                outcomes.append("advanced")
            except services.Stale:
                outcomes.append("stale")
            finally:
                connection.close()

        threads = [threading.Thread(target=press, args=(u,)) for u in (ann, ben)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(outcomes), ["advanced", "stale"])
        stored = GameRoom.objects.get()
        self.assertEqual((stored.version, stored.state["position"]), (2, 1))
        self.assertEqual(RoomEvent.objects.count(), 1)


class CustomQuestionApiTests(TestCase):
    def test_question_added_through_the_api_reaches_the_open_room(self):
        from django.core.cache import cache
        from django.test import Client

        cache.clear()
        couple, (ann, _) = make_couple("ann@example.com", "ben@example.com")
        room = services.room_for(ann, "questions", "questions")
        client = Client(enforce_csrf_checks=True)
        client.force_login(ann)
        client.get("/play/")
        with self.captureOnCommitCallbacks(execute=True):
            response = client.post("/api/space/custom-questions/", {"text": "Ours?", "mode": "questions"},
                                   content_type="application/json",
                                   HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 201)
        room.refresh_from_db()
        key = f"c:{CustomQuestion.objects.get().pk}"
        self.assertEqual((room.version, room.state["deck"].count(key)), (2, 1))
