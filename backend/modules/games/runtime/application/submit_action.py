"""``submit_action`` use case: validate and apply one action of a match."""

from dataclasses import replace

from ...contracts import Action
from ..domain.errors import (
    IllegalAction,
    MatchNotFound,
    MatchNotPlayable,
    NotASeat,
    NotYourTurn,
    StaleVersion,
    UnknownGame,
)
from .views import seat_views
from .ports import MatchRecord


def submit_action(
    *,
    match_ref,
    participant_ref,
    action_name,
    action_value,
    expected_version,
    store,
    registry,
    projector,
    rng=None,
) -> MatchRecord:
    """Validate and apply one action, then publish the resulting views.

    Rejections are ordered deliberately: the version is checked before the
    action legality, so a client that composed its action against a different
    state is told to re-sync (``StaleVersion``) rather than told its action is
    illegal.

    The load, every gate, ``apply`` and both writes run inside one
    ``store.unit_of_work()``. The read must be inside the transaction the
    adapter serializes on the match row; otherwise two simultaneous actors
    both read version N, both pass the gate and one action is silently lost.
    A rejection rolls back an otherwise empty transaction, which is harmless.
    """
    with store.unit_of_work():
        record = store.load(match_ref)
        if record is None:
            raise MatchNotFound(match_ref)

        definition = registry.get(record.game_id)
        if definition is None:
            raise UnknownGame(record.game_id)

        if record.status != 'in_progress':
            raise MatchNotPlayable(match_ref, record.status)

        seat = record.seat_for(participant_ref)
        if seat is None:
            raise NotASeat(match_ref, participant_ref)

        if expected_version != record.version:
            raise StaleVersion(match_ref, expected_version, record.version)

        if seat.seat_id not in definition.active_seats(record.state):
            raise NotYourTurn(seat.seat_id)

        spec = _spec_for(definition, record.state, seat.seat_id, action_name)
        if spec.options:
            if action_value not in spec.options:
                raise IllegalAction(action_name, seat.seat_id)
        elif action_value is not None:
            raise IllegalAction(action_name, seat.seat_id)

        action = Action(name=action_name, value=action_value)
        transition = definition.apply(record.state, seat.seat_id, action, rng)
        facts = tuple(
            {'name': fact.name, 'seat': fact.seat, 'detail': dict(fact.detail)}
            for fact in transition.facts
        )

        if definition.is_finished(transition.state):
            outcome = definition.outcome(transition.state)
            status = 'finished'
            winner_seat = outcome.winner_seat if outcome is not None else None
            event = 'match_finished'
        else:
            status = 'in_progress'
            winner_seat = None
            event = 'match_updated'

        next_record = replace(
            record,
            version=record.version + 1,
            state=transition.state,
            status=status,
            winner_seat=winner_seat,
        )

        store.save(next_record)
        store.append_action(
            record=next_record,
            seat_id=seat.seat_id,
            action=action,
            facts=facts,
        )

    projector.publish(
        event=event,
        header=next_record.header,
        views=seat_views(definition, next_record),
        facts=facts,
    )
    return next_record


def _spec_for(definition, state, seat_id, action_name):
    """Return the offered action spec named ``action_name`` or reject it."""
    for spec in definition.legal_actions(state, seat_id):
        if spec.name == action_name:
            return spec
    raise IllegalAction(action_name, seat_id)
