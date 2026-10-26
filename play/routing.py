from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(r"ws/room/(?P<game>[a-z_]{1,30})/(?P<variant>[a-z_]{1,20})/$", consumers.RoomConsumer.as_asgi()),
]
