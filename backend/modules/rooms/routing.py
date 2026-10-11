from django.urls import path

from .consumers import RoomConsumer

websocket_urlpatterns = [
    path('ws/rooms/active/', RoomConsumer.as_asgi()),
]
