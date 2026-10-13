"""``abandon_seat`` use case: resolve a match after a seat is expelled.

The trigger lives outside this layer (the room's reconnect grace and the read
paths that reap): by the time this use case runs, a seat of a running match has
already been expelled for not reconnecting. What that expulsion does to the
match is the game's own decision (S3, S4); the runtime only delegates to the
definition's ``abandon`` operation and reports whatever it returns.
"""

from dataclasses import replace

from ...contracts import Action
from ..domain.errors import UnknownGame
from .views import seat_views
from .ports import MatchRecord


def abandon_seat(
    *,
    match_ref,
    participant_ref,
    store,
    registry,
    projector,
    lifecycle,
    rng=None,
) -> MatchRecord | None:
    """Resolve ``match_ref`` after ``participant_ref``'s seat is expelled.

    The whole read-validate-write sequence runs inside one
    ``store.unit_of_work()`` and the read is the serialized ``store.load``: the
    expulsion, the game's resolution, the version bump and the audit row are
    one atomic outcome (S5), and two simultaneous triggers cannot both resolve
    the same stale state.

    Idempotent by contract. The trigger may arrive through more than one path
    and may repeat, so a trigger that has nothing left to do returns ``None``
    and leaves the store untouched instead of raising: when the match does not
    exist, when it is not ``in_progress`` (already resolved), or when the
    participant occupies no seat (a spectator). A repeat or a race between two
    triggers is therefore a harmless no-op, never an error. Only a registered
    game that is missing for a live match is a real failure and raises
    ``UnknownGame``, exactly as ``submit_action`` does.

    Resolution is delegated, never imposed: the definition's ``abandon``
    produces the new state and the runtime then reads ``is_finished`` and
    ``outcome`` off it. A definition may end the match (``status='finished'``,
    ``winner_seat`` from the outcome, event ``'match_finished'``) or keep it
    running with the remaining seats (``status='in_progress'``,
    ``winner_seat=None``, event ``'seat_abandoned'``). The runtime does not
    reassign turns or seats on its own (D3).

    ``lifecycle`` is a required part of finishing a match, not an optional
    extra: finishing resets the room's readiness so the post-match lobby is
    usable again, and it runs inside the same unit of work that saves the
    finished match so the finish and the reset are one atomic outcome (S7).
    The body rejects an explicit ``None`` up front, before any lookup or gate,
    with the same ``TypeError`` a missing argument raises, so a caller can
    neither omit the hook nor opt out by passing ``None``.
    """
    if lifecycle is None:
        # ``lifecycle`` is required, but a required parameter only stops a
        # caller from *omitting* it -- ``None`` is still a value they can pass,
        # and treating it as "no hook" would silently skip the post-match
        # readiness reset. Fail loudly, before any lookup, for every trigger,
        # with the same ``TypeError`` a missing argument produces.
        raise TypeError(
            "abandon_seat() 'lifecycle' must be provided; passing None would "
            "silently skip the post-match readiness reset"
        )

    with store.unit_of_work():
        record = store.load(match_ref)
        if record is None:
            return None

        definition = registry.get(record.game_id)
        if definition is None:
            raise UnknownGame(record.game_id)

        if record.status != 'in_progress':
            return None

        seat = record.seat_for(participant_ref)
        if seat is None:
            return None

        transition = definition.abandon(record.state, seat.seat_id, rng)
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
            event = 'seat_abandoned'

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
            action=Action(name='abandon', value=None),
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
