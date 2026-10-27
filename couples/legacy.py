"""Moving a secret-word couple over to accounts (docs/PRODUCT_DECISIONS.md §1).

1. Claim: a couple-space member enters the old couple's names and secret
   word. The old couple is linked to the space; nothing is copied or deleted.
2. Ready: once both space members confirm they have moved over, the secret
   word keeps working for GRACE_PERIOD.
3. Deadline: if the move is still complete (space open, both members there
   and ready), the secret word stops working. Otherwise it keeps working and
   the link is flagged for an admin. The deadline is applied the next time
   the secret word is used.

Admins can clear a retirement or unlink; every step is reversible."""

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from game.models import CoupleSession, bump_questions_cache_version

from .models import MEMBER_SLOTS, LegacyLink, Membership
from .services import InvitationError, NotInCouple, active_membership

GRACE_PERIOD = timedelta(days=14)


class NoSuchLegacyCouple(InvitationError):
    # The same for an unknown secret and for wrong names.
    message = "Those names and secret word don't match an old couple."


class AlreadyLinked(InvitationError):
    message = "That couple is already linked to a couple space (or this space already has one)."


def active_links():
    return LegacyLink.objects.filter(unlinked_at__isnull=True)


def link_for_couple(couple):
    link = active_links().filter(couple=couple).select_related("legacy").first()
    if link is not None:
        secret_word_retired(link.legacy)  # Applies a passed deadline.
        link.refresh_from_db()
    return link


def notice_for_secret(secret):
    """What a legacy page should tell the couple using this secret word:
    "move" (not linked yet), "linked", "retiring" (with a date) or
    "retired". None for unknown or expired secrets, which get no notice."""
    session = CoupleSession.objects.filter(secret_word=secret).first() if secret else None
    if session is None or session.is_expired():
        return None
    if secret_word_retired(session):
        return {"kind": "retired"}
    link = active_links().filter(legacy=session).first()
    if link is None:
        return {"kind": "move"}
    if link.retire_at and link.needs_resolution_at is None:
        return {"kind": "retiring", "date": link.retire_at}
    return {"kind": "linked"}


def claim(user, partner1_name, partner2_name, secret_word):
    membership = active_membership(user)
    if membership is None:
        raise NotInCouple()
    session = CoupleSession.objects.filter(secret_word=secret_word).first() if secret_word else None
    names = sorted([(partner1_name or "").strip().casefold(), (partner2_name or "").strip().casefold()])
    if session is None or names != sorted([session.partner1_name.casefold(), session.partner2_name.casefold()]):
        raise NoSuchLegacyCouple()
    try:
        with transaction.atomic():
            link = LegacyLink.objects.create(legacy=session, couple=membership.couple, claimed_by=user)
    except IntegrityError:
        raise AlreadyLinked() from None
    bump_questions_cache_version()  # The space's question lists change.
    return link


def mark_ready(user):
    with transaction.atomic():
        link = _locked_link(user)
        link.ready.add(user)
        if link.retire_at is None and _move_complete(link):
            link.retire_at = timezone.now() + GRACE_PERIOD
            link.save(update_fields=["retire_at"])
    return link


def withdraw_ready(user):
    with transaction.atomic():
        link = _locked_link(user)
        link.ready.remove(user)
        if link.retired_at is None:
            link.retire_at = None
            link.save(update_fields=["retire_at"])
    return link


def secret_word_retired(session):
    """Whether this legacy couple's secret word no longer works. Applies a
    passed deadline first."""
    link = active_links().filter(legacy=session).first()
    if link is None:
        return False
    if link.retired_at is None and link.retire_at and link.retire_at <= timezone.now() \
            and link.needs_resolution_at is None:
        _apply_deadline(link.pk)
        link.refresh_from_db()
    return link.retired_at is not None


def clear_retirement(link):
    """Admin: the secret word works again; the countdown starts over when
    both members confirm again."""
    with transaction.atomic():
        link = LegacyLink.objects.select_for_update().get(pk=link.pk)
        link.retire_at = link.retired_at = link.needs_resolution_at = None
        link.save(update_fields=["retire_at", "retired_at", "needs_resolution_at"])
        link.ready.clear()


def unlink(link):
    """Admin: undo a claim. The old couple works as before and can be
    claimed again; its questions leave the space."""
    clear_retirement(link)
    LegacyLink.objects.filter(pk=link.pk).update(unlinked_at=timezone.now())
    bump_questions_cache_version()


def _locked_link(user):
    membership = active_membership(user)
    if membership is None:
        raise NotInCouple()
    link = active_links().select_for_update().filter(couple=membership.couple).first()
    if link is None:
        raise NoSuchLegacyCouple()
    return link


def _move_complete(link):
    if link.couple.closed_at:
        return False
    members = set(Membership.objects.active().filter(couple=link.couple).values_list("user_id", flat=True))
    ready = set(link.ready.values_list("pk", flat=True))
    return len(members) == len(MEMBER_SLOTS) and members <= ready


def _apply_deadline(link_pk):
    with transaction.atomic():
        link = LegacyLink.objects.select_for_update().select_related("couple").get(pk=link_pk)
        if link.retired_at or link.needs_resolution_at or not link.retire_at or link.retire_at > timezone.now():
            return  # Another request got here first, or the countdown changed.
        if _move_complete(link):
            link.retired_at = timezone.now()
        else:
            link.needs_resolution_at = timezone.now()
        link.save(update_fields=["retired_at", "needs_resolution_at"])
