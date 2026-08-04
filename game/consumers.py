import json
from channels.generic.websocket import AsyncWebsocketConsumer


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
        data = json.loads(text_data)
        # Only handle question-related messages
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "send_question",
                "userId": data["userId"],
                "questions": data["questions"],
            },
        )

    async def send_question(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "userId": event["userId"],
                    "questions": event["questions"],
                }
            )
        )
