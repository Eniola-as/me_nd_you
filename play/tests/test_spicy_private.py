"""Spicy Only plays like Questions: each partner answers privately and both
answers are revealed together. Its deck, answers and progress are its own.
Next can warn when the partner would lose something, and the previous
question's text (never its answers) stays visible."""

import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from accounts.consents import CONSENT_KINDS, record_consents
from couples import services as couples
from play import modes, services
from play.models import RoomEvent


def make_couple(*emails):
    users = [get_user_model().objects.create_user(email=e, password="a-long-passphrase-1") for e in emails]
    for user in users:
        record_consents(user, CONSENT_KINDS)
    couple = couples.create_couple(users[0])
    for user in users[1:]:
        couples.redeem_invitation(user, couples.create_invitation(users[0]))
    return couple, users


class SpicySetup(TestCase):
    def setUp(self):
        self.couple, (self.ann, self.ben) = make_couple("ann@example.com", "ben@example.com")
        with mock.patch("play.modes.notify"), self.captureOnCommitCallbacks(execute=True):
            modes.start(self.ann, "spicy")
        self.room = services.room_for(self.ann, modes.MODE_GAMES["spicy"], "spicy")

    def act(self, user, action, **payload):
        self.room.refresh_from_db()
        services.apply_action(user, self.room.pk, action, self.room.version, str(uuid.uuid4()), payload)
        self.room.refresh_from_db()

    def card(self):
        return self.room.state["current"]["key"]

    def view(self, user):
        self.room.refresh_from_db()
        return services.snapshot(self.room, user)["state"]


class SpicyPrivacyTests(SpicySetup):
    def test_spicy_uses_private_answers(self):
        self.assertEqual(modes.MODE_GAMES["spicy"], "answer_reveal")
        self.assertEqual(self.room.game, "answer_reveal")

    def test_an_unrevealed_answer_never_reaches_the_partner(self):
        self.act(self.ann, "answer", card=self.card(), text="My secret spicy answer")
        ben_view = self.view(self.ben)
        self.assertTrue(ben_view["partner_answered"])
        self.assertIsNone(ben_view["partner_answer"])
        self.assertNotIn("My secret spicy answer", str(services.snapshot(self.room, self.ben)))

    def test_both_answers_are_revealed_together(self):
        self.act(self.ann, "answer", card=self.card(), text="Ann's")
        self.act(self.ben, "answer", card=self.card(), text="Ben's")
        self.assertEqual(self.view(self.ann)["partner_answer"], "Ben's")
        self.assertEqual(self.view(self.ben)["partner_answer"], "Ann's")

    def test_answers_stay_out_of_the_event_history(self):
        self.act(self.ann, "answer", card=self.card(), text="Never stored in history")
        self.assertNotIn("Never stored", str(list(RoomEvent.objects.values_list("payload", flat=True))))

    def test_outsiders_cannot_read_the_room(self):
        _, (cy,) = make_couple("cy@example.com")
        with self.assertRaises(services.Forbidden):
            services.snapshot(self.room, cy)
        with self.assertRaises(services.Forbidden):
            services.apply_action(cy, self.room.pk, "next", self.room.version, str(uuid.uuid4()))

    def test_spicy_and_questions_keep_separate_progress_and_answers(self):
        questions = services.room_for(self.ann, "answer_reveal", "questions")
        before = dict(questions.state)
        self.act(self.ann, "answer", card=self.card(), text="Spicy only")
        self.act(self.ann, "next")
        questions.refresh_from_db()
        self.assertEqual(questions.state["position"], before["position"])
        self.assertEqual(questions.state["answers"], {})
        self.assertNotEqual(questions.pk, self.room.pk)

    def test_the_play_page_shows_the_answer_box_for_spicy(self):
        client = Client()
        client.force_login(self.ann)
        html = client.get("/play/?mode=spicy").content.decode()
        self.assertIn('data-game="answer_reveal"', html)
        self.assertIn('id="answer-panel"', html)


class PlayPageTests(SpicySetup):
    def html(self):
        client = Client()
        client.force_login(self.ann)
        return client.get("/play/?mode=spicy").content.decode()

    def test_next_warns_only_when_the_partner_would_lose_something(self):
        html = self.html()
        self.assertIn('id="next-warning"', html)
        for words in ["hasn't seen your answers yet", "hasn't answered yet", "has answered. Moving on deletes"]:
            self.assertIn(words, html.replace("&#x27;", "'"))
        # The warning is advice: Next anyway still sends the real action.
        self.assertIn('getElementById("nextConfirm").addEventListener', html)

    def test_the_previous_question_shows_text_only(self):
        html = self.html()
        self.assertIn('id="previous-question"', html)
        self.assertIn("state.previous.text", html)

    def test_seen_is_sent_only_while_the_page_is_on_screen(self):
        html = self.html()
        self.assertIn('document.visibilityState !== "visible"', html)
        self.assertIn('room.act("seen", { card: answerCard })', html)


class PreviousQuestionTests(SpicySetup):
    def test_after_next_the_previous_question_text_is_kept_but_not_its_answers(self):
        first = self.room.state["current"]
        self.act(self.ann, "answer", card=self.card(), text="Ann's")
        self.act(self.ben, "answer", card=self.card(), text="Ben's")
        self.act(self.ann, "next")
        view = self.view(self.ben)
        self.assertEqual(view["previous"], {"key": first["key"], "text": first["text"]})
        self.assertNotIn("Ann's", str(self.room.state))
        self.assertNotIn("Ben's", str(self.room.state))

    def test_only_one_previous_question_is_kept(self):
        self.act(self.ann, "next")
        second = self.room.state["current"]
        self.act(self.ann, "next")
        self.assertEqual(self.view(self.ann)["previous"]["key"], second["key"])

    def test_reset_forgets_the_previous_question(self):
        self.act(self.ann, "next")
        self.act(self.ann, "reset")
        self.assertIsNone(self.view(self.ann)["previous"])


class SeenRevealTests(SpicySetup):
    def reveal(self):
        self.act(self.ann, "answer", card=self.card(), text="Ann's")
        self.act(self.ben, "answer", card=self.card(), text="Ben's")

    def test_the_partner_has_not_seen_the_answers_until_they_say_so(self):
        self.reveal()
        self.assertFalse(self.view(self.ann)["partner_seen"])
        self.act(self.ben, "seen", card=self.card())
        self.assertTrue(self.view(self.ann)["partner_seen"])
        self.assertFalse(self.view(self.ben)["partner_seen"])

    def test_seen_only_counts_for_revealed_answers_on_this_card(self):
        with self.assertRaises(services.Invalid):
            self.act(self.ben, "seen", card=self.card())
        self.reveal()
        with self.assertRaises(services.Invalid):
            self.act(self.ben, "seen", card="some-other-card")

    def test_seeing_twice_changes_nothing(self):
        self.reveal()
        self.act(self.ben, "seen", card=self.card())
        state = dict(self.room.state)
        self.act(self.ben, "seen", card=self.card())
        self.assertEqual(self.room.state["seen"], state["seen"])

    def test_next_still_works_and_clears_seen(self):
        self.reveal()
        self.act(self.ann, "next")
        self.assertFalse(self.view(self.ann)["partner_seen"])
        self.assertEqual(self.room.state["answers"], {})
