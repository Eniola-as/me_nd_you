"""Challenges are turn-based (owner, 2026-10-29): the player whose turn it is
draws the next challenge and the turn passes to the partner; the player
whose challenge is up may skip it as often as they like (it goes to the
bottom of the pile, the turn stays). Reset starts again."""

from django.test import SimpleTestCase

from play.games import ActionInvalid, get_game

CARDS = [{"key": f"q:{n}", "text": f"Challenge {n}.", "mode": "challenge", "custom": False} for n in range(4)]


class ChallengeTurnsTests(SimpleTestCase):
    def setUp(self):
        self.game = get_game("challenge_turns")
        self.state = self.game.start(CARDS, seed=11)
        self.first = self.state["turn"]

    def act(self, state, action, slot):
        return self.game.apply(state, action, actor_slot=slot, cards=CARDS)

    def test_it_is_the_challenge_modes_game(self):
        self.assertEqual(self.game.variants, {"challenge"})

    def test_a_random_player_goes_first_and_nothing_is_drawn_yet(self):
        self.assertIn(self.first, (1, 2))
        view = self.game.view(self.state, self.first)
        self.assertEqual((view["current"], view["your_turn"], view["remaining"]), (None, True, 4))

    def test_drawing_passes_the_turn(self):
        state = self.act(self.state, "draw", self.first)
        mine, theirs = self.game.view(state, self.first), self.game.view(state, 3 - self.first)
        self.assertTrue(mine["drawn_by_you"])
        self.assertFalse(mine["your_turn"])
        self.assertTrue(theirs["your_turn"])
        self.assertEqual(mine["current"], theirs["current"])

    def test_only_the_player_whose_turn_it_is_can_draw(self):
        with self.assertRaises(ActionInvalid):
            self.act(self.state, "draw", 3 - self.first)

    def test_unlimited_skips_for_the_drawer_only_and_the_turn_stays(self):
        state = self.act(self.state, "draw", self.first)
        drawn = state["current"]["key"]
        with self.assertRaises(ActionInvalid):
            self.act(state, "skip", 3 - self.first)
        for _ in range(6):  # More skips than cards: still fine.
            state = self.act(state, "skip", self.first)
        self.assertEqual(state["turn"], 3 - self.first)
        self.assertIn(drawn, state["pile"])

    def test_the_last_card_finishes_and_reset_starts_again(self):
        state, slot = self.state, self.first
        for _ in range(4):
            state = self.act(state, "draw", slot)
            slot = 3 - slot
        self.assertTrue(state["finished"])
        with self.assertRaises(ActionInvalid):
            self.act(state, "draw", slot)
        state = self.game.apply(state, "reset", actor_slot=1, cards=CARDS, seed=12)
        self.assertEqual((state["finished"], len(state["pile"]), state["current"]), (False, 4, None))

    def test_a_new_custom_challenge_joins_the_pile_once(self):
        card = {"key": "c:1", "text": "Ours.", "mode": "challenge", "custom": True}
        state = self.game.insert_card(self.state, card, seed=1)
        self.assertEqual(state["pile"].count("c:1"), 1)
        self.assertEqual(self.game.insert_card(state, card, seed=2), state)
