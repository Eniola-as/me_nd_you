"""Game types are pure functions: these tests need no database."""

from django.test import SimpleTestCase

from play.games import ActionInvalid, get_game

CARDS = [{"key": f"q:{n}", "text": f"Question {n}?", "mode": "questions", "custom": False} for n in range(5)]


class QuestionsGameTests(SimpleTestCase):
    def setUp(self):
        self.game = get_game("questions")
        self.state = self.game.start(CARDS, seed=7)

    def test_start_shows_the_first_card_of_a_shuffled_deck(self):
        self.assertEqual(sorted(self.state["deck"]), sorted(c["key"] for c in CARDS))
        self.assertEqual(self.state["position"], 0)
        self.assertEqual(self.state["current"]["key"], self.state["deck"][0])

    def test_same_seed_same_order(self):
        self.assertEqual(self.game.start(CARDS, seed=7)["deck"], self.state["deck"])
        self.assertNotEqual(self.game.start(CARDS, seed=8)["deck"], self.state["deck"])

    def test_next_moves_exactly_one_card(self):
        state = self.game.apply(self.state, "next", actor_slot=1, cards=CARDS)
        self.assertEqual(state["position"], 1)
        self.assertEqual(state["current"]["key"], self.state["deck"][1])

    def test_end_of_deck_finishes_and_next_is_refused(self):
        state = self.state
        for _ in range(len(CARDS) - 1):
            state = self.game.apply(state, "next", actor_slot=1, cards=CARDS)
        state = self.game.apply(state, "next", actor_slot=2, cards=CARDS)
        self.assertTrue(state["finished"])
        self.assertIsNone(state["current"])
        with self.assertRaises(ActionInvalid):
            self.game.apply(state, "next", actor_slot=1, cards=CARDS)

    def test_reset_starts_a_new_deck(self):
        state = self.game.apply(self.state, "next", actor_slot=1, cards=CARDS)
        reset = self.game.apply(state, "reset", actor_slot=2, cards=CARDS, seed=99)
        self.assertEqual(reset["position"], 0)
        self.assertEqual(reset["seed"], 99)
        self.assertFalse(reset["finished"])

    def test_unknown_action_is_refused(self):
        with self.assertRaises(ActionInvalid):
            self.game.apply(self.state, "jump", actor_slot=1, cards=CARDS)

    def test_inserted_card_comes_later_exactly_once(self):
        card = {"key": "c:1", "text": "Ours?", "mode": "questions", "custom": True}
        state = self.game.insert_card(self.state, card, seed=3)
        upcoming = state["deck"][state["position"] + 1:]
        self.assertEqual(upcoming.count("c:1"), 1)
        self.assertEqual(state["deck"][: state["position"] + 1], self.state["deck"][: self.state["position"] + 1])
        self.assertEqual(self.game.insert_card(state, card, seed=4)["deck"].count("c:1"), 1)

    def test_view_hides_the_upcoming_order(self):
        view = self.game.view(self.state, viewer_slot=1)
        self.assertNotIn("deck", view)
        self.assertEqual(view["current"]["text"], self.state["current"]["text"])
        self.assertEqual(view["remaining"], len(CARDS) - 1)


class AnswerRevealGameTests(SimpleTestCase):
    def setUp(self):
        self.game = get_game("answer_reveal")
        self.state = self.game.start(CARDS, seed=7)

    def answer(self, state, slot, text):
        return self.game.apply(state, "answer", actor_slot=slot, cards=CARDS, payload={"text": text})

    def test_partner_answer_is_hidden_until_both_have_answered(self):
        state = self.answer(self.state, 1, "My private answer")
        partner_view = self.game.view(state, viewer_slot=2)
        self.assertNotIn("My private answer", str(partner_view))
        self.assertTrue(partner_view["partner_answered"])
        self.assertEqual(self.game.view(state, viewer_slot=1)["my_answer"], "My private answer")

    def test_answers_are_revealed_to_both_once_both_answered(self):
        state = self.answer(self.answer(self.state, 1, "Mine"), 2, "Yours")
        self.assertEqual(state["phase"], "revealed")
        self.assertEqual(self.game.view(state, viewer_slot=1)["partner_answer"], "Yours")
        self.assertEqual(self.game.view(state, viewer_slot=2)["partner_answer"], "Mine")

    def test_next_only_after_reveal_and_clears_answers(self):
        with self.assertRaises(ActionInvalid):
            self.game.apply(self.state, "next", actor_slot=1, cards=CARDS)
        state = self.answer(self.answer(self.state, 1, "Mine"), 2, "Yours")
        state = self.game.apply(state, "next", actor_slot=1, cards=CARDS)
        self.assertEqual((state["phase"], state["answers"]), ("answering", {}))

    def test_answers_are_validated(self):
        for text in ["", "   ", "x" * 501, 5]:
            with self.subTest(text=str(text)[:10]), self.assertRaises(ActionInvalid):
                self.game.apply(self.state, "answer", actor_slot=1, cards=CARDS, payload={"text": text})

    def test_answer_cannot_change_after_reveal(self):
        state = self.answer(self.answer(self.state, 1, "Mine"), 2, "Yours")
        with self.assertRaises(ActionInvalid):
            self.answer(state, 1, "Changed")
