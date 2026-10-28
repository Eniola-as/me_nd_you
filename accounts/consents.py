"""The 18+ confirmation and the explicit consents (NDPA 2023, GAID 2025).

Each is stored with its time and the policy version it was given for. The
age confirmation is asked once; the others are asked again whenever
settings.POLICY_VERSION changes."""

from django.conf import settings
from django.db import IntegrityError, transaction

from .models import Consent

CONSENT_KINDS = [Consent.AGE, Consent.TERMS, Consent.SENSITIVE, Consent.TRANSFER]
ONE_TIME_KINDS = {Consent.AGE}

# Session key: the policy version this session's user is known to have
# accepted, so the gate doesn't query on every request. Consents are never
# withdrawn without deleting the account, so this can't go stale.
SESSION_KEY = "consented_policy_version"


def missing_consents(user):
    """The consent kinds this user still has to give, in display order."""
    given = set(Consent.objects.filter(user=user).values_list("kind", "policy_version"))
    kinds_given = {kind for kind, _ in given}
    return [
        kind for kind in CONSENT_KINDS
        if not (kind in kinds_given if kind in ONE_TIME_KINDS else (kind, settings.POLICY_VERSION) in given)
    ]


def record_consents(user, kinds):
    """Store the given consents at the current policy version. Giving one
    again for the same version changes nothing."""
    for kind in kinds:
        try:
            with transaction.atomic():
                Consent.objects.get_or_create(user=user, kind=kind, policy_version=settings.POLICY_VERSION)
        except IntegrityError:
            pass  # Recorded at the same moment by another request.
