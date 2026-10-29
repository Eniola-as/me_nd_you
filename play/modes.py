"""The couple's shared game mode (owner, 2026-10-29).

The first mode starts straight away. After that, a change is a request the
other partner must accept; while it's pending nothing changes, so the
current card or turn carries on. Declined or cancelled keeps the current
mode. Accepted: the new mode starts (fresh if never played; each mode's room
keeps its own progress for when the couple switches back), and the mode
being left loses its unrevealed answers and picks, as Next does.

Every change locks the couple's row, checks the version the page last saw
(a stale request changes nothing and gets the latest state), and tells both
partners' open member pages after the change commits."""

from functools import partial

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import IntegrityError, transaction

from couples.models import Membership
from couples.services import active_couple
from game.models import Question

from .games import get_game
from .groups import mode_group_name
from .models import CoupleMode, GameRoom

LABELS = dict(Question.MODES)
# Which game each mode plays: turn-based Truth or Dare and Challenges,
# private answers or picks for Questions and Would You Rather, and a shared
# deck either partner advances for Spicy Only and Mixed.
MODE_GAMES = {
    "questions": "answer_reveal",
    "would": "pick_reveal",
    "truth": "truth_or_dare",
    "challenge": "challenge_turns",
    "spicy": "questions",
    "mixed": "questions",
}


class ModeError(Exception):
    pass


class Invalid(ModeError):
    pass


class Forbidden(ModeError):
    pass


class Stale(ModeError):
    def __init__(self, snapshot):
        super().__init__("The mode changed; here is the latest.")
        self.snapshot = snapshot


def _couple(user):
    couple = active_couple(user) if getattr(user, "is_authenticated", False) else None
    if couple is None:
        raise Forbidden()
    return couple


def _valid(mode):
    if mode not in MODE_GAMES:
        raise Invalid("Unknown game mode.")


def snapshot(couple, viewer):
    """What one partner's page shows: the current mode, the version to send
    back, and any pending request (and whether it's theirs)."""
    row = CoupleMode.objects.filter(couple=couple).first()
    if row is None:
        return {"mode": None, "label": None, "version": 0, "pending": None}
    pending = None
    if row.pending_mode:
        pending = {"mode": row.pending_mode, "by_you": row.requested_by_id == viewer.pk}
    return {"mode": row.mode, "label": LABELS[row.mode], "version": row.version, "pending": pending}


def page_context(user):
    """For the mode banner on member pages: the state and the partner's name."""
    from couples.services import partner_of

    couple = active_couple(user)
    if couple is None:
        return {"mode_state": None}
    partner = partner_of(user)
    state = snapshot(couple, user)
    if state["pending"]:
        state["pending"]["label"] = LABELS[state["pending"]["mode"]]
    return {"mode_state": state, "mode_partner": partner.name_for_partner if partner else "Your partner"}


def current_mode(user):
    """The couple's current mode, or None (no couple or nothing started)."""
    couple = active_couple(user)
    row = CoupleMode.objects.filter(couple=couple).first() if couple else None
    return row.mode if row else None


def start(user, mode):
    """Set the first mode. If one is already set, nothing changes."""
    _valid(mode)
    couple = _couple(user)
    try:
        with transaction.atomic():
            row = CoupleMode.objects.create(couple=couple, mode=mode)
    except IntegrityError:
        return snapshot(couple, user)  # Already started (maybe a moment ago).
    _tell_both(couple, row, "started", mode, actor=user)
    return snapshot(couple, user)


def request_switch(user, mode, version):
    _valid(mode)
    with transaction.atomic():
        couple, row = _locked(user, version)
        if row.pending_mode:
            raise Invalid("A switch is already waiting for an answer.")
        if mode == row.mode:
            raise Invalid("You're already playing that.")
        row.pending_mode, row.requested_by = mode, user
        _save(row)
        _tell_both(couple, row, "requested", mode, actor=user)
    return snapshot(couple, user)


def respond(user, accept, version):
    """The other partner accepts or declines the pending switch."""
    with transaction.atomic():
        couple, row = _locked(user, version)
        if not row.pending_mode:
            raise Invalid("There's no switch waiting.")
        if row.requested_by_id == user.pk:
            raise Invalid("Your partner has to answer your request.")
        requested = row.pending_mode
        if accept:
            _leave(couple, row.mode)
            row.mode = requested
        row.pending_mode, row.requested_by = "", None
        _save(row)
        _tell_both(couple, row, "switched" if accept else "declined", requested, actor=user)
    return snapshot(couple, user)


def cancel(user, version):
    """The partner who asked takes the request back."""
    with transaction.atomic():
        couple, row = _locked(user, version)
        if not row.pending_mode or row.requested_by_id != user.pk:
            raise Invalid("There's no request of yours to cancel.")
        requested = row.pending_mode
        row.pending_mode, row.requested_by = "", None
        _save(row)
        _tell_both(couple, row, "cancelled", requested, actor=user)
    return snapshot(couple, user)


def _locked(user, version):
    couple = _couple(user)
    row = CoupleMode.objects.select_for_update().filter(couple=couple).first()
    if row is None:
        raise Invalid("Start a game mode first.")
    if row.version != version:
        raise Stale(snapshot(couple, user))
    return couple, row


def _save(row):
    row.version += 1
    row.save()


def _leave(couple, mode):
    """Delete the unrevealed answers or picks of the mode being left (its
    deck and position stay for when the couple comes back)."""
    from . import services

    game = get_game(MODE_GAMES[mode])
    if not hasattr(game, "forget_answers"):
        return
    room = GameRoom.objects.select_for_update().filter(
        couple=couple, game=game.key, variant=mode, status=GameRoom.ACTIVE).first()
    if room is None:
        return
    forgotten = game.forget_answers(room.state)
    if forgotten != room.state:
        services._commit(room, forgotten, kind="mode_left", actor=None)


def _tell_both(couple, row, event, mode, actor):
    members = Membership.objects.active().filter(couple=couple).select_related("user")
    users = [m.user for m in members]
    for user in users:
        partner = next((u for u in users if u.pk != user.pk), None)
        message = {
            "event": event,
            "mode": mode,
            "by_you": actor.pk == user.pk,
            "partner": partner.name_for_partner if partner else "Your partner",
        }
        transaction.on_commit(partial(notify, user.pk, message))


def notify(user_id, message):
    layer = get_channel_layer()
    if layer is not None:
        async_to_sync(layer.group_send)(mode_group_name(user_id), {"type": "couple.mode", **message})
