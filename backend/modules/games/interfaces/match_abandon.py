"""Interface-layer entry point that resolves a seat abandoned for good (S2).

The reconnect grace and, later, the lazy sweep both need to turn "this
session's seat will not reconnect" into the one runtime call that knows how to
resolve it. That translation -- from a room id and a session id to the match
ref and participant ref the use case takes, plus the production adapters --
lives here exactly once so the two triggers cannot drift.

This is a projection read: it uses plain ``Match``/``MatchSeat`` queries and
never the locking ``DjangoMatchStore.load``, which demands an open transaction.
The use case owns the authoritative read under its own unit of work.

The entry point is total. A room without an in-progress match, a session with
no participant, and a participant that occupies no seat all return ``None``
without reaching the use case. Reaching the use case with nothing to do would
still be harmless (it is idempotent), but the resolution is what lets a caller
distinguish "nothing to abandon" from "the seat was resolved".
"""

from ...rooms.models import Participant
from ..models import Match, MatchSeat
from ..runtime.application.abandon_seat import abandon_seat
from .composition import compose_match_dependencies


def abandon_seat_for_session(room_id, session_id):
    """Resolve the running match after ``session_id``'s seat is abandoned.

    Returns whatever the runtime use case returns, or ``None`` when there is
    nothing to abandon. The runtime adapters come from
    :func:`compose_match_dependencies`, the same composition root the match API
    uses, so the trigger never builds its own store, projector or registry.
    """
    match = Match.objects.filter(
        room_id=room_id, status=Match.Status.IN_PROGRESS
    ).first()
    if match is None:
        return None

    participant = Participant.objects.filter(
        room_id=room_id, session_id=session_id
    ).first()
    if participant is None:
        return None

    if not MatchSeat.objects.filter(
        match=match, participant=participant
    ).exists():
        return None

    dependencies = compose_match_dependencies()
    return abandon_seat(
        match_ref=str(match.public_id),
        participant_ref=str(participant.public_id),
        store=dependencies.store,
        registry=dependencies.registry,
        projector=dependencies.projector,
        lifecycle=dependencies.lifecycle,
    )
