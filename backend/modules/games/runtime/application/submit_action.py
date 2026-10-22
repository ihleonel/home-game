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
    lifecycle,
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

    When the action finishes the match, ``lifecycle.on_match_finished`` runs
    inside that same unit of work, after the save and the audit row: the finish
    and the room-level reset are one atomic outcome, and a reset failure aborts
    the action instead of leaving a half-finished match. ``lifecycle`` is a
    required part of finishing a match, not an optional extra: with no default,
    a caller that forgets it fails loudly at the call site instead of silently
    skipping the reset and leaving the post-match lobby a dead end. That
    requirement is still not enough on its own, because ``None`` is a value a
    caller can pass explicitly: the body rejects it up front with the same
    ``TypeError`` a missing argument raises, so neither mistake can quietly
    skip the reset.
    """
    if lifecycle is None:
        # ``lifecycle`` is required, but a required parameter only stops a
        # caller from *omitting* it -- ``None`` is still a value they can pass,
        # and treating it as "no hook" would silently skip the post-match
        # readiness reset. Fail loudly, before any lookup or gate, for every
        # action, with the same ``TypeError`` a missing argument produces.
        raise TypeError(
            "submit_action() 'lifecycle' must be provided; passing None would "
            "silently skip the post-match readiness reset"
        )

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
        elif spec.freeform:
            # The engine is the authority of a composed value (S3): any
            # non-empty string is accepted here and graded by ``apply``.
            if not isinstance(action_value, str) or not action_value:
                raise IllegalAction(action_name, seat.seat_id)
        elif action_value is not None:
            raise IllegalAction(action_name, seat.seat_id)

        action = Action(name=action_name, value=action_value)
        try:
            transition = definition.apply(record.state, seat.seat_id, action, rng)
        except ValueError:
            if not spec.freeform:
                # A value from an enumerated or valueless spec is composed by
                # the server, so a rejection there is a programming error and
                # must stay loud instead of being masked as a client mistake.
                raise
            # A freeform value is composed by the client, so the engine saying
            # no is a client error, not a broken rule.
            raise IllegalAction(action_name, seat.seat_id) from None
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

        if status == 'finished':
            lifecycle.on_match_finished(
                match_ref=next_record.match_ref,
                room_id=next_record.room_id,
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
