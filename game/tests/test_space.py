"""Couple spaces: only a signed-in, active member of a couple can add to its
questions (game rooms: play/tests/test_consumers.py). Nothing in the
request (a couple id) grants access by itself."""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import Client, TestCase

from couples import services
from game.models import CustomQuestion
from play.cards import DatabaseCards

ADD = "/api/space/custom-questions/"


def make_user(email):
    return get_user_model().objects.create_user(email=email, password="a-long-passphrase-1")


def make_couple(email_a, email_b=None):
    a = make_user(email_a)
    couple = services.create_couple(a)
    b = None
    if email_b:
        b = make_user(email_b)
        services.redeem_invitation(b, services.create_invitation(a))
    return couple, a, b


def card_texts(couple, mode="questions"):
    return [card["text"] for card in DatabaseCards(couple, mode).all()]


class SpaceCustomQuestionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.couple, self.ann, self.ben = make_couple("ann@example.com", "ben@example.com")
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.ann)
        self.client.get("/space/")  # Sets the CSRF cookie.
        self.csrf = self.client.cookies["csrftoken"].value

    def post(self, body, csrf=True, client=None):
        headers = {"HTTP_X_CSRFTOKEN": self.csrf} if csrf else {}
        return (client or self.client).post(ADD, body, content_type="application/json", **headers)

    def test_member_adds_a_question_to_their_couple(self):
        response = self.post({"text": "  Ours now?  ", "mode": "questions"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"text": "Ours now?", "mode": "questions", "is_custom": True})
        self.assertEqual(CustomQuestion.objects.get().space, self.couple)

    def test_it_joins_this_couples_cards_only(self):
        other, _, _ = make_couple("cy@example.com")
        self.post({"text": "Shared?", "mode": "questions"})
        self.assertIn("Shared?", card_texts(self.couple))
        self.assertNotIn("Shared?", card_texts(other))

    def test_csrf_token_is_required(self):
        self.assertEqual(self.post({"text": "No token?", "mode": "questions"}, csrf=False).status_code, 403)
        self.assertFalse(CustomQuestion.objects.exists())

    def test_client_supplied_couple_is_ignored(self):
        other, _, _ = make_couple("cy@example.com")
        self.post({"text": "Where?", "mode": "questions", "couple": str(other.id), "space": str(other.id)})
        self.assertEqual(CustomQuestion.objects.get().space, self.couple)

    def test_non_member_cannot_add(self):
        outsider = Client(enforce_csrf_checks=True)
        outsider.force_login(make_user("solo@example.com"))
        outsider.get("/space/")
        response = outsider.post(ADD, {"text": "Mine?", "mode": "questions"}, content_type="application/json",
                                 HTTP_X_CSRFTOKEN=outsider.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(CustomQuestion.objects.exists())

    def test_anonymous_visitors_cannot_add(self):
        self.assertEqual(Client().post(ADD, {"text": "Hi?", "mode": "questions"},
                                       content_type="application/json").status_code, 403)

    def test_invalid_input_is_rejected(self):
        for body in [{"text": "", "mode": "questions"}, {"text": "x" * 501, "mode": "questions"},
                     {"text": "Ok?", "mode": "nope"}]:
            with self.subTest(body=str(body)[:40]):
                self.assertEqual(self.post(body).status_code, 400)
        self.assertFalse(CustomQuestion.objects.exists())


class CustomQuestionOwnerTests(TestCase):
    def test_every_question_belongs_to_a_space(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            CustomQuestion.objects.create(text="Q?", mode="questions")
