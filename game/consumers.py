import json
from channels.generic.websocket import AsyncWebsocketConsumer

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


class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_name = self.scope["url_route"]["kwargs"]["room_name"]
        self.mode = self.scope["url_route"]["kwargs"]["mode"]
        self.room_group_name = f"game_{self.room_name}_{self.mode}"
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
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
