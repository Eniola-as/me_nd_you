"""Applying actions to game rooms: the only code that changes a room.

Each action runs in one database transaction that locks the room row,
re-checks the actor's membership and the room's status, applies a request
id at most once, refuses actions based on an old version, and records the
change. Clients are told about a change only after it commits.
"""

import uuid
from functools import partial

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import IntegrityError, transaction

from accounts.consents import missing_consents
from couples.models import Membership
from couples.services import active_couple
from game.models import Question
from notifications import services as notifications

from . import games
from .cards import DatabaseCards, card_for_question
from .groups import room_group_name, user_group_name
from .models import CoupleMode, GameRoom, RoomEvent


VALID_MODES = {value for value, _ in Question.MODES}


class PlayError(Exception):
    reason = "error"


class Forbidden(PlayError):
    """Not an active member of the room's couple, or the room is closed."""

    reason = "forbidden"


class Invalid(PlayError):
    reason = "invalid"


class Stale(PlayError):
    """Someone else changed the room first. Carries the current snapshot."""

    reason = "stale"

    def __init__(self, snapshot):
        super().__init__("stale")
        self.snapshot = snapshot


def room_for(user, game_key, variant):
    """The couple's active room for a game and mode, created on first use."""
    try:
        game = games.get_game(game_key)
    except games.ActionInvalid as error:
        raise Invalid(str(error)) from None
    if variant not in VALID_MODES or (game.variants is not None and variant not in game.variants):
        raise Invalid("Unknown game mode.")
    couple = active_couple(user)
    if couple is None:
        raise Forbidden()
    room = _active_room(couple, game_key, variant)
    if room:
        return room
    state = games.get_game(game_key).start(DatabaseCards(couple, variant), seed=games.new_seed())
    try:
        with transaction.atomic():
            return GameRoom.objects.create(couple=couple, game=game_key, variant=variant, state=state)
    except IntegrityError:  # The partner opened it at the same moment.
        return _active_room(couple, game_key, variant)


def snapshot(room, user):
    """The room as this user may see it. Raises Forbidden for non-members
    and closed rooms, so a revoked player never gets another update."""
    membership = _membership(user, room)
    game = games.get_game(room.game)
    view = game.view(room.state, viewer_slot=membership.slot)
    snap = {"type": "state", "game": room.game, "variant": room.variant, "version": room.version, "state": view}
    if game.shows_names:
        snap["names"] = _names(user, room)
    return snap


def apply_action(user, room_id, action, expected_version, request_id, payload=None):
    request_id = _uuid_or_none(request_id)
    with transaction.atomic():
        room = GameRoom.objects.select_for_update().filter(pk=room_id).first()
        if room is None:
            raise Forbidden()
        membership = _membership(user, room)

        if request_id and RoomEvent.objects.filter(room=room, request_id=request_id).exists():
            return room  # A retry of a request that was already applied.
        current_mode = CoupleMode.objects.filter(couple_id=room.couple_id).values_list("mode", flat=True).first()
        if current_mode and room.variant != current_mode:
            # The couple switched modes (play.modes); this page hasn't followed yet.
            raise Invalid("You're playing another mode now.")
        if expected_version != room.version:
            raise Stale(snapshot(room, user))

        game = games.get_game(room.game)
        try:
            new_state = game.apply(
                room.state, action, actor_slot=membership.slot,
                cards=DatabaseCards(room.couple, room.variant), payload=payload,
            )
        except games.ActionInvalid as error:
            raise Invalid(str(error)) from None
        previous_state = room.state
        _commit(room, new_state, kind=action, actor=user, payload=payload, request_id=request_id)
        _notify_answers(room, user, action, previous_state, new_state)
    return room


def _notify_answers(room, user, action, before, after):
    """Private-answer games: "<name> answered" for the partner, and "your
    answers are revealed" for whoever answered first. No answer text."""
    if room.game != games.AnswerRevealGame.key:
        return
    if action == "answer":
        notifications.mark_read(user, kind=notifications.ANSWERED, couple_id=room.couple_id, mode=room.variant)
        revealed = before.get("phase") != "revealed" and after.get("phase") == "revealed"
        kind = notifications.REVEALED if revealed else notifications.ANSWERED
        notifications.notify_partner(user, room.couple_id, kind, room.variant)
    elif action in ("next", "reset"):
        # The card moved on: those notifications no longer lead anywhere new.
        for member in Membership.objects.active().filter(couple_id=room.couple_id).select_related("user"):
            for kind in (notifications.ANSWERED, notifications.REVEALED):
                notifications.mark_read(member.user, kind=kind, couple_id=room.couple_id, mode=room.variant)


def add_custom_card(question):
    """Put a couple's new custom question into their open rooms for its mode."""
    if question.space_id is None:
        return
    card = card_for_question(question)
    rooms = GameRoom.objects.filter(couple_id=question.space_id, status=GameRoom.ACTIVE)
    for room_id in rooms.filter(variant__in=[question.mode, "mixed"]).values_list("pk", flat=True):
        with transaction.atomic():
            room = GameRoom.objects.select_for_update().get(pk=room_id)
            new_state = games.get_game(room.game).insert_card(room.state, card, seed=games.new_seed())
            if new_state != room.state:
                _commit(room, new_state, kind="insert_card", actor=None, payload={"key": card["key"]})


def notify_user_signed_out(user_id):
    """Close every open game connection of this user."""
    layer = get_channel_layer()
    if layer is not None:
        async_to_sync(layer.group_send)(user_group_name(user_id), {"type": "user.signed_out"})


def notify_room(room_id, version):
    """Tell connected players that a new version exists. Each connection
    then builds its own player's view, so no private data is broadcast."""
    layer = get_channel_layer()
    if layer is not None:
        async_to_sync(layer.group_send)(
            room_group_name(room_id), {"type": "room.updated", "version": version}
        )


def _commit(room, new_state, kind, actor, payload=None, request_id=None):
    """Store the next version and its event; notify only after commit."""
    previous = room.version
    # Compare-and-set backs up the row lock (a no-op on SQLite).
    updated = GameRoom.objects.filter(pk=room.pk, version=previous).update(
        state=new_state, version=previous + 1
    )
    if not updated:
        raise Stale(None)
    room.state, room.version = new_state, previous + 1
    RoomEvent.objects.create(
        room=room, version=room.version, kind=kind, actor=actor,
        payload=_event_payload(kind, payload), request_id=request_id,
    )
    transaction.on_commit(partial(notify_room, room.pk, room.version))


def _event_payload(kind, payload):
    # Keep answers, Would You Rather picks and reactions out of the history;
    # the room state holds them until the card moves on.
    return {} if kind in ("answer", "react", "pick") else (payload or {})


def _membership(user, room):
    if room.status != GameRoom.ACTIVE or not getattr(user, "is_authenticated", False):
        raise Forbidden()
    membership = Membership.objects.active().filter(user=user, couple_id=room.couple_id).first()
    # Missing a required consent (or not yet accepting a new policy
    # version) counts as no access, on connect and on every action/update.
    if membership is None or missing_consents(user):
        raise Forbidden()
    return membership


def _names(user, room):
    """Display names for turn banners; never an email address."""
    partner = (
        Membership.objects.active().filter(couple_id=room.couple_id).exclude(user=user)
        .select_related("user").first()
    )
    return {"me": user.display_name, "partner": partner.user.name_for_partner if partner else ""}


def _active_room(couple, game_key, variant):
    return GameRoom.objects.filter(
        couple=couple, game=game_key, variant=variant, status=GameRoom.ACTIVE
    ).first()


def _uuid_or_none(value):
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise Invalid("Bad request id.") from None
