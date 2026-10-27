import hashlib
import hmac
import json

from django.conf import settings


def room_group_name(room_id):
    """The Channels group of one game room: an HMAC of the room id, so the
    name is valid for Channels and can't be guessed or chosen by a client."""
    payload = json.dumps(["play", "room", str(room_id), "v1"]).encode()
    digest = hmac.new(settings.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()
    return f"game.{digest}"
