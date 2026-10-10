import asyncio
from datetime import timedelta
from urllib.parse import parse_qs
from uuid import UUID

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db import transaction
from django.utils import timezone

from .events import room_event_message, room_group_name, room_snapshot
from .constants import RECONNECT_GRACE_SECONDS
from .models import Participant, Room

_CONNECTIONS = {}
_GRACE_TASKS = {}


def _register_connection(room_id, session_id, channel_name):
    key = (room_id, session_id)
    _CONNECTIONS.setdefault(key, set()).add(channel_name)


def _unregister_connection(room_id, session_id, channel_name):
    key = (room_id, session_id)
    channels = _CONNECTIONS.get(key)
    if channels is None:
        return True
    channels.discard(channel_name)
    if channels:
        return False
    _CONNECTIONS.pop(key, None)
    return True


def _cancel_grace_task(room_id, session_id):
    task = _GRACE_TASKS.pop((room_id, session_id), None)
    if task is not None and not task.done():
        task.cancel()


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
    participant = Participant.objects.select_related('room').filter(
        session_id=session_id,
        room__status=Room.Status.ACTIVE,
        left_at__isnull=True,
    ).first()
    if participant is None:
        return None
    return participant.room_id, str(participant.session_id)


@database_sync_to_async
def _mark_online(room_id, session_id):
    with transaction.atomic():
        room = Room.objects.select_for_update().filter(
            pk=room_id,
            status=Room.Status.ACTIVE,
        ).first()
        if room is None:
            return None
        participant = Participant.objects.select_for_update().filter(
            room=room,
            session_id=session_id,
            left_at__isnull=True,
        ).first()
        if participant is None:
            return None

        changed = (
            participant.presence != Participant.Presence.ONLINE
            or participant.disconnected_at is not None
        )
        participant.presence = Participant.Presence.ONLINE
        participant.disconnected_at = None
        if changed:
            participant.save(
                update_fields=('presence', 'disconnected_at', 'updated_at')
            )
        return room_snapshot(room), changed


@database_sync_to_async
def _mark_reconnecting(room_id, session_id):
    with transaction.atomic():
        room = Room.objects.select_for_update().filter(
            pk=room_id,
            status=Room.Status.ACTIVE,
        ).first()
        if room is None:
            return None
        participant = Participant.objects.select_for_update().filter(
            room=room,
            session_id=session_id,
            left_at__isnull=True,
        ).first()
        if participant is None:
            return None

        disconnected_at = timezone.now()
        participant.presence = Participant.Presence.RECONNECTING
        participant.disconnected_at = disconnected_at
        participant.save(
            update_fields=('presence', 'disconnected_at', 'updated_at')
        )
        return room_snapshot(room), disconnected_at


@database_sync_to_async
def _mark_inactive(room_id, session_id, disconnected_at):
    with transaction.atomic():
        room = Room.objects.select_for_update().filter(
            pk=room_id,
            status=Room.Status.ACTIVE,
        ).first()
        if room is None:
            return None
        participant = Participant.objects.select_for_update().filter(
            room=room,
            session_id=session_id,
            left_at__isnull=True,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=disconnected_at,
        ).first()
        if participant is None:
            return None
        if timezone.now() < disconnected_at + timedelta(seconds=RECONNECT_GRACE_SECONDS):
            return None

        participant.presence = Participant.Presence.INACTIVE
        participant.save(update_fields=('presence', 'updated_at'))
        return room_snapshot(room)


async def _publish_inactive_after_grace(room_id, session_id, disconnected_at, layer):
    try:
        await asyncio.sleep(RECONNECT_GRACE_SECONDS)
        if _CONNECTIONS.get((room_id, session_id)):
            return
        snapshot = await _mark_inactive(room_id, session_id, disconnected_at)
        if snapshot is not None and not _CONNECTIONS.get((room_id, session_id)):
            await layer.group_send(
                room_group_name(room_id),
                room_event_message('participant_inactive', snapshot),
            )
    except asyncio.CancelledError:
        raise
    finally:
        key = (room_id, session_id)
        if _GRACE_TASKS.get(key) is asyncio.current_task():
            _GRACE_TASKS.pop(key, None)


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
        await self.channel_layer.group_add(self.room_group, self.channel_name)
        _register_connection(self.room_id, self.session_id, self.channel_name)
        self.connection_registered = True
        _cancel_grace_task(self.room_id, self.session_id)

        online = await _mark_online(self.room_id, self.session_id)
        if online is None:
            await self.close(code=4401)
            return
        snapshot, changed = online

        await self.accept()
        await self.send_json({'type': 'room.snapshot', 'room': snapshot})
        if changed:
            await self.channel_layer.group_send(
                self.room_group,
                room_event_message('participant_online', snapshot),
            )

    async def room_event(self, event):
        if event.get('departed_session_id') == self.session_id:
            _cancel_grace_task(self.room_id, self.session_id)
            await self.send_json({'type': event['event'], 'room': event['room']})
            await self.close(code=4001)
            return
        await self.send_json({'type': event['event'], 'room': event['room']})

    async def disconnect(self, close_code):
        if self.room_group is not None:
            await self.channel_layer.group_discard(self.room_group, self.channel_name)

        if not self.connection_registered:
            return
        self.connection_registered = False
        if not _unregister_connection(self.room_id, self.session_id, self.channel_name):
            return

        reconnecting = await _mark_reconnecting(self.room_id, self.session_id)
        if reconnecting is None:
            return
        snapshot, disconnected_at = reconnecting
        await self.channel_layer.group_send(
            self.room_group,
            room_event_message('participant_reconnecting', snapshot),
        )

        key = (self.room_id, self.session_id)
        _cancel_grace_task(self.room_id, self.session_id)
        _GRACE_TASKS[key] = asyncio.create_task(
            _publish_inactive_after_grace(
                self.room_id,
                self.session_id,
                disconnected_at,
                self.channel_layer,
            )
        )
