from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase

from game.models import CoupleSession, CustomQuestion

URL = "/api/add-custom-question/"


class CustomQuestionTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.ours = CoupleSession.objects.create(
            partner1_name="Ann", partner2_name="Ben", secret_word="sunflower"
        )
        self.theirs = CoupleSession.objects.create(
            partner1_name="Cy", partner2_name="Di", secret_word="moonlight"
        )

    def submit(self, client=None, **body):
        payload = {"secret": "sunflower", "text": "What made you smile today?", "mode": "questions"}
        payload.update(body)
        payload = {k: v for k, v in payload.items() if v is not None}
        return (client or self.client).post(URL, payload, content_type="application/json")

    def question_texts(self, secret, mode="questions"):
        response = self.client.get(f"/api/questions/{mode}/", {"secret": secret})
        return [q["text"] for q in response.json()]


class SubmissionTests(CustomQuestionTestCase):
    def test_valid_question_is_saved_for_the_couple(self):
        response = self.submit()
        self.assertEqual(response.status_code, 201)
        question = CustomQuestion.objects.get()
        self.assertEqual(question.couple, self.ours)
        self.assertEqual((question.text, question.mode), ("What made you smile today?", "questions"))

    def test_response_has_only_the_question_list_shape(self):
        response = self.submit()
        self.assertEqual(
            response.json(),
            {"text": "What made you smile today?", "mode": "questions", "is_custom": True},
        )
        body = response.content.decode()
        self.assertNotIn(str(self.ours.pk), body)
        self.assertNotIn("sunflower", body)

    def test_text_is_trimmed(self):
        self.submit(text="   Padded question?  ")
        self.assertEqual(CustomQuestion.objects.get().text, "Padded question?")

    def test_new_question_appears_in_an_already_cached_list(self):
        self.question_texts("sunflower")  # Fill the cache first.
        self.submit(text="Brand new custom question?")
        self.assertIn("Brand new custom question?", self.question_texts("sunflower"))


class InvalidInputTests(CustomQuestionTestCase):
    def assert_rejected(self, field, **body):
        response = self.submit(**body)
        self.assertEqual(response.status_code, 400)
        self.assertIn(field, response.json())
        self.assertFalse(CustomQuestion.objects.exists())

    def test_blank_text_is_rejected(self):
        self.assert_rejected("text", text="")

    def test_whitespace_only_text_is_rejected(self):
        self.assert_rejected("text", text="   \n\t ")

    def test_text_over_500_characters_is_rejected(self):
        self.assert_rejected("text", text="x" * 501)

    def test_text_of_exactly_500_characters_is_accepted(self):
        self.assertEqual(self.submit(text="x" * 500).status_code, 201)

    def test_unknown_mode_is_rejected(self):
        self.assert_rejected("mode", mode="not-a-mode")

    def test_missing_secret_is_rejected(self):
        self.assert_rejected("secret", secret=None)

    def test_non_string_text_is_rejected(self):
        self.assert_rejected("text", text=["a", "list"])


class OwnershipTests(CustomQuestionTestCase):
    def test_unknown_secret_gets_a_generic_404(self):
        response = self.submit(secret="no-such-secret")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("no-such-secret", response.content.decode())
        self.assertFalse(CustomQuestion.objects.exists())

    def test_client_supplied_couple_id_is_ignored(self):
        response = self.submit(couple=str(self.theirs.pk))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(CustomQuestion.objects.get().couple, self.ours)

    def test_other_unexpected_fields_are_ignored(self):
        response = self.submit(id=999, created_at="2000-01-01T00:00:00Z", is_custom=False)
        self.assertEqual(response.status_code, 201)
        question = CustomQuestion.objects.get()
        self.assertNotEqual(question.pk, 999)
        self.assertNotEqual(question.created_at.year, 2000)

    def test_a_couples_question_is_never_shown_to_another_couple(self):
        self.submit(text="Only for Ann and Ben?")
        self.assertIn("Only for Ann and Ben?", self.question_texts("sunflower"))
        self.assertNotIn("Only for Ann and Ben?", self.question_texts("moonlight"))


class CsrfTests(CustomQuestionTestCase):
    def test_browser_logged_into_admin_can_still_submit(self):
        admin = get_user_model().objects.create_superuser(email="a@example.com", password="pw-for-tests")
        client = Client(enforce_csrf_checks=True)
        client.force_login(admin)
        self.assertEqual(self.submit(client=client).status_code, 201)

    def test_login_endpoint_still_requires_csrf_for_logged_in_browsers(self):
        # Out of scope for this fix: login keeps its current behaviour.
        admin = get_user_model().objects.create_superuser(email="a@example.com", password="pw-for-tests")
        client = Client(enforce_csrf_checks=True)
        client.force_login(admin)
        response = client.post(
            "/api/login/",
            {"partner1_name": "Ann", "partner2_name": "Ben", "secret_word": "sunflower"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)


class PlayPagePayloadTests(TestCase):
    def test_play_page_sends_the_secret_not_a_couple_id(self):
        html = self.client.get("/play/").content.decode()
        self.assertIn("JSON.stringify({ secret, text, mode })", html)
        self.assertNotIn("couple: secret", html)
