"""Account deletion and the purge of deleted accounts and closed spaces.

Deleting an account closes it at once: it's made inactive, signed out
everywhere, and its couple space closes for both members. Signing in within
DELETION_GRACE cancels. After that, everything the user wrote is
permanently deleted: their chat messages and reactions, the custom
questions known to be theirs, their consents, memberships (with presence
data) and the account itself. Closed couple spaces are deleted, with
everything in them, CLOSED_SPACE_RETENTION after closing.

There is no background worker: the app purges at most hourly, on the first
request after that (maybe_purge), and every deploy runs
`manage.py purge_deleted_accounts`."""

import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from couples import services as couples
from couples.models import CLOSED_SPACE_RETENTION, Couple
from game.models import CustomQuestion

from .sessions import sign_out_everywhere

logger = logging.getLogger(__name__)

DELETION_GRACE = timedelta(days=7)
LAST_PURGE_KEY = "accounts:last-purge"
PURGE_INTERVAL = 60 * 60  # Seconds. Counted per process, like the rate limits.


def deletion_date(user):
    """When the account will be purged (if still not cancelled)."""
    return user.deletion_requested_at + DELETION_GRACE


def request_deletion(user):
    """Close the account now. Returns the couple space this closed, if any."""
    with transaction.atomic():
        couple = None
        if couples.active_membership(user) is not None:
            couple = couples.close_couple(user, reason=Couple.CLOSED_BY_ACCOUNT_DELETION)
        user.is_active = False
        user.deletion_requested_at = timezone.now()
        user.save(update_fields=["is_active", "deletion_requested_at"])
        sign_out_everywhere(user)
    return couple


def is_restorable(user):
    """Deleted by its owner, and still within the 7 days."""
    return (not user.is_active and user.deletion_requested_at is not None
            and timezone.now() < deletion_date(user))


def cancel_deletion(user):
    user.is_active = True
    user.deletion_requested_at = None
    user.save(update_fields=["is_active", "deletion_requested_at"])


def _purge_account(user):
    from couples.notices import notify_partners_of_final_deletion

    notify_partners_of_final_deletion(user)
    # A question outlives its author otherwise (its author link is cleared).
    CustomQuestion.objects.filter(author=user).delete()
    # Everything else goes with the account (cascades): chat messages (and
    # the reactions on them), reactions, consents, memberships with their
    # presence data, and invitations.
    user.delete()


def purge_due(now=None):
    """Permanently delete what's due. Returns how many of each went."""
    now = now or timezone.now()
    accounts = spaces = 0
    due_accounts = get_user_model().objects.filter(
        is_active=False, deletion_requested_at__isnull=False, deletion_requested_at__lte=now - DELETION_GRACE
    )
    for user in due_accounts:
        with transaction.atomic():
            _purge_account(user)
        accounts += 1
    for couple in Couple.objects.filter(closed_at__isnull=False, closed_at__lte=now - CLOSED_SPACE_RETENTION):
        with transaction.atomic():
            # Its custom questions, chat, game rooms, memberships and
            # invitations go with it.
            couple.delete()
        spaces += 1
    if accounts or spaces:
        logger.info("Purged %s deleted accounts and %s closed couple spaces.", accounts, spaces)
    return {"accounts": accounts, "couple_spaces": spaces}


def maybe_purge():
    """Purge at most once per PURGE_INTERVAL; never let it break a request."""
    if not cache.add(LAST_PURGE_KEY, True, PURGE_INTERVAL):
        return
    try:
        purge_due()
    except Exception:
        logger.exception("The scheduled purge failed; it will run again on the next deploy or hour.")
