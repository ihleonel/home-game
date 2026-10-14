"""Rejections raised by the framework-free match runtime.

Every rejection is a plain ``Exception`` subclass so the use cases stay free
of any framework; adapters translate them into transport responses. No Django,
DRF or Channels imports are allowed here.
"""


class MatchError(Exception):
    """Base class for every rejection raised by the match runtime."""


class UnknownGame(MatchError):
    """No registered game definition matches the requested game id."""

    def __init__(self, game_id):
        self.game_id = game_id
        super().__init__(f'unknown game: {game_id!r}')


class WrongSeatCount(MatchError):
    """The requested seat count is outside the game's allowed range."""

    def __init__(self, game_id, count, min_seats, max_seats):
        self.game_id = game_id
        self.count = count
        self.min_seats = min_seats
        self.max_seats = max_seats
        super().__init__(
            f'game {game_id!r} accepts {min_seats}..{max_seats} seats, got {count}'
        )


class MatchNotFound(MatchError):
    """No match exists for the requested match reference."""

    def __init__(self, match_ref):
        self.match_ref = match_ref
        super().__init__(f'match not found: {match_ref!r}')


class MatchNotPlayable(MatchError):
    """The match is finished and can no longer accept actions."""

    def __init__(self, match_ref, status):
        self.match_ref = match_ref
        self.status = status
        super().__init__(f'match {match_ref!r} is not playable (status={status!r})')


class NotASeat(MatchError):
    """The participant occupies no seat in the match."""

    def __init__(self, match_ref, participant_ref):
        self.match_ref = match_ref
        self.participant_ref = participant_ref
        super().__init__(
            f'participant {participant_ref!r} occupies no seat in match {match_ref!r}'
        )


class StaleVersion(MatchError):
    """The submitted version does not match the persisted match version."""

    def __init__(self, match_ref, expected_version, actual_version):
        self.match_ref = match_ref
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            f'stale version for match {match_ref!r}: '
            f'expected {expected_version}, current {actual_version}'
        )


class NotYourTurn(MatchError):
    """The seat is not active in the current state."""

    def __init__(self, seat_id):
        self.seat_id = seat_id
        super().__init__(f'seat {seat_id!r} is not active')


class IllegalAction(MatchError):
    """The action name is not offered, or its value is not an allowed option."""

    def __init__(self, action_name, seat_id):
        self.action_name = action_name
        self.seat_id = seat_id
        super().__init__(f'illegal action {action_name!r} for seat {seat_id!r}')
