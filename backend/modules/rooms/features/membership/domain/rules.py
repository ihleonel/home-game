from dataclasses import dataclass


@dataclass(frozen=True)
class MembershipChange:
    updates: tuple[tuple[str, object], ...]
    event_name: str | None


def membership_change(
    *,
    was_left,
    was_disconnected,
    current_display_name,
    current_game_marker,
    data,
):
    """Resolve identity and reconnect changes without persistence dependencies."""
    updates = {}
    identity_updated = False
    for field, current_value in (
        ('display_name', current_display_name),
        ('game_marker', current_game_marker),
    ):
        if field in data and current_value != data[field]:
            updates[field] = data[field]
            identity_updated = True
    if was_left:
        updates['left_at'] = None
    if was_left or was_disconnected:
        updates.update(presence='offline', disconnected_at=None)

    if was_left or was_disconnected:
        event_name = 'player_joined'
    elif identity_updated:
        event_name = 'player_updated'
    else:
        event_name = None
    return MembershipChange(tuple(updates.items()), event_name)


def missing_identity_fields(data):
    return {
        field: 'Este campo es obligatorio para participar en una sala nueva.'
        for field in ('display_name', 'game_marker')
        if field not in data
    }


def game_matches(room_game_id, requested_game_id):
    return room_game_id == requested_game_id


def is_disconnected_presence(presence):
    return presence in ('reconnecting', 'inactive')


def can_leave(is_ready):
    return not is_ready


def leave_changes(left_at):
    return (
        ('left_at', left_at),
        ('presence', 'offline'),
        ('disconnected_at', None),
    )
