from dataclasses import dataclass


PLAYER_ROLE = 'player'
SPECTATOR_ROLE = 'spectator'


@dataclass(frozen=True)
class MembershipChange:
    updates: tuple[tuple[str, object], ...]
    event_name: str | None


def resolve_entry_role(
    *, as_spectator, match_in_progress, active_players, max_seats
):
    """Resolve a new participant's role in the exact S2 order.

    The policy is derived from the game contract: the caller passes the room's
    game ``max_seats``, never a per-game list. A room already at capacity or
    with a match in progress admits only spectators; an explicit request wins
    over any free seat.
    """
    if as_spectator:
        return SPECTATOR_ROLE
    if match_in_progress:
        return SPECTATOR_ROLE
    if max_seats is not None and active_players >= max_seats:
        return SPECTATOR_ROLE
    return PLAYER_ROLE


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
