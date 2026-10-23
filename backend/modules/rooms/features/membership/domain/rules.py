from dataclasses import dataclass


PLAYER_ROLE = 'player'
SPECTATOR_ROLE = 'spectator'
SPECTATOR_NAME_PREFIX = 'Espectador'
MISSING_IDENTITY_MESSAGE = (
    'Este campo es obligatorio para participar en una sala nueva.'
)


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


def resolve_returning_role(
    *, current_role, as_spectator, match_in_progress, active_players, max_seats
):
    """Resolve the role of a membership that comes back after leaving.

    A returning session is admitted by the same policy that admits a new
    arrival, but the outcome can only keep or reduce its role: a stored
    spectator is never promoted without asking (S5), and a stored player is
    demoted to spectator exactly when the room has no seat left for it. The
    row already exists, so this is the only place that can keep the room's
    player count at or below ``max_seats`` after a seat was given away while
    its former holder was out (a leave or a reap).
    """
    if current_role != PLAYER_ROLE:
        return SPECTATOR_ROLE
    return resolve_entry_role(
        as_spectator=as_spectator,
        match_in_progress=match_in_progress,
        active_players=active_players,
        max_seats=max_seats,
    )


def can_take_player_seat(
    *, role, match_in_progress, active_players, max_seats
):
    """The S5 promotion gate, derived from the game contract.

    A spectator only takes a seat in a lobby: never during an ``in_progress``
    match, and only while the count of active players is below the room's
    game ``max_seats``. An unknown game has no limit to compare against, so it
    can never grant a seat.
    """
    if role != SPECTATOR_ROLE:
        return False
    if match_in_progress:
        return False
    if max_seats is None:
        return False
    return active_players < max_seats


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


def missing_identity_fields(identity):
    """The identity values a new participant still has to carry (S4).

    An explicit spectator may arrive without them: the platform assigns the
    missing ones before this check, and a player entry never does.
    """
    return {
        field: MISSING_IDENTITY_MESSAGE
        for field in ('display_name', 'game_marker')
        if not identity.get(field)
    }


def next_spectator_display_name(used_display_names):
    """The first free ``Espectador N`` name in the room (S4).

    The number is per room and deterministic, so two anonymous spectators
    never collide and a player who is already called ``Espectador 1`` is
    respected instead of duplicated.
    """
    number = 1
    while f'{SPECTATOR_NAME_PREFIX} {number}' in used_display_names:
        number += 1
    return f'{SPECTATOR_NAME_PREFIX} {number}'


def first_free_game_marker(used_game_markers, seat_option_ids):
    """The first marker the room is not using, else the game's first (S4).

    A spectator holds no seat, so its marker is only the visual chip the
    roster and the match screen show. It must still be an option the game
    offers, and a room that already uses every option falls back to the first
    one instead of inventing an unknown marker.
    """
    for option_id in seat_option_ids:
        if option_id not in used_game_markers:
            return option_id
    return seat_option_ids[0] if seat_option_ids else None


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
