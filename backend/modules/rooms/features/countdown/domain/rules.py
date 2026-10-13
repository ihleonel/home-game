"""Framework-free rules for the lobby countdown.

No Django, DRF, Channels or asyncio imports are allowed here: the rules read a
plain room snapshot and produce plain payloads, so both the use cases and their
fakes can share them.
"""

LOBBY_COUNTDOWN_SECONDS = 10

COUNTDOWN_EVENT = 'match_countdown'
COUNTDOWN_CANCELLED_EVENT = 'match_countdown_cancelled'

CANCELLED_LOBBY_CHANGED = 'lobby_changed'
CANCELLED_START_FAILED = 'start_failed'


def lobby_is_ready(snapshot, min_seats, max_seats):
    """Whether the snapshot is a complete, fully ready lobby.

    A lobby is ready only when its active roster length is inside
    ``[min_seats, max_seats]`` and every participant is ready. An empty roster
    is never ready, even if a game allowed a zero-seat minimum.
    """
    participants = snapshot.get('participants') or []
    if not participants:
        return False
    if not min_seats <= len(participants) <= max_seats:
        return False
    return all(participant.get('is_ready') for participant in participants)


def countdown_payload(seconds, remaining_seconds):
    return {'seconds': seconds, 'remaining_seconds': remaining_seconds}


def cancelled_payload(reason):
    return {'reason': reason}
