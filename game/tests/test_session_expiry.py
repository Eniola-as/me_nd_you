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


class CheckSessionTests(TestCase):
    def test_expired_session_is_reported_but_not_deleted(self):
        make_session(days_inactive=31)
        response = self.client.get("/api/check-session/", {"secret": "sunflower"})
        self.assertEqual(response.json(), {"valid": False})
        self.assertEqual(CoupleSession.objects.count(), 1)

    def test_recent_session_is_valid(self):
        make_session(days_inactive=1)
        response = self.client.get("/api/check-session/", {"secret": "sunflower"})
        self.assertEqual(response.json(), {"valid": True})


class PurgeCommandTests(TestCase):
    def test_purge_deletes_only_inactive_sessions(self):
        make_session(days_inactive=31, secret="old-one")
        make_session(days_inactive=29, secret="recent")
        call_command("purge_inactive_sessions", stdout=StringIO())
        self.assertEqual(
            list(CoupleSession.objects.values_list("secret_word", flat=True)), ["recent"]
        )
