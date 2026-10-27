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
    """Questions mode: each partner may answer the card privately; answers
    are revealed once both have answered. Answering is optional."""

    def setUp(self):
        self.game = get_game("answer_reveal")
        self.state = self.game.start(CARDS, seed=7)

    def answer(self, state, slot, text, card=None):
        payload = {"text": text, "card": card or state["current"]["key"]}
        return self.game.apply(state, "answer", actor_slot=slot, cards=CARDS, payload=payload)

    def next(self, state, slot=1):
        return self.game.apply(state, "next", actor_slot=slot, cards=CARDS)

    def test_it_is_questions_mode_with_partner_names(self):
        self.assertEqual(self.game.variants, {"questions"})
        self.assertTrue(self.game.shows_names)

    def test_partner_answer_is_hidden_until_both_have_answered(self):
        state = self.answer(self.state, 1, "My private answer")
        partner_view = self.game.view(state, viewer_slot=2)
        self.assertNotIn("My private answer", str(partner_view))
        self.assertTrue(partner_view["partner_answered"])
        self.assertIsNone(partner_view["partner_answer"])
        self.assertEqual(self.game.view(state, viewer_slot=1)["my_answer"], "My private answer")

    def test_answers_are_revealed_to_both_once_both_answered(self):
        state = self.answer(self.answer(self.state, 1, "Mine"), 2, "Yours")
        self.assertEqual(state["phase"], "revealed")
        self.assertEqual(self.game.view(state, viewer_slot=1)["partner_answer"], "Yours")
        self.assertEqual(self.game.view(state, viewer_slot=2)["partner_answer"], "Mine")

    def test_answering_is_optional_next_works_at_any_time(self):
        state = self.next(self.state)
        self.assertEqual(state["position"], 1)
        self.assertEqual((state["phase"], state["answers"]), ("answering", {}))

    def test_a_lone_answer_is_deleted_by_next(self):
        state = self.next(self.answer(self.state, 1, "Only mine"), slot=2)
        self.assertNotIn("Only mine", str(state))

    def test_revealed_answers_are_deleted_by_next_and_reset(self):
        revealed = self.answer(self.answer(self.state, 1, "Mine"), 2, "Yours")
        for state in [self.next(revealed), self.game.apply(revealed, "reset", actor_slot=1, cards=CARDS, seed=3)]:
            self.assertNotIn("Mine", str(state))
            self.assertEqual((state["phase"], state["answers"]), ("answering", {}))

    def test_you_can_change_your_answer_until_the_reveal(self):
        state = self.answer(self.answer(self.state, 1, "First"), 1, "Second")
        self.assertEqual(self.game.view(state, viewer_slot=1)["my_answer"], "Second")
        self.assertNotIn("First", str(state))
        state = self.answer(state, 2, "Yours")
        with self.assertRaises(ActionInvalid):
            self.answer(state, 1, "Changed")

    def test_an_answer_for_a_card_that_moved_on_is_refused(self):
        old_card = self.state["current"]["key"]
        state = self.next(self.state)
        with self.assertRaises(ActionInvalid):
            self.answer(state, 1, "Late", card=old_card)

    def test_answers_are_validated_up_to_500_characters(self):
        self.answer(self.state, 1, "x" * 500)
        for text in ["", "   ", "x" * 501, 5, None]:
            with self.subTest(text=str(text)[:10]), self.assertRaises(ActionInvalid):
                self.answer(self.state, 1, text)

    def test_no_answers_once_the_deck_is_finished(self):
        state = self.state
        for _ in CARDS:
            state = self.next(state)
        with self.assertRaises(ActionInvalid):
            self.game.apply(state, "answer", actor_slot=1, cards=CARDS, payload={"text": "Hi", "card": None})

    def test_forgetting_answers_keeps_the_game(self):
        state = self.answer(self.next(self.state), 1, "Mine")
        forgotten = self.game.forget_answers(state)
        self.assertEqual((forgotten["answers"], forgotten["phase"]), ({}, "answering"))
        self.assertEqual((forgotten["deck"], forgotten["position"]), (state["deck"], state["position"]))
