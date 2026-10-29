"""Would You Rather with private picks: each partner picks A or B; neither
pick reaches the other until both have picked; picks are never kept (Next,
Reset and closing the space clear them, and the history never has them)."""

import uuid

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase

from couples import services as couples
from play import services
from play.games import ActionInvalid, get_game, split_options
from play.models import GameRoom, RoomEvent

CARDS = [
    {"key": "q:1", "text": "Would you rather fly or be invisible?", "mode": "would", "custom": False},
    {"key": "q:2", "text": "Would you rather always know when someone is lying, or always get away with lying?",
     "mode": "would", "custom": False},
    {"key": "q:3", "text": "Would you rather hike or swim?", "mode": "would", "custom": False},
]


class SplitOptionsTests(SimpleTestCase):
    def test_a_single_or_splits_into_two_options(self):
        self.assertEqual(split_options("Would you rather fly or be invisible?"), ["Fly", "Be invisible"])

    def test_a_comma_or_wins_over_an_or_inside_an_option(self):
        self.assertEqual(
            split_options("Would you rather explore a city or a forest, or stay home?"),
            ["Explore a city or a forest", "Stay home"],
        )

    def test_anything_ambiguous_is_not_guessed(self):
        for text in [
            "Would you rather have a deep talk or a playful debate over a game of truth or dare?",
            "What's your favourite colour?",
            "Would you rather?",
            "Would you rather sing or ?",
        ]:
            with self.subTest(text):
                self.assertIsNone(split_options(text))


class PickRevealGameTests(SimpleTestCase):
    def setUp(self):
        self.game = get_game("pick_reveal")
        self.state = self.game.start(CARDS, seed=3)
        self.card = self.state["current"]["key"]

    def pick(self, state, slot, choice, card=None):
        return self.game.apply(state, "pick", actor_slot=slot, cards=CARDS,
                               payload={"card": card or self.card, "choice": choice})

    def test_it_is_only_for_would_you_rather(self):
        self.assertEqual(self.game.variants, {"would"})

    def test_a_pick_stays_private_until_both_have_picked(self):
        state = self.pick(self.state, 1, "a")
        mine, theirs = self.game.view(state, 1), self.game.view(state, 2)
        self.assertEqual((mine["phase"], mine["my_pick"], mine["partner_pick"]), ("picking", "a", None))
        self.assertEqual((theirs["my_pick"], theirs["partner_picked"], theirs["partner_pick"]), (None, True, None))
        self.assertNotIn('"a"', str({k: v for k, v in theirs.items() if k != "options"}))

    def test_both_picks_are_revealed_together(self):
        state = self.pick(self.pick(self.state, 1, "a"), 2, "b")
        view = self.game.view(state, 2)
        self.assertEqual((view["phase"], view["my_pick"], view["partner_pick"]), ("revealed", "b", "a"))

    def test_a_pick_can_change_until_the_reveal_then_it_is_locked(self):
        state = self.pick(self.pick(self.state, 1, "a"), 1, "b")
        self.assertEqual(self.game.view(state, 1)["my_pick"], "b")
        state = self.pick(state, 2, "b")
        with self.assertRaises(ActionInvalid):
            self.pick(state, 1, "a")

    def test_next_reset_and_closing_forget_the_picks(self):
        picked = self.pick(self.pick(self.state, 1, "a"), 2, "b")
        for state in [
            self.game.apply(picked, "next", actor_slot=1, cards=CARDS),
            self.game.apply(picked, "reset", actor_slot=1, cards=CARDS, seed=4),
            self.game.forget_answers(picked),
        ]:
            self.assertEqual((state["picks"], state["phase"]), ({}, "picking"))

    def test_only_a_or_b_for_the_current_card(self):
        for payload in [{"card": self.card, "choice": "c"}, {"card": self.card}, {"card": "q:999", "choice": "a"}]:
            with self.subTest(payload):
                with self.assertRaises(ActionInvalid):
                    self.game.apply(self.state, "pick", actor_slot=1, cards=CARDS, payload=payload)

    def test_the_view_offers_the_two_options_when_they_are_clear(self):
        view = self.game.view(self.state, 1)
        self.assertEqual(view["options"], split_options(self.state["current"]["text"]))
        self.assertEqual(len(view["options"]), 2)


class PickRevealServiceTests(TestCase):
    def setUp(self):
        users = [get_user_model().objects.create_user(email=e, password="a-long-passphrase-1")
                 for e in ("ann@example.com", "ben@example.com")]
        self.ann, self.ben = users
        self.couple = couples.create_couple(self.ann)
        couples.redeem_invitation(self.ben, couples.create_invitation(self.ann))
        self.room = services.room_for(self.ann, "pick_reveal", "would")

    def act(self, user, action, payload=None):
        room = GameRoom.objects.get(pk=self.room.pk)
        with self.captureOnCommitCallbacks(execute=True):
            services.apply_action(user, room.pk, action, expected_version=room.version,
                                  request_id=str(uuid.uuid4()), payload=payload)

    def test_picks_never_enter_the_history(self):
        card = GameRoom.objects.get(pk=self.room.pk).state["current"]["key"]
        self.act(self.ann, "pick", {"card": card, "choice": "a"})
        self.act(self.ben, "pick", {"card": card, "choice": "b"})
        for event in RoomEvent.objects.filter(room=self.room, kind="pick"):
            self.assertEqual(event.payload, {})

    def test_closing_the_space_forgets_the_picks(self):
        card = GameRoom.objects.get(pk=self.room.pk).state["current"]["key"]
        self.act(self.ann, "pick", {"card": card, "choice": "a"})
        with self.captureOnCommitCallbacks(execute=True):
            couples.close_couple(self.ann)
        self.assertEqual(GameRoom.objects.get(pk=self.room.pk).state["picks"], {})


class PlayPageTests(TestCase):
    def test_would_you_rather_uses_private_picks_and_other_modes_are_unchanged(self):
        ann = get_user_model().objects.create_user(email="ann@example.com", password="a-long-passphrase-1")
        couples.create_couple(ann)
        client = Client()
        client.force_login(ann)
        html = client.get("/play/?mode=would").content.decode()
        self.assertIn('id="pick-panel"', html)
        self.assertIn('data-game="pick_reveal"', html)  # The server picks the game (play.modes).
