"""Compatibility exports for the room WebSocket interface adapter."""

from .constants import RECONNECT_GRACE_SECONDS
from .events import room_event_message, room_group_name
from .features.presence.infrastructure.grace_timer import (
    GRACE_TASKS as _GRACE_TASKS,
    cancel_grace_task as _cancel_grace_task,
)
from .interfaces import websocket as _websocket

_active_membership = _websocket._active_membership
_mark_inactive = _websocket._mark_inactive
_mark_inactive_event = _websocket._mark_inactive_event
_mark_online = _websocket._mark_online
_mark_reconnecting = _websocket._mark_reconnecting
_session_id_from_scope = _websocket._session_id_from_scope


async def _publish_inactive_after_grace(
    room_id, session_id, disconnected_at, layer
):
    await _websocket.publish_inactive_after_grace(
        room_id,
        session_id,
        disconnected_at,
        layer,
        RECONNECT_GRACE_SECONDS,
    )


class RoomConsumer(_websocket.RoomConsumer):
    def reconnect_grace_seconds(self):
        return RECONNECT_GRACE_SECONDS


__all__ = (
    'RECONNECT_GRACE_SECONDS',
    'RoomConsumer',
    '_GRACE_TASKS',
    '_active_membership',
    '_cancel_grace_task',
    '_mark_inactive',
    '_mark_inactive_event',
    '_mark_online',
    '_mark_reconnecting',
    '_publish_inactive_after_grace',
    '_session_id_from_scope',
    'room_event_message',
    'room_group_name',
)
