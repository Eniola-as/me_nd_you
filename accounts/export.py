"""Download my data: everything Me & You holds that is this user's, as JSON.

Covers active couple spaces and spaces that closed less than 30 days ago
(they're permanently deleted after that). The partner's own messages,
reactions, email and name are theirs, so they're left out."""

from django.conf import settings
from django.utils import timezone

from chat import crypto
from chat.models import ChatMessage, ChatReaction
from couples.models import CLOSED_SPACE_RETENTION, Membership
from game.models import CustomQuestion


def _time(value):
    return value.isoformat() if value else None


def exportable_memberships(user, now=None):
    """The user's memberships whose space is open or closed within 30 days."""
    now = now or timezone.now()
    memberships = Membership.objects.filter(user=user).select_related("couple").order_by("joined_at", "pk")
    return [m for m in memberships
            if m.couple.closed_at is None or m.couple.closed_at > now - CLOSED_SPACE_RETENTION]


def _space(user, membership):
    couple = membership.couple
    space = {
        "status": "closed" if couple.closed_at else "active",
        "created_at": _time(couple.created_at),
        "you_joined_at": _time(membership.joined_at),
        "you_left_at": _time(membership.left_at),
    }
    if couple.closed_at:
        space["closed_at"] = _time(couple.closed_at)
        space["deleted_after"] = _time(couple.closed_at + CLOSED_SPACE_RETENTION)
    space["custom_questions"] = [
        {
            "text": q.text,
            "mode": q.mode,
            "kind": q.kind or None,
            "created_at": _time(q.created_at),
            # True: you wrote it; False: your partner did; null: added before
            # authors were recorded.
            "yours": None if q.author_id is None else q.author_id == user.pk,
        }
        for q in CustomQuestion.objects.filter(space=couple).order_by("created_at", "pk")
    ]
    space["chat_messages"] = [
        {"id": m.pk, "text": crypto.decrypt(m.body), "sent_at": _time(m.created_at)}
        for m in ChatMessage.objects.filter(couple=couple, author=user).order_by("pk")
    ]
    space["chat_reactions"] = [
        {"message_id": r.message_id, "on_your_message": r.message.author_id == user.pk,
         "emoji": r.emoji, "reacted_at": _time(r.created_at)}
        for r in ChatReaction.objects.filter(message__couple=couple, user=user).select_related("message")
        .order_by("created_at", "pk")
    ]
    return space


def export_for(user):
    now = timezone.now()
    return {
        "about": "Your data from Me & You. Chat messages are your own; your partner's are theirs.",
        "exported_at": _time(now),
        "policy_version": settings.POLICY_VERSION,
        "account": {
            "email": user.email,
            "display_name": user.display_name,
            "joined_at": _time(user.date_joined),
            "last_sign_in": _time(user.last_login),
            "email_verified_at": _time(user.email_verified_at),
        },
        "consents": [
            {"kind": c.kind, "description": c.get_kind_display(), "policy_version": c.policy_version,
             "given_at": _time(c.given_at)}
            for c in user.consents.order_by("given_at", "pk")
        ],
        "couple_spaces": [_space(user, m) for m in exportable_memberships(user, now)],
    }
