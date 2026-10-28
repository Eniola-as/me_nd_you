import hashlib
import hmac
import json

from django.conf import settings


def chat_group_name(couple_id):
    """The Channels group of one couple's chat: an HMAC of the couple id, so
    it can't be guessed or chosen by a client."""
    payload = json.dumps(["chat", "couple", str(couple_id), "v1"]).encode()
    digest = hmac.new(settings.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()
    return f"chat.{digest}"


def chat_reader_group_name(user_id):
    """All one user's chat connections, so reading on one device clears the
    unread badge on the others. Separate from play's per-user group, whose
    members (game connections) don't handle chat events."""
    payload = json.dumps(["chat", "reader", str(user_id), "v1"]).encode()
    digest = hmac.new(settings.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()
    return f"chatreader.{digest}"
