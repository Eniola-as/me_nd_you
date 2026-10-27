import hashlib
import hmac
import json

from django.conf import settings


def room_group_name(room_id):
    """The Channels group of one game room. Its HMAC input is a four-part
    JSON list, so it can never equal a legacy secret-word room's (two-part)
    group name, whatever a client puts in a URL."""
    payload = json.dumps(["play", "room", str(room_id), "v1"]).encode()
    digest = hmac.new(settings.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()
    return f"game.{digest}"
