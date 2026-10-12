import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

from .snapshots import room_snapshot

logger = logging.getLogger(__name__)


def room_group_name(room_id):
    return f'room_{room_id}'


def room_event_message(event_name, snapshot, departed_session_id=None, vote=None):
    message = {
        'type': 'room.event',
        'event': event_name,
        'room': snapshot,
    }
    if departed_session_id is not None:
        message['departed_session_id'] = str(departed_session_id)
    if vote is not None:
        message['vote'] = vote
    return message


def broadcast_room_event(
    room_id,
    event_name,
    snapshot,
    departed_session_id=None,
    vote=None,
):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    try:
        async_to_sync(channel_layer.group_send)(
            room_group_name(room_id),
            room_event_message(event_name, snapshot, departed_session_id, vote),
        )
    except Exception:
        logger.exception('Unable to broadcast a room event.')


def schedule_room_event(
    room_id,
    event_name,
    snapshot,
    departed_session_id=None,
    vote=None,
):
    transaction.on_commit(
        lambda: broadcast_room_event(
            room_id,
            event_name,
            snapshot,
            departed_session_id,
            vote,
        )
    )
