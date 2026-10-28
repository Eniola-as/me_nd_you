"""Chat rules. Every call re-checks that the user is an active member of
the couple, inside the transaction, and partners are told about changes
only after they commit. Message text is encrypted at rest (chat.crypto)."""

import datetime
import uuid
from functools import partial

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone

from accounts.consents import missing_consents
from couples.models import Membership

from . import crypto, presence
from .groups import chat_group_name, chat_reader_group_name
from .models import ChatMessage, ChatReaction
from .reaction_emoji import is_single_emoji

MAX_LENGTH = 1000
PAGE_SIZE = 50
RATE_LIMIT = 30  # Messages per person per RATE_WINDOW.
RATE_WINDOW = datetime.timedelta(minutes=1)


class ChatError(Exception):
    pass


class Forbidden(ChatError):
    """Not an active member of this couple (any more)."""


class Invalid(ChatError):
    pass


class RateLimited(ChatError):
    pass


def membership(user, couple_id, lock=False):
    """The user's active membership of this couple, or Forbidden."""
    if not getattr(user, "is_authenticated", False):
        raise Forbidden()
    memberships = Membership.objects.active().filter(user=user, couple_id=couple_id)
    if lock:
        memberships = memberships.select_for_update()
    found = memberships.first()
    # Missing a required consent (or not yet accepting a new policy
    # version) counts as no access, on connect and on every message.
    if found is None or missing_consents(user):
        raise Forbidden()
    return found


def active_couple_id(user):
    if not getattr(user, "is_authenticated", False):
        return None
    return Membership.objects.active().filter(user=user).values_list("couple_id", flat=True).first()


def send(user, couple_id, text, request_id):
    request_id = _uuid_or_none(request_id)
    if not isinstance(text, str) or not text.strip() or len(text.strip()) > MAX_LENGTH:
        raise Invalid(f"Messages need 1 to {MAX_LENGTH} characters.")
    with transaction.atomic():
        # Locking the membership row serialises one person's sends, so the
        # rate limit can't be raced.
        membership(user, couple_id, lock=True)
        if request_id:
            existing = ChatMessage.objects.filter(author=user, request_id=request_id, couple_id=couple_id).first()
            if existing:
                return existing  # A retry of a send that was already saved.
        since = timezone.now() - RATE_WINDOW
        if ChatMessage.objects.filter(author=user, created_at__gt=since).count() >= RATE_LIMIT:
            raise RateLimited(f"That's {RATE_LIMIT} messages in a minute. Wait a moment.")
        message = ChatMessage.objects.create(
            couple_id=couple_id, author=user, body=crypto.encrypt(text.strip()), request_id=request_id
        )
        transaction.on_commit(partial(notify_couple, couple_id, {"type": "chat.message", "id": message.pk}))
    return message


def message_for(user, couple_id, message_id):
    """One message as this user may see it; None if it no longer exists."""
    membership(user, couple_id)
    message = ChatMessage.objects.filter(pk=message_id, couple_id=couple_id).prefetch_related("reactions").first()
    return serialize(message, user) if message else None


def history(user, couple_id, before=None):
    """The PAGE_SIZE messages before `before` (a message id), oldest first.
    The latest page also says who the partner is and what's unread."""
    member = membership(user, couple_id)
    messages = ChatMessage.objects.filter(couple_id=couple_id)
    if before is not None:
        if type(before) is not int or before < 1:
            raise Invalid("Bad history cursor.")
        messages = messages.filter(pk__lt=before)
    page = list(messages.order_by("-id").prefetch_related("reactions")[: PAGE_SIZE + 1])
    result = {
        "messages": [serialize(m, user) for m in reversed(page[:PAGE_SIZE])],
        "has_more": len(page) > PAGE_SIZE,
    }
    if before is None:
        unread = ChatMessage.objects.filter(couple_id=couple_id).exclude(author=user)
        if member.chat_read_up_to is not None:
            unread = unread.filter(pk__gt=member.chat_read_up_to)
        partner = (Membership.objects.active().filter(couple_id=couple_id).exclude(user=user)
                   .select_related("user").first())
        result.update(lastRead=member.chat_read_up_to, unread=unread.count(),
                      partner=partner.user.name_for_partner if partner else "")
    return result


def mark_read(user, couple_id, up_to):
    """Move this member's read marker forward to `up_to` (a message id),
    never back and never past the newest message."""
    if type(up_to) is not int or up_to < 1:
        raise Invalid("Bad read marker.")
    with transaction.atomic():
        member = membership(user, couple_id, lock=True)
        newest = ChatMessage.objects.filter(couple_id=couple_id).order_by("-id").values_list("pk", flat=True).first()
        if newest is None:
            return
        up_to = min(up_to, newest)
        if member.chat_read_up_to is not None and up_to <= member.chat_read_up_to:
            return
        member.chat_read_up_to = up_to
        member.save(update_fields=["chat_read_up_to"])
        transaction.on_commit(partial(notify_reader, user.pk, {"type": "chat.read", "upTo": up_to}))


def delete(user, couple_id, message_id):
    """Delete your own message for both of you. The row is removed."""
    if type(message_id) is not int:
        raise Invalid("That message doesn't exist.")
    with transaction.atomic():
        membership(user, couple_id, lock=True)
        message = ChatMessage.objects.select_for_update().filter(pk=message_id, couple_id=couple_id).first()
        if message is None:
            raise Invalid("That message doesn't exist.")
        if message.author_id != user.pk:
            raise Invalid("You can only delete your own messages.")
        message.delete()
        transaction.on_commit(partial(notify_couple, couple_id, {"type": "chat.deleted", "id": message_id}))


def react(user, couple_id, message_id, emoji):
    """Set (or with emoji=None, remove) this person's one reaction to a
    message in their couple's chat."""
    if type(message_id) is not int:
        raise Invalid("That message doesn't exist.")
    if emoji is not None and not is_single_emoji(emoji):
        raise Invalid("Pick a single emoji.")
    with transaction.atomic():
        membership(user, couple_id, lock=True)
        message = ChatMessage.objects.filter(pk=message_id, couple_id=couple_id).first()
        if message is None:
            raise Invalid("That message doesn't exist.")
        if emoji is None:
            ChatReaction.objects.filter(message=message, user=user).delete()
        else:
            ChatReaction.objects.update_or_create(message=message, user=user, defaults={"emoji": emoji})
        transaction.on_commit(partial(notify_couple, couple_id, {"type": "chat.reaction", "id": message_id}))


def serialize(message, viewer):
    text = crypto.decrypt(message.body)
    shown = {
        "id": message.pk,
        "mine": message.author_id == viewer.pk,
        "text": text if text is not None else crypto.UNREADABLE,
        "unreadable": text is None,
        "sentAt": message.created_at.isoformat(),
        "reactions": {"mine": None, "partner": None},
    }
    for reaction in message.reactions.all():
        shown["reactions"]["mine" if reaction.user_id == viewer.pk else "partner"] = reaction.emoji
    if shown["mine"] and message.request_id:
        shown["requestId"] = str(message.request_id)  # Lets the sender match it.
    return shown


def notify_couple(couple_id, event):
    layer = get_channel_layer()
    if layer is not None:
        async_to_sync(layer.group_send)(chat_group_name(couple_id), event)


def partner_presence(user, couple_id):
    """Where the partner is: online (and where) from the live connections,
    otherwise when they were last seen."""
    membership(user, couple_id)
    partner = Membership.objects.active().filter(couple_id=couple_id).exclude(user=user).first()
    if partner is None:
        return {"online": False, "where": None, "lastSeen": None}
    live = presence.status(partner.user_id)
    seen = partner.last_seen_at.isoformat() if partner.last_seen_at and not live["online"] else None
    return {**live, "lastSeen": seen}


def mark_seen(user, couple_id):
    """Store "last seen" when a member's last chat connection closes."""
    Membership.objects.active().filter(user=user, couple_id=couple_id).update(last_seen_at=timezone.now())


def notify_reader(user_id, event):
    layer = get_channel_layer()
    if layer is not None:
        async_to_sync(layer.group_send)(chat_reader_group_name(user_id), event)


def notify_chat_closed(couple_id):
    notify_couple(couple_id, {"type": "chat.closed"})


def _uuid_or_none(value):
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise Invalid("Bad request id.") from None
