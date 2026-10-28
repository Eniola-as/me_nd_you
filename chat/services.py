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

from couples.models import Membership

from . import crypto
from .groups import chat_group_name
from .models import ChatMessage

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
    if found is None:
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
    message = ChatMessage.objects.filter(pk=message_id, couple_id=couple_id).first()
    return serialize(message, user) if message else None


def history(user, couple_id, before=None):
    """The PAGE_SIZE messages before `before` (a message id), oldest first."""
    membership(user, couple_id)
    messages = ChatMessage.objects.filter(couple_id=couple_id)
    if before is not None:
        if type(before) is not int or before < 1:
            raise Invalid("Bad history cursor.")
        messages = messages.filter(pk__lt=before)
    page = list(messages.order_by("-id")[: PAGE_SIZE + 1])
    return {
        "messages": [serialize(m, user) for m in reversed(page[:PAGE_SIZE])],
        "has_more": len(page) > PAGE_SIZE,
    }


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


def serialize(message, viewer):
    text = crypto.decrypt(message.body)
    shown = {
        "id": message.pk,
        "mine": message.author_id == viewer.pk,
        "text": text if text is not None else crypto.UNREADABLE,
        "unreadable": text is None,
        "sentAt": message.created_at.isoformat(),
    }
    if shown["mine"] and message.request_id:
        shown["requestId"] = str(message.request_id)  # Lets the sender match it.
    return shown


def notify_couple(couple_id, event):
    layer = get_channel_layer()
    if layer is not None:
        async_to_sync(layer.group_send)(chat_group_name(couple_id), event)


def notify_chat_closed(couple_id):
    notify_couple(couple_id, {"type": "chat.closed"})


def _uuid_or_none(value):
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise Invalid("Bad request id.") from None
