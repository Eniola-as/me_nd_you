"""Per-client rate limits on the endpoints that take a secret word (audit
A2 and A8). Counts live in Django's default in-memory cache, so they are
per process; a scaled deployment needs a shared cache for them to hold."""

from django.core.cache import cache
from django.test import TestCase

from game.models import CoupleSession, CustomQuestion

QUESTIONS_PER_MINUTE = 30
CUSTOM_QUESTIONS_PER_MINUTE = 10


class RateLimitTestCase(TestCase):
    def setUp(self):
        cache.clear()
        CoupleSession.objects.create(
            partner1_name="Ann", partner2_name="Ben", secret_word="sunflower"
        )

    def load_questions(self, secret="sunflower", **headers):
        return self.client.get("/api/questions/questions/", {"secret": secret}, **headers)

    def add_question(self, n, **headers):
        return self.client.post(
            "/api/add-custom-question/",
            {"secret": "sunflower", "text": f"Question {n}?", "mode": "questions"},
            content_type="application/json",
            **headers,
        )


class QuestionLoadingLimitTests(RateLimitTestCase):
    def test_guessing_secrets_is_throttled(self):
        statuses = [
            self.load_questions(secret=f"guess-{n}").status_code
            for n in range(QUESTIONS_PER_MINUTE + 1)
        ]
        self.assertNotIn(429, statuses[:QUESTIONS_PER_MINUTE])
        self.assertEqual(statuses[-1], 429)

    def test_faked_forwarded_for_does_not_escape_the_limit(self):
        statuses = [
            self.load_questions(secret=f"guess-{n}", HTTP_X_FORWARDED_FOR=f"10.1.0.{n}").status_code
            for n in range(QUESTIONS_PER_MINUTE + 1)
        ]
        self.assertEqual(statuses[-1], 429)

    def test_throttled_response_reveals_nothing_about_the_secret(self):
        for _ in range(QUESTIONS_PER_MINUTE):
            self.load_questions()
        response = self.load_questions()
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("sunflower", response.content.decode())
        self.assertNotIn("question", response.content.decode().lower().replace("request", ""))

    def test_normal_play_stays_well_under_the_limit(self):
        # A page load and a few resets in a minute.
        statuses = [self.load_questions().status_code for _ in range(5)]
        self.assertEqual(set(statuses), {200})


class CustomQuestionLimitTests(RateLimitTestCase):
    def test_adding_questions_is_throttled(self):
        statuses = [self.add_question(n).status_code for n in range(CUSTOM_QUESTIONS_PER_MINUTE + 1)]
        self.assertEqual(set(statuses[:CUSTOM_QUESTIONS_PER_MINUTE]), {201})
        self.assertEqual(statuses[-1], 429)

    def test_throttled_request_saves_nothing(self):
        for n in range(CUSTOM_QUESTIONS_PER_MINUTE + 1):
            self.add_question(n)
        self.assertEqual(CustomQuestion.objects.count(), CUSTOM_QUESTIONS_PER_MINUTE)

    def test_faked_forwarded_for_does_not_escape_the_limit(self):
        statuses = [
            self.add_question(n, HTTP_X_FORWARDED_FOR=f"10.2.0.{n}").status_code
            for n in range(CUSTOM_QUESTIONS_PER_MINUTE + 1)
        ]
        self.assertEqual(statuses[-1], 429)


class SeparateLimitTests(RateLimitTestCase):
    def test_each_endpoint_has_its_own_budget(self):
        for n in range(CUSTOM_QUESTIONS_PER_MINUTE):
            self.add_question(n)
        self.assertEqual(self.load_questions().status_code, 200)
