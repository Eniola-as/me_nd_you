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
