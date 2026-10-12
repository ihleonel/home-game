"""``start_match`` use case: open a match of a registered game."""

from ...contracts import Seat, seat_id
from ..domain.errors import UnknownGame, WrongSeatCount
from .views import seat_views
from .ports import MatchRecord, SeatRecord


def start_match(
    *,
    room_id,
    game_id,
    seats,
    store,
    registry,
    projector,
    rng=None,
) -> MatchRecord:
    """Create a match of ``game_id`` and publish its opening views.

    ``seats`` is a sequence of ``(index, participant_ref, badge)`` tuples. The
    runtime derives each ``seat_id`` from its index through the shared
    ``seat_id`` helper so the id convention lives in exactly one place. A
    duplicate index is a programming error: it would put two participants on
    one seat id and corrupt the state, so it raises ``ValueError`` instead of
    being silently deduplicated. A duplicate ``participant_ref`` is rejected
    the same way.
    """
    definition = registry.get(game_id)
    if definition is None:
        raise UnknownGame(game_id)
    if not definition.min_seats <= len(seats) <= definition.max_seats:
        raise WrongSeatCount(
            game_id, len(seats), definition.min_seats, definition.max_seats
        )

    records = _seat_records(seats)
    definition_seats = tuple(
        Seat(
            index=record.index,
            participant_ref=record.participant_ref,
            badge=record.badge,
        )
        for record in records
    )
    state = definition.start(definition_seats, rng)

    with store.unit_of_work():
        record = store.create(
            room_id=room_id,
            game_id=game_id,
            state=state,
            seats=tuple(records),
        )

    projector.publish(
        event='match_started',
        header=record.header,
        views=seat_views(definition, record),
        facts=(),
    )
    return record


def _seat_records(seats) -> list[SeatRecord]:
    """Build the seat records, rejecting duplicates loudly.

    Records are ordered by ``index`` because the runtime, not the game state,
    owns seat ordering. A duplicate index and a duplicate ``participant_ref``
    are both programming errors: the first would put two participants on one
    seat id, and the second would leave one seat unreachable because
    ``seat_for`` returns only the first match, silently dropping the other.
    """
    records = []
    seen_indexes = set()
    seen_participants = set()
    for index, participant_ref, badge in seats:
        if index in seen_indexes:
            raise ValueError(f'duplicate seat index: {index!r}')
        if participant_ref in seen_participants:
            raise ValueError(
                f'duplicate participant_ref: {participant_ref!r}'
            )
        seen_indexes.add(index)
        seen_participants.add(participant_ref)
        records.append(
            SeatRecord(
                index=index,
                seat_id=seat_id(index),
                participant_ref=participant_ref,
                badge=badge,
            )
        )
    records.sort(key=lambda record: record.index)
    return records
