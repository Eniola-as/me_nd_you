"""Test-runner support (used only by `manage.py test`).

Hundreds of tests create users directly and sign them in. Real new users
give their consents at sign-up, so the runner gives every user a test
creates the current consents too. Tests about consent itself switch this off
with `without_auto_consent()`."""

from contextlib import contextmanager

from django.db.models.signals import post_save
from django.test.runner import DiscoverRunner

_auto_consent = {"on": True}


@contextmanager
def without_auto_consent():
    previous = _auto_consent["on"]
    _auto_consent["on"] = False
    try:
        yield
    finally:
        _auto_consent["on"] = previous


def _give_current_consents(sender, instance, created, raw=False, **kwargs):
    if created and not raw and _auto_consent["on"]:
        from .consents import CONSENT_KINDS, record_consents

        record_consents(instance, CONSENT_KINDS)


class ConsentingTestRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        from django.contrib.auth import get_user_model

        post_save.connect(_give_current_consents, sender=get_user_model(),
                          dispatch_uid="accounts.testing.auto_consent")
