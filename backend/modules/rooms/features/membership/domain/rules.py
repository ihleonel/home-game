from dataclasses import dataclass


@dataclass(frozen=True)
class MembershipChange:
    update_fields: tuple[str, ...]
    event_name: str | None


def membership_change(
    *,
    was_left,
    was_disconnected,
    current_display_name,
    current_game_marker,
    data,
):
    """Describe the persisted changes for an existing participant without ORM types."""
    update_fields = []
    identity_updated = False
    for field, current_value in (
        ('display_name', current_display_name),
        ('game_marker', current_game_marker),
    ):
        if field in data and current_value != data[field]:
            update_fields.append(field)
            identity_updated = True
    if was_left:
        update_fields.append('left_at')
    if was_left or was_disconnected:
        update_fields.extend(('presence', 'disconnected_at'))

    if was_left or was_disconnected:
        event_name = 'player_joined'
    elif identity_updated:
        event_name = 'player_updated'
    else:
        event_name = None
    return MembershipChange(tuple(update_fields), event_name)
