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

The reconnect grace timer lives in the process, so a restart in the middle of
the window loses the trigger and the match would hang again. The lazy sweep
(:func:`abandon_expired_seats`) is the second trigger: the read paths that
already reap ask for every already-expired seat before reaping, and it reuses
:func:`abandon_seat_for_session` so there is still one translation and one
runtime call, never a second resolution path.
"""

from dataclasses import dataclass

from django.utils import timezone

from ...rooms.constants import RECONNECT_GRACE_SECONDS
from ...rooms.features.presence.domain.rules import grace_expired
from ...rooms.features.reaping.domain.rules import staleness_cutoff
from ...rooms.models import Participant
from ..models import Match, MatchSeat
from ..runtime.application.abandon_seat import abandon_seat
from .composition import compose_match_dependencies


@dataclass(frozen=True)
class AbandonSweepOutcome:
    """What one lazy sweep did, small enough for a caller to log or assert."""

    seats_resolved: int


def _seat_is_expired(participant, now):
    """Return whether ``participant``'s seat will never reconnect (S2).

    Membership already removed (``left_at``), an explicit ``inactive``, a
    ``reconnecting`` whose grace elapsed, and an ``offline`` row quiet for longer
    than that same grace are all expired. An ``offline`` row never held a socket
    -- an arrival posted over REST whose socket never opened -- so it has no
    ``disconnected_at`` to measure and its window is its last write, exactly the
    rule the membership reaper already applies to those rows. That is what keeps
    such a seat from becoming an exit with no door: it cannot leave while it is
    ready, the reaper skips a busy room and the vote never targets it, so the
    match would otherwise wait forever for somebody who is not there. The grace
    and its cutoff are imported from the rooms rules rather than re-implemented,
    so this reader, the reaper and the presence projection cannot drift.
    """
    if participant.left_at is not None:
        return True
    if participant.presence == Participant.Presence.INACTIVE:
        return True
    if participant.presence == Participant.Presence.RECONNECTING:
        return grace_expired(
            participant.disconnected_at, now, RECONNECT_GRACE_SECONDS
        )
    if participant.presence == Participant.Presence.OFFLINE:
        return (
            participant.updated_at is not None
            and participant.updated_at
            <= staleness_cutoff(now, RECONNECT_GRACE_SECONDS)
        )
    return False


def abandon_expired_seats(room_id=None):
    """Resolve every already-expired seat of a running match (S2, S7).

    Total and deterministic. Every room with an in-progress match is walked in
    ``room_id`` order and each match's seats in ``index`` order, so the same
    rows always resolve in the same sequence; a ``room_id`` restricts the walk
    to one room. A room with no in-progress match, a match with no expired
    seat, and a second call after everything is resolved all return a
    zero-count summary instead of failing.

    The unit of work stays the use case's: this sweep opens no transaction and
    holds no lock. It reads which seats are expired and then makes one
    idempotent :func:`abandon_seat_for_session` call per seat, so a repeated
    trigger is harmless. Callers that also reap must run this first, because
    finishing the match is what unblocks the room for the reap of the very
    same read.
    """
    matches = Match.objects.filter(status=Match.Status.IN_PROGRESS)
    if room_id is not None:
        matches = matches.filter(room_id=room_id)
    matches = matches.order_by('room_id', 'public_id')

    now = timezone.now()
    seats_resolved = 0
    for match in matches:
        seats = (
            MatchSeat.objects.filter(match=match)
            .select_related('participant')
            .order_by('index')
        )
        for seat in seats:
            if not _seat_is_expired(seat.participant, now):
                continue
            resolved = abandon_seat_for_session(
                match.room_id, seat.participant.session_id
            )
            # ``None`` means the seat no longer had anything to resolve -- the
            # use case already ran for it, or finishing an earlier seat kept
            # this one from being a running match any more.
            if resolved is not None:
                seats_resolved += 1
    return AbandonSweepOutcome(seats_resolved=seats_resolved)


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
