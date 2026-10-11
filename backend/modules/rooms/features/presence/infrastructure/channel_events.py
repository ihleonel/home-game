from ....events import room_event_message, room_group_name


async def add_to_room_group(channel_layer, room_group, channel_name):
    await channel_layer.group_add(room_group, channel_name)


async def remove_from_room_group(channel_layer, room_group, channel_name):
    await channel_layer.group_discard(room_group, channel_name)


async def publish_room_event(
    channel_layer,
    room_id,
    event_name,
    snapshot,
    departed_session_id=None,
    vote=None,
):
    await channel_layer.group_send(
        room_group_name(room_id),
        room_event_message(event_name, snapshot, departed_session_id, vote),
    )
