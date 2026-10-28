"""WebSocket for a couple's private chat (/ws/chat/).

Protocol (JSON):
- server -> client on connect: {"type": "history", "messages": [...],
  "has_more": bool}, the latest messages, oldest first.
- client -> server:
  {"type": "send", "text": "...", "requestId": "<uuid>"}
  {"type": "delete", "id": n}  (your own messages only)
  {"type": "history", "before": n}  (older messages)
  {"type": "read", "upTo": n}  (moves your unread marker; only your own
  other connections hear about it, never your partner)
- server -> both members: {"type": "message", "message": {...}} and
  {"type": "deleted", "id": n}.
- server -> sender only: {"type": "error", "reason": "invalid" |
  "rate_limited" | "unavailable" | "forbidden", "requestId": ..., "detail":
  ...}. "forbidden" closes the connection.

Membership is re-checked on every message and every broadcast, so a member
who leaves gets nothing more. Closing the couple or resetting a password
closes the connection at once.
"""

import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from play.groups import user_group_name

MAX_MESSAGE_CHARS = 5_000
FORBIDDEN_CLOSE_CODE = 4403


@database_sync_to_async
def open_chat(user):
    from . import services

    couple_id = services.active_couple_id(user)
    if couple_id is None:
        return None
    try:
        return couple_id, services.history(user, couple_id)
    except services.Forbidden:
        return None


@database_sync_to_async
def call(function, *args):
    return function(*args)


class ChatConsumer(AsyncWebsocketConsumer):
    couple_id = None
    group = None
    user_group = None
    reader_group = None

    async def connect(self):
        from .groups import chat_group_name, chat_reader_group_name

        self.user = self.scope.get("user")
        opened = await open_chat(self.user)
        if opened is None:
            await self.close()
            return
        self.couple_id, history = opened
        self.group = chat_group_name(self.couple_id)
        self.user_group = user_group_name(self.user.pk)
        self.reader_group = chat_reader_group_name(self.user.pk)
        for group in (self.group, self.user_group, self.reader_group):
            await self.channel_layer.group_add(group, self.channel_name)
        await self.accept()
        await self.send_json({"type": "history", "initial": True, **history})

    async def disconnect(self, close_code):
        for group in (self.group, self.user_group, self.reader_group):
            if group:
                await self.channel_layer.group_discard(group, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        from . import crypto, services

        message = _parse(text_data)
        if message is None:
            await self.send_error("invalid", detail="Unrecognised message.")
            return
        request_id = message.get("requestId") if isinstance(message.get("requestId"), str) else None
        try:
            if message["type"] == "send":
                await call(services.send, self.user, self.couple_id, message.get("text"), message.get("requestId"))
            elif message["type"] == "delete":
                await call(services.delete, self.user, self.couple_id, message.get("id"))
            elif message["type"] == "read":
                await call(services.mark_read, self.user, self.couple_id, message.get("upTo"))
            elif message["type"] == "history":
                older = await call(services.history, self.user, self.couple_id, message.get("before"))
                await self.send_json({"type": "history", **older})
        except services.Forbidden:
            await self.revoke(request_id)
        except services.RateLimited as error:
            await self.send_error("rate_limited", request_id, str(error))
        except services.Invalid as error:
            await self.send_error("invalid", request_id, str(error))
        except crypto.ChatKeyMissing:
            await self.send_error("unavailable", request_id, "Chat isn't available right now.")

    # Broadcasts carry only ids; each connection re-checks its own user's
    # membership before sending anything.
    async def chat_message(self, event):
        from . import crypto, services

        try:
            shown = await call(services.message_for, self.user, self.couple_id, event["id"])
        except services.Forbidden:
            await self.revoke()
            return
        except crypto.ChatKeyMissing:
            return
        if shown is not None:
            await self.send_json({"type": "message", "message": shown})

    async def chat_deleted(self, event):
        from . import services

        try:
            await call(services.membership, self.user, self.couple_id)
        except services.Forbidden:
            await self.revoke()
            return
        await self.send_json({"type": "deleted", "id": event["id"]})

    async def chat_read(self, event):
        await self.send_json({"type": "read", "upTo": event["upTo"]})

    async def chat_closed(self, event):
        await self.revoke()

    async def user_signed_out(self, event):
        await self.revoke()

    async def send_json(self, data):
        await self.send(text_data=json.dumps(data))

    async def send_error(self, reason, request_id=None, detail=""):
        await self.send_json({"type": "error", "reason": reason, "requestId": request_id, "detail": detail})

    async def revoke(self, request_id=None):
        await self.send_error("forbidden", request_id, "You no longer have access to this chat.")
        await self.close(code=FORBIDDEN_CLOSE_CODE)


def _parse(text_data):
    if text_data is None or len(text_data) > MAX_MESSAGE_CHARS:
        return None
    try:
        message = json.loads(text_data)
    except ValueError:
        return None
    if not isinstance(message, dict) or message.get("type") not in {"send", "delete", "history", "read"}:
        return None
    return message
