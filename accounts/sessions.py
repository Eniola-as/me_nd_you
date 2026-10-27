from functools import partial

from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone

from play.services import notify_user_signed_out


def sign_out_everywhere(user):
    """End every session of this user and, after commit, close their open
    game connections. A password change already invalidates old sessions on
    their next request (Django's session hash); deleting them as well leaves
    nothing behind. Sessions are stored in the database (the default)."""
    user_id = str(user.pk)
    ended = [
        session.pk
        for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator()
        if session.get_decoded().get(SESSION_KEY) == user_id
    ]
    Session.objects.filter(pk__in=ended).delete()
    transaction.on_commit(partial(notify_user_signed_out, user.pk))
