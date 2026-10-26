from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from game.models import CoupleSession

from .test_login import login


def make_session(days_inactive, secret="sunflower"):
    session = CoupleSession.objects.create(
        partner1_name="Ann", partner2_name="Ben", secret_word=secret
    )
    CoupleSession.objects.filter(pk=session.pk).update(
        last_active=timezone.now() - timedelta(days=days_inactive)
    )
    return session


class ActivityTests(TestCase):
    def assert_recently_active(self, session):
        session.refresh_from_db()
        self.assertLess(timezone.now() - session.last_active, timedelta(minutes=1))

    def test_logging_in_counts_as_activity(self):
        session = make_session(days_inactive=10)
        login(self.client)
        self.assert_recently_active(session)

    def test_loading_questions_counts_as_activity(self):
        session = make_session(days_inactive=10)
        self.client.get("/api/questions/questions/", {"secret": "sunflower"})
        self.assert_recently_active(session)


class CheckSessionRemovedTests(TestCase):
    """check-session answered "does this secret exist?" without any rate
    limit (audit A1) and nothing used it, so it was removed."""

    def test_endpoint_no_longer_exists(self):
        make_session(days_inactive=1)
        response = self.client.get("/api/check-session/", {"secret": "sunflower"})
        self.assertEqual(response.status_code, 404)

    def test_play_page_no_longer_calls_it(self):
        html = self.client.get("/play/").content.decode()
        self.assertNotIn("check-session", html)
        self.assertNotIn("checkSession", html)


class PurgeCommandTests(TestCase):
    def test_purge_deletes_only_inactive_sessions(self):
        make_session(days_inactive=31, secret="old-one")
        make_session(days_inactive=29, secret="recent")
        call_command("purge_inactive_sessions", stdout=StringIO())
        self.assertEqual(
            list(CoupleSession.objects.values_list("secret_word", flat=True)), ["recent"]
        )
