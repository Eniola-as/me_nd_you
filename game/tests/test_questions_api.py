from django.core.cache import cache
from django.test import TestCase

from game.models import CoupleSession, CustomQuestion, Question


class QuestionsApiTests(TestCase):
    secret = "sunflower-secret"

    def setUp(self):
        cache.clear()
        self.couple = CoupleSession.objects.create(
            partner1_name="Ann", partner2_name="Ben", secret_word=self.secret
        )

    def fetch(self, mode="questions"):
        return self.client.get(f"/api/questions/{mode}/", {"secret": self.secret})

    def texts(self, mode="questions"):
        return [q["text"] for q in self.fetch(mode).json()]

    def test_unknown_mode_is_rejected(self):
        self.assertEqual(self.fetch("not-a-mode").status_code, 400)

    def test_new_admin_question_appears_without_waiting_for_cache_expiry(self):
        self.texts()
        Question.objects.create(text="Brand new prompt?", mode="questions")
        self.assertIn("Brand new prompt?", self.texts())

    def test_new_custom_question_appears_without_waiting_for_cache_expiry(self):
        self.texts()
        CustomQuestion.objects.create(couple=self.couple, text="Our own?", mode="questions")
        self.assertIn("Our own?", self.texts())

    def test_cache_keys_do_not_contain_the_secret(self):
        self.texts()
        self.assertFalse(any(self.secret in key for key in cache._cache))

    def test_order_is_stable_because_the_client_shuffles(self):
        first = self.texts()
        cache.clear()
        self.assertEqual(first, self.texts())

    def test_custom_question_duplicating_a_prompt_is_listed_once(self):
        existing = Question.objects.filter(mode="questions").first().text
        CustomQuestion.objects.create(couple=self.couple, text=existing, mode="questions")
        self.assertEqual(self.texts().count(existing), 1)
