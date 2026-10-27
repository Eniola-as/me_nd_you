"""Sign-in attempts are limited per client, and a client can't escape the
limit by inventing X-Forwarded-For addresses."""

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings


class ForwardedForSpoofingTests(TestCase):
    def attempts(self, forwarded_for):
        cache.clear()
        return [
            self.client.post(
                "/accounts/login/",
                {"username": "eve@example.com", "password": f"guess-{n}"},
                HTTP_X_FORWARDED_FOR=forwarded_for(n),
            ).status_code
            for n in range(11)
        ]

    def test_rotating_forwarded_for_is_still_throttled_by_default(self):
        # Uses the project's own setting: no trusted proxies configured.
        statuses = self.attempts(lambda n: f"10.0.0.{n}")
        self.assertNotIn(429, statuses[:10])
        self.assertEqual(statuses[-1], 429)

    @override_settings(REST_FRAMEWORK={**settings.REST_FRAMEWORK, "NUM_PROXIES": 1})
    def test_with_one_trusted_proxy_only_the_proxy_added_address_counts(self):
        # The proxy appends the real client address; anything before it is
        # client-supplied and must be ignored.
        self.assertEqual(self.attempts(lambda n: f"10.0.0.{n}, 203.0.113.7")[-1], 429)

    @override_settings(REST_FRAMEWORK={**settings.REST_FRAMEWORK, "NUM_PROXIES": 1})
    def test_with_one_trusted_proxy_different_clients_have_separate_limits(self):
        self.assertNotIn(429, self.attempts(lambda n: f"203.0.113.{n}"))
