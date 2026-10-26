from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.conf import settings
from django.test import TestCase, override_settings

from game.models import CoupleSession


def post_login(client, p1="Ann", p2="Ben", secret="sunflower"):
    return client.post(
        "/api/login/",
        {"partner1_name": p1, "partner2_name": p2, "secret_word": secret},
        content_type="application/json",
    )


def login(client, p1="Ann", p2="Ben", secret="sunflower"):
    # Reset the login rate limit so tests don't throttle each other.
    cache.clear()
    return client.post(
        "/api/login/",
        {"partner1_name": p1, "partner2_name": p2, "secret_word": secret},
        content_type="application/json",
    )


class LoginValidationTests(TestCase):
    def assert_rejected(self, field, **kwargs):
        response = login(self.client, **kwargs)
        self.assertEqual(response.status_code, 400)
        self.assertIn(field, response.json()["errors"])
        self.assertEqual(CoupleSession.objects.count(), 0)

    def test_non_string_name_is_rejected_not_a_server_error(self):
        self.assert_rejected("partner1", p1=1)

    def test_identical_names_are_rejected(self):
        self.assert_rejected("partner2", p1="Ann", p2=" ann ")

    def test_short_secret_is_rejected(self):
        self.assert_rejected("secret", secret="abc")

    def test_overlong_name_is_rejected(self):
        self.assert_rejected("partner1", p1="A" * 101)

    def test_name_with_digits_is_rejected(self):
        self.assert_rejected("partner2", p2="B3n")

    def test_real_world_names_are_accepted(self):
        for p1, p2 in [("José", "Zoë"), ("Anne-Marie", "O'Neil"), ("李雷", "Дмитрий")]:
            with self.subTest(p1=p1, p2=p2):
                response = login(self.client, p1=p1, p2=p2, secret=f"secret-{p1}")
                self.assertEqual(response.status_code, 200, response.content)


class LoginRateLimitTests(TestCase):
    def test_repeated_guesses_are_throttled(self):
        cache.clear()
        statuses = [post_login(self.client, secret=f"guess-{n}").status_code for n in range(11)]
        self.assertNotIn(429, statuses[:10])
        self.assertEqual(statuses[10], 429)


class ForwardedForSpoofingTests(TestCase):
    """A client must not escape the login limit by inventing X-Forwarded-For."""

    def attempts(self, forwarded_for):
        cache.clear()
        return [
            self.client.post(
                "/api/login/",
                {"partner1_name": "Eve", "partner2_name": "Mal", "secret_word": f"try-{n}"},
                content_type="application/json",
                HTTP_X_FORWARDED_FOR=forwarded_for(n),
            ).status_code
            for n in range(11)
        ]

    def test_rotating_forwarded_for_is_still_throttled_by_default(self):
        # Uses the project's own setting: no trusted proxies configured.
        self.assertEqual(self.attempts(lambda n: f"10.0.0.{n}")[-1], 429)

    @override_settings(REST_FRAMEWORK={**settings.REST_FRAMEWORK, "NUM_PROXIES": 1})
    def test_with_one_trusted_proxy_only_the_proxy_added_address_counts(self):
        # The proxy appends the real client address; anything before it is
        # client-supplied and must be ignored.
        self.assertEqual(self.attempts(lambda n: f"10.0.0.{n}, 203.0.113.7")[-1], 429)

    @override_settings(REST_FRAMEWORK={**settings.REST_FRAMEWORK, "NUM_PROXIES": 1})
    def test_with_one_trusted_proxy_different_clients_have_separate_limits(self):
        statuses = self.attempts(lambda n: f"203.0.113.{n}")
        self.assertNotIn(429, statuses)


class NameCasingTests(TestCase):
    def test_names_are_stored_as_typed(self):
        login(self.client, p1="McDonald", p2="de la Cruz")
        session = CoupleSession.objects.get()
        self.assertEqual(
            {session.partner1_name, session.partner2_name}, {"de la Cruz", "McDonald"}
        )


class SecretUniquenessTests(TestCase):
    def test_two_sessions_cannot_share_a_secret(self):
        CoupleSession.objects.create(
            partner1_name="Ann", partner2_name="Ben", secret_word="sunflower"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            CoupleSession.objects.create(
                partner1_name="Cy", partner2_name="Di", secret_word="sunflower"
            )

    def test_returning_couple_logs_into_existing_session(self):
        first = login(self.client)
        second = login(self.client, p1="ben", p2="ANN")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["session"]["id"], second.json()["session"]["id"])
        self.assertEqual(CoupleSession.objects.count(), 1)
