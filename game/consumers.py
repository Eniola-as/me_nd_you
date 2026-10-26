import hashlib
import hmac
import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings

# Game messages are a question or two; anything far larger is abuse.
MAX_MESSAGE_CHARS = 8_000
MAX_USER_ID_CHARS = 64
MAX_QUESTION_CHARS = 500  # Same limit as custom questions.

# The message contract shared with static/js/game-messages.js. Every message
# is a JSON object with a "type" and the sending page's "userId".
#   question       {question: text}                   partner pressed Next
#   reset          {seed: int}                        partner pressed Reset
#   sync_request   {}                                 a page (re)connected
#   sync_response  {seed: int|null, currentQuestion: text|null}
INVALID_MESSAGE = {"type": "error", "reason": "invalid_message"}


def is_text(value, max_chars):
    return isinstance(value, str) and 0 < len(value) <= max_chars


def is_seed(value):
    return isinstance(value, int) and not isinstance(value, bool)


def parse_message(text_data):
    """Return the message rebuilt from its allowed fields, or None if it
    doesn't match the contract. Unexpected fields are dropped."""
    try:
        data = json.loads(text_data)
    except ValueError:
        return None
    if not isinstance(data, dict) or not is_text(data.get("userId"), MAX_USER_ID_CHARS):
        return None
    kind, user_id = data.get("type"), data["userId"]

    if kind == "question" and is_text(data.get("question"), MAX_QUESTION_CHARS):
        return {"type": kind, "userId": user_id, "question": data["question"]}
    if kind == "reset" and is_seed(data.get("seed")):
        return {"type": kind, "userId": user_id, "seed": data["seed"]}
    if kind == "sync_request":
        return {"type": kind, "userId": user_id}
    if kind == "sync_response":
        seed, current = data.get("seed"), data.get("currentQuestion")
        if (seed is None or is_seed(seed)) and (
            current is None or is_text(current, MAX_QUESTION_CHARS)
        ):
            return {"type": kind, "userId": user_id, "seed": seed, "currentQuestion": current}
    return None


def room_group_name(secret, mode):
    """The Channels group for one couple's secret and game mode.

    Channels only allows ASCII letters, digits, "-", "_" and "." in group
    names, under 100 characters, so the name is an HMAC-SHA256 digest: valid
    for any secret, and the raw secret never appears in it. The pair is
    JSON-encoded so a secret and a mode can't be shifted into each other
    ("love_truth" + "questions" vs "love" + "truth_questions"). Keying with
    SECRET_KEY stops anyone who sees a group name (e.g. in Redis) from
    guessing the secret offline; rotating the key only renames live rooms.
    """
    return _group_name([secret, mode])


def space_group_name(couple_id, mode):
    """The Channels group for a couple space and game mode. A three-part
    JSON list can never equal room_group_name's two-part one, so no secret
    word can be chosen to land in a space's room."""
    return _group_name(["space", str(couple_id), mode])


def _group_name(parts):
    payload = json.dumps(parts).encode()
    digest = hmac.new(settings.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()
    return f"game.{digest}"


@database_sync_to_async
def open_session(secret):
    """True if the secret belongs to an active session, which then counts as
    active. Unknown and expired secrets are refused the same way."""
    # Imported here: asgi.py loads this module before Django's apps are ready.
    from .models import CoupleSession

    session = CoupleSession.find_active(secret)
    if session is None:
        return False
    session.touch()
    return True


@database_sync_to_async
def space_for(user):
    """The id of the user's active couple space, or None."""
    from couples.services import active_couple

    if user is None or not user.is_authenticated:
        return None
    couple = active_couple(user)
    return str(couple.id) if couple else None


class GameConsumer(AsyncWebsocketConsumer):
    room_group_name = None

    async def connect(self):
        route = self.scope["url_route"]["kwargs"]
        if not await open_session(route["room_name"]):
            await self.close()
            return
        self.room_group_name = room_group_name(route["room_name"], route["mode"])
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if self.room_group_name:  # Not set when the connection was refused.
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        if len(text_data) > MAX_MESSAGE_CHARS:
            await self.close(code=1009)  # 1009: message too big
            return
        message = parse_message(text_data)
        if message is None:
            # Tell only the sender; keep the connection open.
            await self.send(text_data=json.dumps(INVALID_MESSAGE))
            return
        # Everyone in the room gets it, the sender included; pages ignore
        # their own messages by userId.
        await self.channel_layer.group_send(
            self.room_group_name, {"type": "relay_message", "message": message}
        )

    async def relay_message(self, event):
        await self.send(text_data=json.dumps(event["message"]))


class SpaceGameConsumer(GameConsumer):
    """The game room of the signed-in user's couple space. Access comes from
    the session (Channels' auth middleware) and an active membership,
    checked when connecting; nothing in the URL grants it."""

    async def connect(self):
        couple_id = await space_for(self.scope.get("user"))
        if couple_id is None:
            await self.close()
            return
        mode = self.scope["url_route"]["kwargs"]["mode"]
        self.room_group_name = space_group_name(couple_id, mode)
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
