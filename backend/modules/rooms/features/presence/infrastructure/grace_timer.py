import asyncio

from ....connections import has_room_connection
from ....events import room_event_message, room_group_name

GRACE_TASKS = {}


def cancel_grace_task(room_id, session_id):
    task = GRACE_TASKS.pop((room_id, session_id), None)
    if task is not None and not task.done():
        task.cancel()


def schedule_grace_expiry(
    room_id,
    session_id,
    disconnected_at,
    channel_layer,
    grace_seconds,
    expire_presence,
):
    key = (room_id, session_id)
    cancel_grace_task(room_id, session_id)
    task = asyncio.create_task(
        publish_inactive_after_grace(
            room_id,
            session_id,
            disconnected_at,
            channel_layer,
            grace_seconds,
            expire_presence,
        )
    )
    GRACE_TASKS[key] = task
    return task


async def publish_inactive_after_grace(
    room_id,
    session_id,
    disconnected_at,
    channel_layer,
    grace_seconds,
    expire_presence,
):
    try:
        await asyncio.sleep(grace_seconds)
        if has_room_connection(room_id, session_id):
            return
        presence_event = await expire_presence(
            room_id, session_id, disconnected_at, grace_seconds
        )
        if presence_event is not None and not has_room_connection(room_id, session_id):
            await channel_layer.group_send(
                room_group_name(room_id),
                room_event_message(
                    presence_event.name,
                    presence_event.snapshot,
                    vote=presence_event.vote,
                ),
            )
    except asyncio.CancelledError:
        raise
    finally:
        key = (room_id, session_id)
        if GRACE_TASKS.get(key) is asyncio.current_task():
            GRACE_TASKS.pop(key, None)
