"""WebSocket for server-authoritative game rooms.

Protocol (JSON):
- server -> client on connect and after every committed change:
  {"type": "state", "version": n, "state": {...this player's view...}}
- client -> server:
  {"type": "action", "action": "next", "expectedVersion": n,
   "requestId": "<uuid>", "payload": {...optional...}}
  {"type": "sync"} asks for the current state again.
- server -> sender only: {"type": "error", "reason": "stale" | "forbidden" |
  "invalid", "requestId": ..., "detail": ...}; a stale action is followed by
  the current state. "forbidden" closes the connection.

The database is imported inside the functions below because asgi.py loads
this module before Django's apps are ready.
"""

import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .groups import room_group_name

MAX_MESSAGE_CHARS = 2_000
FORBIDDEN_CLOSE_CODE = 4403


@database_sync_to_async
def open_room(user, game, variant):
    from . import services

    try:
        room = services.room_for(user, game, variant)
        return room.pk, services.snapshot(room, user)
    except services.PlayError:
        return None


@database_sync_to_async
def current_snapshot(user, room_id):
    from . import services
    from .models import GameRoom

    room = GameRoom.objects.filter(pk=room_id).first()
    if room is None:
        raise services.Forbidden()
    return services.snapshot(room, user)


@database_sync_to_async
def perform(user, room_id, message):
    from . import services

    room = services.apply_action(
        user, room_id, message["action"], message["expectedVersion"],
        message.get("requestId"), message.get("payload"),
    )
    return services.snapshot(room, user)


def parse_action(text_data):
    try:
        message = json.loads(text_data)
    except ValueError:
        return None
    if not isinstance(message, dict):
        return None
    if message.get("type") == "sync":
        return message
    if (
        message.get("type") != "action"
        or not isinstance(message.get("action"), str)
        or len(message["action"]) > 30
        or type(message.get("expectedVersion")) is not int
        or not isinstance(message.get("requestId"), (str, type(None)))
        or not isinstance(message.get("payload"), (dict, type(None)))
    ):
        return None
    return message


class RoomConsumer(AsyncWebsocketConsumer):
    room_id = None
    group = None
    last_version = 0

    async def connect(self):
        kwargs = self.scope["url_route"]["kwargs"]
        self.user = self.scope.get("user")
        opened = await open_room(self.user, kwargs["game"], kwargs["variant"])
        if opened is None:
            await self.close()
            return
        self.room_id, snapshot = opened
        self.group = room_group_name(self.room_id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await self.send_state(snapshot, force=True)

    async def disconnect(self, close_code):
        if self.group:
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        from . import services

        if text_data is None or len(text_data) > MAX_MESSAGE_CHARS:
            await self.send_error("invalid", detail="Message too large.")
            return
        message = parse_action(text_data)
        if message is None:
            await self.send_error("invalid", detail="Unrecognised message.")
            return
        request_id = message.get("requestId")
        try:
            if message["type"] == "sync":
                await self.send_state(await current_snapshot(self.user, self.room_id), force=True)
                return
            # Success is confirmed only by a state from the committed change.
            await self.send_state(await perform(self.user, self.room_id, message))
        except services.Stale as stale:
            await self.send_error("stale", request_id)
            await self.send_state(
                stale.snapshot or await current_snapshot(self.user, self.room_id), force=True
            )
        except services.Invalid as error:
            await self.send_error("invalid", request_id, detail=str(error))
        except services.Forbidden:
            await self.revoke(request_id)

    async def room_updated(self, event):
        """A change committed; send this player's own view of it."""
        from . import services

        if event["version"] <= self.last_version:
            return
        try:
            await self.send_state(await current_snapshot(self.user, self.room_id))
        except services.Forbidden:
            await self.revoke()

    async def room_closed(self, event):
        await self.revoke()

    async def send_state(self, snapshot, force=False):
        if force or snapshot["version"] > self.last_version:
            self.last_version = max(self.last_version, snapshot["version"])
            await self.send(text_data=json.dumps(snapshot))

    async def send_error(self, reason, request_id=None, detail=""):
        await self.send(text_data=json.dumps(
            {"type": "error", "reason": reason, "requestId": request_id, "detail": detail}
        ))

    async def revoke(self, request_id=None):
        await self.send_error("forbidden", request_id, detail="You no longer have access to this game.")
        await self.close(code=FORBIDDEN_CLOSE_CODE)
