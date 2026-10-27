"""Turn-based Truth or Dare: the player whose turn it is picks Truth or Dare,
the server draws from that pool and the turn passes. Skip is free: another
card from the same pool, same turn, the skipped card to the bottom."""

import threading
import uuid
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, TransactionTestCase

from couples import services as couples
from game.models import CustomQuestion, Question
from play import services
from play.games import ActionInvalid, TruthOrDareGame, get_game
from play.models import GameRoom, RoomEvent

GAME = TruthOrDareGame()
CARDS = (
    [{"key": f"t{n}", "text": f"Truth: Question {n}?", "mode": "truth", "kind": "truth", "custom": False}
     for n in range(4)]
    + [{"key": f"d{n}", "text": f"Dare: Do thing {n}.", "mode": "truth", "kind": "dare", "custom": False}
       for n in range(3)]
)


def started(seed=7):
    return GAME.start(CARDS, seed)


def choose(state, slot, kind):
    return GAME.apply(state, "choose", slot, CARDS, payload={"kind": kind})


class StartTests(TestCase):
    def test_two_pools_hold_every_card_of_their_kind(self):
        state = started()
        self.assertEqual(sorted(state["truths"]), ["t0", "t1", "t2", "t3"])
        self.assertEqual(sorted(state["dares"]), ["d0", "d1", "d2"])
        self.assertIsNone(state["current"])

    def test_the_first_turn_is_random_but_fixed_by_the_seed(self):
        firsts = {started(seed)["turn"] for seed in range(40)}
        self.assertEqual(firsts, {1, 2})
        self.assertEqual(started(5)["turn"], started(5)["turn"])
        self.assertEqual(started(5)["first_turn"], started(5)["turn"])


class ChooseTests(TestCase):
    def setUp(self):
        self.state = started()
        self.player = self.state["turn"]
        self.partner = 3 - self.player

    def test_choosing_draws_from_that_pool_and_passes_the_turn(self):
        after = choose(self.state, self.player, "dare")
        self.assertEqual(after["current"]["kind"], "dare")
        self.assertEqual(after["current"]["key"], self.state["dares"][0])
        self.assertEqual(after["dares"], self.state["dares"][1:])
        self.assertEqual(after["truths"], self.state["truths"])
        self.assertEqual((after["turn"], after["drawn_by"], after["draws"]), (self.partner, self.player, 1))

    def test_only_the_player_whose_turn_it_is_can_choose(self):
        with self.assertRaisesMessage(ActionInvalid, "It's not your turn."):
            choose(self.state, self.partner, "truth")

    def test_turns_alternate(self):
        state = choose(self.state, self.player, "truth")
        state = choose(state, self.partner, "dare")
        self.assertEqual(state["turn"], self.player)

    def test_unknown_choices_are_refused(self):
        for kind in ["both", None, 3]:
            with self.assertRaises(ActionInvalid):
                GAME.apply(self.state, "choose", self.player, CARDS, payload={"kind": kind})

    def test_an_empty_pool_cannot_be_chosen_and_both_empty_finishes(self):
        state, slot = self.state, self.player
        for _ in range(3):
            state, slot = choose(state, slot, "dare"), 3 - slot
        with self.assertRaisesMessage(ActionInvalid, "No dares left."):
            choose(state, slot, "dare")
        for _ in range(4):
            state, slot = choose(state, slot, "truth"), 3 - slot
        self.assertTrue(state["finished"])
        self.assertIsNotNone(state["current"])  # The last card stays up.


class SkipTests(TestCase):
    def setUp(self):
        state = started()
        self.player = state["turn"]
        self.state = choose(state, self.player, "truth")
        self.shown = self.state["current"]["key"]

    def skip(self, state, slot):
        return GAME.apply(state, "skip", slot, CARDS)

    def test_skip_draws_another_of_the_same_kind_and_keeps_the_turn(self):
        after = self.skip(self.state, self.player)
        self.assertEqual(after["current"]["kind"], "truth")
        self.assertNotEqual(after["current"]["key"], self.shown)
        self.assertEqual(after["turn"], self.state["turn"])
        self.assertEqual(after["truths"][-1], self.shown)  # To the bottom, not lost.
        self.assertEqual(len(after["truths"]), len(self.state["truths"]))

    def test_skip_is_unlimited(self):
        state = self.state
        for _ in range(10):
            state = self.skip(state, self.player)
        self.assertEqual(state["current"]["kind"], "truth")

    def test_only_the_player_whose_card_it_is_can_skip(self):
        with self.assertRaises(ActionInvalid):
            self.skip(self.state, 3 - self.player)

    def test_nothing_to_skip_before_the_first_card(self):
        fresh = started()
        with self.assertRaises(ActionInvalid):
            self.skip(fresh, fresh["turn"])

    def test_the_last_card_of_a_kind_cannot_be_skipped(self):
        state, slot = started(), None
        slot = state["turn"]
        for _ in range(3):
            state, drawer, slot = choose(state, slot, "dare"), slot, 3 - slot
        with self.assertRaisesMessage(ActionInvalid, "That was the last dare."):
            self.skip(state, drawer)


class ResetAndCustomCardTests(TestCase):
    def test_reset_starts_again_with_full_pools(self):
        state = choose(started(), started()["turn"], "dare")
        again = GAME.apply(state, "reset", 1, CARDS, seed=11)
        self.assertEqual(again, GAME.start(CARDS, 11))

    def test_a_new_custom_card_joins_its_own_pool(self):
        card = {"key": "c1", "text": "Hug me.", "mode": "truth", "kind": "dare", "custom": True}
        after = GAME.insert_card(started(), card, seed=3)
        self.assertIn("c1", after["dares"])
        self.assertNotIn("c1", after["truths"])
        self.assertEqual(GAME.insert_card(after, card, seed=4), after)  # Once.

    def test_next_is_not_part_of_this_game(self):
        with self.assertRaises(ActionInvalid):
            GAME.apply(started(), "next", 1, CARDS)


class ViewTests(TestCase):
    def test_the_card_hides_its_prefix_and_shows_its_kind(self):
        state = choose(started(), started()["turn"], "dare")
        view = GAME.view(state, 1)
        self.assertEqual(view["current"]["kind"], "dare")
        self.assertFalse(view["current"]["text"].startswith("Dare"))
        self.assertTrue(view["current"]["text"].startswith("Do thing"))

    def test_each_player_sees_whose_turn_it_is(self):
        state = started()
        mine, theirs = GAME.view(state, state["turn"]), GAME.view(state, 3 - state["turn"])
        self.assertTrue(mine["your_turn"] and mine["first_turn_yours"])
        self.assertFalse(theirs["your_turn"] or theirs["first_turn_yours"])

    def test_pool_order_stays_on_the_server(self):
        view = GAME.view(started(), 1)
        self.assertNotIn("truths", view)
        self.assertNotIn("dares", view)
        self.assertEqual((view["truths_left"], view["dares_left"], view["remaining"]), (4, 3, 7))


def make_couple(*emails, names=("Ann", "Ben")):
    users = [get_user_model().objects.create_user(email=e, password="a-long-passphrase-1", display_name=n)
             for e, n in zip(emails, names)]
    couple = couples.create_couple(users[0])
    for user in users[1:]:
        couples.redeem_invitation(user, couples.create_invitation(users[0]))
    return couple, users


class RoomTests(TestCase):
    def test_game_is_registered(self):
        self.assertIsInstance(get_game("truth_or_dare"), TruthOrDareGame)

    def setUp(self):
        self.couple, (self.ann, self.ben) = make_couple("ann@example.com", "ben@example.com")
        self.room = services.room_for(self.ann, "truth_or_dare", "truth")

    def players(self):
        first = self.room.state["turn"]
        return (self.ann, self.ben) if first == 1 else (self.ben, self.ann)

    def test_the_room_uses_the_banks_truths_and_dares(self):
        state = self.room.state
        self.assertEqual(len(state["truths"]), Question.objects.filter(mode="truth", kind="truth").count())
        self.assertEqual(len(state["dares"]), Question.objects.filter(mode="truth", kind="dare").count())

    def test_truth_or_dare_only_plays_the_truth_or_dare_mode(self):
        with self.assertRaises(services.Invalid):
            services.room_for(self.ann, "truth_or_dare", "spicy")

    def test_the_server_refuses_a_choice_out_of_turn(self):
        player, partner = self.players()
        with self.assertRaisesMessage(services.Invalid, "It's not your turn."):
            services.apply_action(partner, self.room.id, "choose", 1, str(uuid.uuid4()), {"kind": "dare"})
        room = services.apply_action(player, self.room.id, "choose", 1, str(uuid.uuid4()), {"kind": "dare"})
        self.assertEqual(room.version, 2)

    def test_both_partners_see_the_same_card_and_their_names(self):
        player, partner = self.players()
        room = services.apply_action(player, self.room.id, "choose", 1, str(uuid.uuid4()), {"kind": "truth"})
        mine, theirs = services.snapshot(room, player), services.snapshot(room, partner)
        self.assertEqual(mine["state"]["current"], theirs["state"]["current"])
        self.assertTrue(theirs["state"]["your_turn"])
        self.assertEqual(theirs["names"]["partner"], player.display_name)
        self.assertNotIn("@", str(mine) + str(theirs))  # No emails.

    def test_a_new_custom_dare_joins_the_open_room(self):
        from play.services import add_custom_card

        question = CustomQuestion.objects.create(space=self.couple, text="Hold my hand.", mode="truth", kind="dare")
        add_custom_card(question)
        self.room.refresh_from_db()
        self.assertIn(f"c:{question.pk}", self.room.state["dares"])


@skipUnless(connection.vendor == "postgresql", "Real concurrency needs PostgreSQL.")
class SimultaneousChoiceTests(TransactionTestCase):
    serialized_rollback = True

    def test_both_pressing_at_once_applies_exactly_one_choice(self):
        couple, (ann, ben) = make_couple("ann@example.com", "ben@example.com")
        room = services.room_for(ann, "truth_or_dare", "truth")
        barrier, outcomes = threading.Barrier(2), []

        def press(user):
            try:
                barrier.wait()
                services.apply_action(user, room.id, "choose", 1, str(uuid.uuid4()), {"kind": "dare"})
                outcomes.append("applied")
            except (services.Stale, services.Invalid):
                outcomes.append("refused")
            finally:
                connection.close()

        threads = [threading.Thread(target=press, args=(u,)) for u in (ann, ben)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(outcomes), ["applied", "refused"])
        stored = GameRoom.objects.get()
        self.assertEqual((stored.version, stored.state["draws"]), (2, 1))
        self.assertEqual(RoomEvent.objects.count(), 1)
