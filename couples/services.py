"""Couple membership and invitation rules. Views call these; they hold every
check, so the rules are the same wherever an action comes from."""

import hashlib
import secrets
from datetime import timedelta

from functools import partial

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import IntegrityError, transaction
from django.utils import timezone

from chat.services import notify_chat_closed
from play.games import get_game
from play.groups import room_group_name
from play.models import GameRoom

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


# Both are "already in a couple"; they say which, for the space page.
class AlreadyMember(AlreadyInCouple):
    message = "You're already in this space."


class SwitchNeedsConfirmation(AlreadyInCouple):
    message = "Tick the box to confirm that you want to close your current space and join this one."


# Where an invitation would take this user (see invitation_for).
JOIN, ALREADY_MEMBER, SWITCH = "join", "already_member", "switch"


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


def _usable_invitation(raw_token, now, lock=False):
    invitations = Invitation.objects.select_related("couple", "created_by")
    if lock:
        invitations = invitations.select_for_update()
    invitation = invitations.filter(token_hash=hash_token(raw_token)).first()
    if invitation is None or not invitation.is_usable(now) or invitation.couple.closed_at:
        raise InvalidInvitation()
    return invitation


def invitation_for(user, raw_token):
    """What accepting this invitation would do for this user, without
    changing anything: (JOIN | ALREADY_MEMBER | SWITCH, inviter's name).
    Raises InvalidInvitation or CoupleFull. Only the person holding the
    token sees this, and only the inviter's display name."""
    invitation = _usable_invitation(raw_token, timezone.now())
    current = active_membership(user)
    if current and current.couple_id == invitation.couple_id:
        return ALREADY_MEMBER, invitation.created_by.name_for_partner
    if Membership.objects.active().filter(couple=invitation.couple_id).count() >= len(MEMBER_SLOTS):
        raise CoupleFull()
    return (SWITCH if current else JOIN), invitation.created_by.name_for_partner


def redeem_invitation(user, raw_token, switch=False):
    """Add user to the invitation's couple, atomically. Each invitation works
    once; a couple never gets a third member.

    Someone already in another couple must pass switch=True (an explicit
    confirmation): their current space then closes for both members, exactly
    as leaving does, in the same transaction as the join. Everything is
    checked before anything changes, and if any step fails the whole
    transaction rolls back, so they keep their current space. The caller
    sends the closure notices for the closed couple."""
    now = timezone.now()
    with transaction.atomic():
        invitation = _usable_invitation(raw_token, now, lock=True)
        current = active_membership(user)
        if current and current.couple_id == invitation.couple_id:
            raise AlreadyMember()
        if current and not switch:
            raise SwitchNeedsConfirmation()

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

        # Only now, with the invitation and a free slot secured, does the
        # current space close (a savepoint inside this transaction).
        if current:
            close_couple(user)
        _add_member(couple, user, free[0])
    return couple


def _add_member(couple, user, slot):
    try:
        with transaction.atomic():
            Membership.objects.create(couple=couple, user=user, slot=slot)
    except IntegrityError:
        # Lost a race; the outer transaction rolls back the claim (and any
        # closure), so the invitation stays usable.
        raise (AlreadyInCouple() if active_membership(user) else CoupleFull()) from None


def close_couple(user, reason=Couple.CLOSED_BY_LEAVING):
    """Leave the couple: it closes for both members. Both memberships end,
    pending invitations are revoked and game rooms close, in one
    transaction; open game connections are told only after it commits.
    Nothing is deleted now: the space, with everything in it, is deleted
    30 days later (accounts.deletion.purge_due), and until then an admin
    can reopen it. The caller sends the closure notices."""
    now = timezone.now()
    with transaction.atomic():
        membership = active_membership(user)
        if membership is None:
            raise NotInCouple()
        couple = Couple.objects.select_for_update().get(pk=membership.couple_id)
        couple.closed_at, couple.closed_by, couple.closed_reason = now, user, reason
        couple.save(update_fields=["closed_at", "closed_by", "closed_reason"])
        Membership.objects.active().filter(couple=couple).update(left_at=now)
        _pending(couple).update(revoked_at=now)
        rooms = GameRoom.objects.filter(couple=couple, status=GameRoom.ACTIVE)
        room_ids = list(rooms.values_list("pk", flat=True))
        # Private answers are never kept, not even for admin recovery.
        for room in rooms.select_for_update():
            game = get_game(room.game)
            if hasattr(game, "forget_answers"):
                room.state = game.forget_answers(room.state)
                room.save(update_fields=["state"])
        rooms.update(status=GameRoom.CLOSED)
        for room_id in room_ids:
            transaction.on_commit(partial(notify_room_closed, room_id))
        # Messages stay in the database, hidden from everyone, and come back
        # if an admin reopens the couple; open chats close now.
        transaction.on_commit(partial(notify_chat_closed, couple.pk))
    return couple


def reopen_couple(couple):
    """Admin recovery: reopen a closed couple and restore the memberships
    that the closure ended, except for anyone now in another couple.
    Returns the users restored. Game rooms start fresh when next played;
    custom questions were never removed."""
    with transaction.atomic():
        couple = Couple.objects.select_for_update().get(pk=couple.pk)
        if couple.closed_at is None:
            return []
        restored = []
        for membership in Membership.objects.filter(couple=couple, left_at=couple.closed_at).select_related("user"):
            if Membership.objects.active().filter(user=membership.user).exists():
                continue  # Joined another couple since; leave them there.
            membership.left_at = None
            membership.save(update_fields=["left_at"])
            restored.append(membership.user)
        couple.closed_at, couple.closed_by, couple.closed_reason = None, None, ""
        couple.save(update_fields=["closed_at", "closed_by", "closed_reason"])
    return restored


def notify_room_closed(room_id):
    layer = get_channel_layer()
    if layer is not None:
        async_to_sync(layer.group_send)(room_group_name(room_id), {"type": "room.closed"})


def _pending(couple):
    return Invitation.objects.filter(couple=couple, used_at__isnull=True, revoked_at__isnull=True)
