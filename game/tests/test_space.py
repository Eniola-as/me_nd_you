"""Couple spaces: only a signed-in, active member of a couple can load its
questions or add to them (game rooms: play/tests/test_consumers.py).
Nothing in the request (a couple id, an old secret word) grants access by
itself."""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import Client, TestCase

from couples import services
from game.models import CoupleSession, CustomQuestion

QUESTIONS = "/api/space/questions/questions/"
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


class SpaceQuestionsAccessTests(TestCase):
    def setUp(self):
        cache.clear()
        self.couple, self.ann, self.ben = make_couple("ann@example.com", "ben@example.com")
        CustomQuestion.objects.create(space=self.couple, text="Only ours?", mode="questions")

    def load_as(self, user):
        client = Client()
        if user:
            client.force_login(user)
        return client.get(QUESTIONS)

    def test_anonymous_visitors_are_refused(self):
        self.assertEqual(self.load_as(None).status_code, 403)

    def test_signed_in_user_without_a_couple_is_refused(self):
        response = self.load_as(make_user("solo@example.com"))
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("Only ours?", response.content.decode())

    def test_both_members_see_their_couples_questions(self):
        for user in (self.ann, self.ben):
            with self.subTest(user=user.email):
                texts = [q["text"] for q in self.load_as(user).json()]
                self.assertIn("Only ours?", texts)
                self.assertGreater(len(texts), 100)

    def test_another_couple_never_sees_them(self):
        _, cy, _ = make_couple("cy@example.com")
        self.assertNotIn("Only ours?", [q["text"] for q in self.load_as(cy).json()])

    def test_query_parameters_grant_nothing(self):
        CoupleSession.objects.create(partner1_name="Ann", partner2_name="Ben", secret_word="old-secret")
        client = Client()
        for params in [{"secret": "old-secret"}, {"couple": str(self.couple.id)}]:
            with self.subTest(params=params):
                self.assertEqual(client.get(QUESTIONS, params).status_code, 403)

    def test_unknown_mode_is_rejected(self):
        client = Client()
        client.force_login(self.ann)
        self.assertEqual(client.get("/api/space/questions/not-a-mode/").status_code, 400)


class SpaceCustomQuestionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.couple, self.ann, self.ben = make_couple("ann@example.com", "ben@example.com")
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.ann)
        self.client.get("/play/")  # Sets the CSRF cookie.
        self.csrf = self.client.cookies["csrftoken"].value

    def post(self, body, csrf=True, client=None):
        headers = {"HTTP_X_CSRFTOKEN": self.csrf} if csrf else {}
        return (client or self.client).post(ADD, body, content_type="application/json", **headers)

    def test_member_adds_a_question_to_their_couple(self):
        response = self.post({"text": "  Ours now?  ", "mode": "questions"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"text": "Ours now?", "mode": "questions", "is_custom": True})
        question = CustomQuestion.objects.get()
        self.assertEqual((question.space, question.couple), (self.couple, None))

    def test_partner_sees_it_immediately(self):
        partner = Client()
        partner.force_login(self.ben)
        partner.get(QUESTIONS)  # Fill the cache before the add.
        self.post({"text": "Shared?", "mode": "questions"})
        self.assertIn("Shared?", [q["text"] for q in partner.get(QUESTIONS).json()])

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
        outsider.get("/play/")
        response = outsider.post(ADD, {"text": "Mine?", "mode": "questions"}, content_type="application/json",
                                 HTTP_X_CSRFTOKEN=outsider.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(CustomQuestion.objects.exists())

    def test_invalid_input_is_rejected(self):
        for body in [{"text": "", "mode": "questions"}, {"text": "x" * 501, "mode": "questions"},
                     {"text": "Ok?", "mode": "nope"}]:
            with self.subTest(body=str(body)[:40]):
                self.assertEqual(self.post(body).status_code, 400)
        self.assertFalse(CustomQuestion.objects.exists())


class CustomQuestionOwnerConstraintTests(TestCase):
    def test_a_question_belongs_to_exactly_one_owner(self):
        couple, _, _ = make_couple("ann@example.com")
        legacy = CoupleSession.objects.create(partner1_name="A", partner2_name="B", secret_word="s3cret")
        for owners in [{}, {"space": couple, "couple": legacy}]:
            with self.subTest(owners=list(owners)):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    CustomQuestion.objects.create(text="Q?", mode="questions", **owners)
