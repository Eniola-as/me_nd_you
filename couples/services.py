"""Couple membership and invitation rules. Views call these; they hold every
check, so the rules are the same wherever an action comes from."""

import hashlib
import secrets
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import MEMBER_SLOTS, Couple, Invitation, Membership

INVITATION_TTL = timedelta(days=7)


class InvitationError(Exception):
    message = "Something went wrong."

    def __str__(self):
        return self.message


class InvalidInvitation(InvitationError):
    # Deliberately the same for unknown, used, expired and revoked tokens.
    message = "This invitation link is invalid or has expired."


class AlreadyInCouple(InvitationError):
    message = "You're already in a couple."


class CoupleFull(InvitationError):
    message = "This couple already has two members."


class NotInCouple(InvitationError):
    message = "Start or join a couple first."


def hash_token(raw_token):
    return hashlib.sha256((raw_token or "").encode()).hexdigest()


def active_membership(user):
    if not user.is_authenticated:
        return None
    return Membership.objects.active().select_related("couple").filter(user=user).first()


def active_couple(user):
    membership = active_membership(user)
    return membership.couple if membership else None


def partner_of(user):
    membership = active_membership(user)
    if membership is None:
        return None
    other = (
        Membership.objects.active()
        .filter(couple=membership.couple)
        .exclude(user=user)
        .select_related("user")
        .first()
    )
    return other.user if other else None


def create_couple(user):
    with transaction.atomic():
        if active_membership(user):
            raise AlreadyInCouple()
        couple = Couple.objects.create()
        try:
            with transaction.atomic():
                Membership.objects.create(couple=couple, user=user, slot=MEMBER_SLOTS[0])
        except IntegrityError:  # Joined another couple at the same moment.
            raise AlreadyInCouple() from None
    return couple


def create_invitation(user):
    """Return a new raw token. Any earlier pending invitation is revoked, so
    only one link works at a time."""
    with transaction.atomic():
        membership = active_membership(user)
        if membership is None:
            raise NotInCouple()
        couple = membership.couple
        if Membership.objects.active().filter(couple=couple).count() >= len(MEMBER_SLOTS):
            raise CoupleFull()
        now = timezone.now()
        _pending(couple).update(revoked_at=now)
        raw_token = secrets.token_urlsafe(32)
        Invitation.objects.create(
            couple=couple,
            created_by=user,
            token_hash=hash_token(raw_token),
            expires_at=now + INVITATION_TTL,
        )
    return raw_token


def revoke_invitations(user):
    membership = active_membership(user)
    if membership is None:
        raise NotInCouple()
    return _pending(membership.couple).update(revoked_at=timezone.now())


def pending_invitation(user):
    membership = active_membership(user)
    if membership is None:
        return None
    return _pending(membership.couple).filter(expires_at__gt=timezone.now()).first()


def redeem_invitation(user, raw_token):
    """Add user to the invitation's couple, atomically. Each invitation works
    once; a couple never gets a third member."""
    now = timezone.now()
    with transaction.atomic():
        invitation = (
            Invitation.objects.select_for_update().filter(token_hash=hash_token(raw_token)).first()
        )
        if invitation is None or not invitation.is_usable(now):
            raise InvalidInvitation()
        if active_membership(user):
            raise AlreadyInCouple()

        # Lock the couple so two acceptances can't pick the same free slot
        # (PostgreSQL); the slot constraint backs this up on every database.
        couple = Couple.objects.select_for_update().get(pk=invitation.couple_id)
        taken = set(Membership.objects.active().filter(couple=couple).values_list("slot", flat=True))
        free = [slot for slot in MEMBER_SLOTS if slot not in taken]
        if not free:
            raise CoupleFull()

        # Compare-and-set: only one request can mark this invitation used.
        claimed = Invitation.objects.filter(
            pk=invitation.pk, used_at__isnull=True, revoked_at__isnull=True, expires_at__gt=now
        ).update(used_at=now, used_by=user)
        if not claimed:
            raise InvalidInvitation()

        try:
            with transaction.atomic():
                Membership.objects.create(couple=couple, user=user, slot=free[0])
        except IntegrityError:
            # Lost a race; the outer transaction rolls back the claim above,
            # so the invitation stays usable.
            raise (AlreadyInCouple() if active_membership(user) else CoupleFull()) from None
    return couple


def _pending(couple):
    return Invitation.objects.filter(couple=couple, used_at__isnull=True, revoked_at__isnull=True)
