"""The closure notices. When a couple space closes, its members get an email
and see a notice on their space page until it's permanently deleted.

The closure notice is neutral: never who closed it, why, the partner's name,
or anything that was in the space. That holds when a member deletes their
account too, because the deletion can still be cancelled for 7 days. Only
when it becomes final (the purge) is the other partner told that their
partner deleted their account (approved 2026-10-29). The one deleting gets
only their account-deletion email. No notice ever names the partner."""

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.emails import send_account_email

from .models import CLOSED_SPACE_RETENTION, Couple, Membership

logger = logging.getLogger(__name__)

DOWNLOAD_PATH = "/accounts/profile/#download"


def deleted_after(couple):
    return couple.closed_at + CLOSED_SPACE_RETENTION


def _context(couple, link):
    return {"date": deleted_after(couple), "link": link, "contact_email": settings.PRIVACY_CONTACT_EMAIL}


def _send(user, template, context):
    try:
        send_account_email(user, template, context)
    except Exception:
        logger.exception("Could not send a %s email.", template)


def _ended_memberships(couple):
    return Membership.objects.filter(couple=couple, left_at=couple.closed_at).select_related("user")


def send_closure_notices(request, couple):
    """The neutral email to each member whose membership the closure ended
    (except someone deleting their account: their own email covers it)."""
    if couple is None or couple.closed_at is None:
        return
    context = _context(couple, request.build_absolute_uri(DOWNLOAD_PATH))
    for membership in _ended_memberships(couple):
        deleting = couple.closed_reason == Couple.CLOSED_BY_ACCOUNT_DELETION and couple.closed_by_id == membership.user_id
        if not deleting:
            _send(membership.user, "couple_closed", context)


def notify_partners_of_final_deletion(user):
    """Called when a deleted account is purged: tell the partner in each
    space it closed (and that isn't deleted yet) that the deletion is final.
    Sent after the purge commits."""
    couples = Couple.objects.filter(closed_by=user, closed_reason=Couple.CLOSED_BY_ACCOUNT_DELETION,
                                    closed_at__isnull=False)
    notices = [
        (membership.user, _context(couple, settings.SITE_URL + DOWNLOAD_PATH))
        for couple in couples
        for membership in _ended_memberships(couple).exclude(user=user)
    ]
    for partner, context in notices:
        transaction.on_commit(lambda partner=partner, context=context: _send(partner, "partner_account_deleted", context))


def closure_notice_for(user):
    """The in-app notice for a space of this user's that closed less than
    30 days ago, or None."""
    now = timezone.now()
    membership = (
        Membership.objects.filter(user=user, couple__closed_at__gt=now - CLOSED_SPACE_RETENTION)
        .select_related("couple").order_by("-couple__closed_at").first()
    )
    if membership is None:
        return None
    couple = membership.couple
    return {
        "date": deleted_after(couple),
        # Final only once the deleted account is gone (closed_by is then
        # cleared); while it can be cancelled, the notice stays neutral.
        "partner_deleted_account": couple.closed_reason == Couple.CLOSED_BY_ACCOUNT_DELETION
        and couple.closed_by_id is None,
    }
