"""In-app notifications: created inside the change that caused them (so a
rolled-back change leaves none), at most one unread per kind, and shown only
to their member while they're in that couple space. A push goes out after
commit, only for a new notification (notifications.push)."""

from functools import partial

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Notification

CHAT = "chat_message"
ANSWERED = "partner_answered"
REVEALED = "answers_revealed"
MODE_REQUESTED = "mode_requested"
MODE_SWITCHED = "mode_switched"

RECENT = 20

# Push text: no names, modes or content, since it can show on a lock screen.
PUSH_TEXT = {
    CHAT: "Your partner sent you a message.",
    ANSWERED: "Your partner answered a question.",
    REVEALED: "Your answers are revealed.",
    MODE_REQUESTED: "Your partner wants to switch games.",
    MODE_SWITCHED: "Your game changed.",
}


def notify(recipient_id, couple_id, kind, mode=""):
    """Tell a member something happened. Returns True if this made a new
    unread notification (and so a push), False if one was already waiting."""
    with transaction.atomic():
        waiting = Notification.objects.filter(
            user_id=recipient_id, couple_id=couple_id, kind=kind, mode=mode, read_at__isnull=True
        ).first()
        if waiting:
            waiting.save(update_fields=["updated_at"])  # Back to the top of the list.
            return False
        try:
            with transaction.atomic():
                Notification.objects.create(user_id=recipient_id, couple_id=couple_id, kind=kind, mode=mode)
        except IntegrityError:
            return False  # Made by a simultaneous event; one is enough.
    from . import push

    transaction.on_commit(partial(push.notify_user, recipient_id, kind, url_for(kind, mode)))
    return True


def notify_partner(actor, couple_id, kind, mode=""):
    """Notify the actor's partner in this couple, if there is one."""
    from couples.models import Membership

    partner_id = (Membership.objects.active().filter(couple_id=couple_id).exclude(user=actor)
                  .values_list("user_id", flat=True).first())
    if partner_id is not None:
        notify(partner_id, couple_id, kind, mode)


def _current(user):
    from couples.services import active_couple

    couple = active_couple(user)
    if couple is None:
        return Notification.objects.none()
    return Notification.objects.filter(user=user, couple=couple)


def unread_count(user):
    return _current(user).filter(read_at__isnull=True).count()


def recent(user):
    """This member's latest notifications in their current couple space,
    each with its text and link."""
    from couples.services import partner_of

    partner = partner_of(user)
    name = partner.name_for_partner if partner else "Your partner"
    return [dict(describe(note, name), id=note.pk, unread=note.read_at is None, at=note.updated_at)
            for note in _current(user)[:RECENT]]


def mark_read(user, kind=None, couple_id=None, mode=None, ids=None):
    notes = Notification.objects.filter(user=user, read_at__isnull=True)
    if kind is not None:
        notes = notes.filter(kind=kind)
    if couple_id is not None:
        notes = notes.filter(couple_id=couple_id)
    if mode is not None:
        notes = notes.filter(mode=mode)
    if ids is not None:
        notes = notes.filter(pk__in=ids)
    return notes.update(read_at=timezone.now())


def mode_label(mode):
    from play.modes import LABELS

    return LABELS.get(mode, "a game")


def describe(note, partner_name):
    """The text and link for a notification. Built here, never stored, and
    never with anything anyone wrote."""
    label = mode_label(note.mode)
    texts = {
        CHAT: f"{partner_name} sent you a message",
        ANSWERED: f"{partner_name} answered a question in {label}",
        REVEALED: f"Your answers in {label} are revealed",
        MODE_REQUESTED: f"{partner_name} wants to switch to {label}",
        MODE_SWITCHED: f"Now playing {label}",
    }
    return {"text": texts.get(note.kind, "Something new in your space"), "url": url_for(note.kind, note.mode)}


def url_for(kind, mode=""):
    """Where a notification leads: always a path on this site."""
    if kind == CHAT:
        return "/space/?chat=1"
    if kind == MODE_REQUESTED:
        return "/modes/"
    if kind in (ANSWERED, REVEALED, MODE_SWITCHED) and mode:
        return f"/play/?mode={mode}"
    return "/space/"
