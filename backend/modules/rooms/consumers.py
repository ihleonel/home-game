from urllib.parse import parse_qs
from uuid import UUID

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .constants import RECONNECT_GRACE_SECONDS
from .connections import register_connection, unregister_connection
from .events import room_event_message, room_group_name
from .features.presence.application.use_cases import (
    find_active_membership,
    mark_inactive,
    mark_online,
    mark_reconnecting,
)
from .features.presence.infrastructure.channel_events import (
    add_to_room_group,
    publish_room_event,
    remove_from_room_group,
)
from .features.presence.infrastructure.django_gateway import DjangoPresenceGateway
from .features.presence.infrastructure.grace_timer import (
    GRACE_TASKS as _GRACE_TASKS,
    cancel_grace_task as _cancel_task,
    publish_inactive_after_grace,
    schedule_grace_expiry,
)


def _cancel_grace_task(room_id, session_id):
    _cancel_task(room_id, session_id)


def _session_id_from_scope(scope):
    try:
        query = parse_qs(scope.get('query_string', b'').decode('utf-8'))
    except UnicodeDecodeError:
        return None
    tokens = query.get('session_id', [])
    if len(tokens) != 1:
        return None
    try:
        return str(UUID(tokens[0]))
    except (AttributeError, ValueError):
        return None


@database_sync_to_async
def _active_membership(session_id):
    return find_active_membership(DjangoPresenceGateway(), session_id)


@database_sync_to_async
def _mark_online(room_id, session_id):
    return mark_online(DjangoPresenceGateway(), room_id, session_id)


@database_sync_to_async
def _mark_reconnecting(room_id, session_id):
    return mark_reconnecting(DjangoPresenceGateway(), room_id, session_id)


@database_sync_to_async
def _mark_inactive(room_id, session_id, disconnected_at, grace_seconds=None):
    event = mark_inactive(
        DjangoPresenceGateway(),
        room_id,
        session_id,
        disconnected_at,
        RECONNECT_GRACE_SECONDS if grace_seconds is None else grace_seconds,
    )
    return event.snapshot if event is not None else None


@database_sync_to_async
def _mark_inactive_event(room_id, session_id, disconnected_at, grace_seconds=None):
    return mark_inactive(
        DjangoPresenceGateway(),
        room_id,
        session_id,
        disconnected_at,
        RECONNECT_GRACE_SECONDS if grace_seconds is None else grace_seconds,
    )


async def _expire_presence(room_id, session_id, disconnected_at, grace_seconds):
    return await _mark_inactive_event(
        room_id, session_id, disconnected_at, grace_seconds
    )


async def _publish_inactive_after_grace(
    room_id, session_id, disconnected_at, layer
):
    await publish_inactive_after_grace(
        room_id,
        session_id,
        disconnected_at,
        layer,
        RECONNECT_GRACE_SECONDS,
        _expire_presence,
    )


class RoomConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.room_id = None
        self.session_id = _session_id_from_scope(self.scope)
        self.room_group = None
        self.connection_registered = False

        if self.session_id is None:
            await self.close(code=4401)
            return

        membership = await _active_membership(self.session_id)
        if membership is None:
            await self.close(code=4401)
            return

        self.room_id, self.session_id = membership
        self.room_group = room_group_name(self.room_id)
        await add_to_room_group(
            self.channel_layer, self.room_group, self.channel_name
        )
        register_connection(self.room_id, self.session_id, self.channel_name)
        self.connection_registered = True
        _cancel_grace_task(self.room_id, self.session_id)

        online = await _mark_online(self.room_id, self.session_id)
        if online is None:
            await self.close(code=4401)
            return
        snapshot, events = online

        await self.accept()
        await self.send_json({'type': 'room.snapshot', 'room': snapshot})
        for event in events:
            await publish_room_event(
                self.channel_layer,
                self.room_id,
                event.name,
                event.snapshot,
                vote=event.vote,
            )

    async def room_event(self, event):
        client_event = {'type': event['event'], 'room': event['room']}
        if 'vote' in event:
            client_event['vote'] = event['vote']
        if event.get('departed_session_id') == self.session_id:
            _cancel_grace_task(self.room_id, self.session_id)
            await self.send_json(client_event)
            await self.close(code=4001)
            return
        await self.send_json(client_event)

    async def disconnect(self, close_code):
        if self.room_group is not None:
            await remove_from_room_group(
                self.channel_layer, self.room_group, self.channel_name
            )

        if not self.connection_registered:
            return
        self.connection_registered = False
        if not unregister_connection(self.room_id, self.session_id, self.channel_name):
            return

        reconnecting = await _mark_reconnecting(self.room_id, self.session_id)
        if reconnecting is None:
            return
        snapshot, disconnected_at, events = reconnecting
        for event in events:
            await publish_room_event(
                self.channel_layer,
                self.room_id,
                event.name,
                event.snapshot,
                vote=event.vote,
            )

        schedule_grace_expiry(
            self.room_id,
            self.session_id,
            disconnected_at,
            self.channel_layer,
            RECONNECT_GRACE_SECONDS,
            _expire_presence,
        )
