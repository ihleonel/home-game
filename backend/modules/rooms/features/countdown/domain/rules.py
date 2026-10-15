"""Framework-free rules for the lobby countdown.

No Django, DRF, Channels or asyncio imports are allowed here: the rules read a
plain room snapshot and produce plain payloads, so both the use cases and their
fakes can share them.
"""

from ...membership.domain.rules import PLAYER_ROLE

LOBBY_COUNTDOWN_SECONDS = 10

COUNTDOWN_EVENT = 'match_countdown'
COUNTDOWN_CANCELLED_EVENT = 'match_countdown_cancelled'

CANCELLED_LOBBY_CHANGED = 'lobby_changed'
CANCELLED_START_FAILED = 'start_failed'


def lobby_is_ready(snapshot, min_seats, max_seats):
    """Whether the snapshot is a complete, fully ready lobby.

    A lobby is ready only when its active players are inside
    ``[min_seats, max_seats]`` and every one of them is ready. Spectators are
    not players, so they neither fill a seat nor block a start; a participant
    whose snapshot predates the ``role`` field counts as a player. An empty
    player roster is never ready, even if a game allowed a zero-seat minimum.
    """
    participants = snapshot.get('participants') or []
    players = [
        participant
        for participant in participants
        if participant.get('role', PLAYER_ROLE) == PLAYER_ROLE
    ]
    if not players:
        return False
    if not min_seats <= len(players) <= max_seats:
        return False
    return all(participant.get('is_ready') for participant in players)


def countdown_payload(seconds, remaining_seconds):
    return {'seconds': seconds, 'remaining_seconds': remaining_seconds}


def cancelled_payload(reason):
    return {'reason': reason}
