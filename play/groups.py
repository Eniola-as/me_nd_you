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


def user_group_name(user_id):
    """The Channels group of all one user's game connections, named the same
    way, so they can be closed together (for example after a password reset)."""
    payload = json.dumps(["play", "user", str(user_id), "v1"]).encode()
    digest = hmac.new(settings.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()
    return f"user.{digest}"


def mode_group_name(user_id):
    """The Channels group that tells one user's member pages about the
    couple's game mode (joined by the chat connection every member page has)."""
    payload = json.dumps(["play", "mode", str(user_id), "v1"]).encode()
    digest = hmac.new(settings.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()
    return f"mode.{digest}"
