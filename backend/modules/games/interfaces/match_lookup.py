"""Interface-layer resolver of a socket's single match subscription (FRG-05C).

This is a **projection read**. It uses plain ``Match.objects`` and
``MatchSeat.objects`` queries and deliberately never the locking
``DjangoMatchStore.load``. ``load`` issues ``SELECT ... FOR UPDATE`` and
therefore demands an open transaction: it is the authoritative read at the
head of a read-validate-write sequence. Subscribing a socket to a match is not
such a sequence, so taking a row lock here would be unnecessary, and calling
``load`` outside a transaction would raise ``TransactionManagementError`` for a
read that needs no transaction at all.

The resolver is total: a request that simply has no in-progress match returns
``None`` and never raises. A participant that occupies a seat resolves to its
own seat group and its own seat view; a participant with no seat in an
in-progress match is a spectator and resolves to the public group and the
public view. Any other missing link in the chain -- no match, no participant,
unknown game -- also resolves to ``None`` rather than raising.
"""

from dataclasses import dataclass
from typing import Mapping

from django.core.exceptions import ValidationError

from ...rooms.models import Participant
from ..composition import GAME_REGISTRY
from ..models import Match, MatchSeat
from ..runtime.infrastructure.channel_projector import (
    match_public_group_name,
    match_seat_group_name,
)


@dataclass(frozen=True)
class SeatSubscription:
    """The single match group a socket may join and the view it may see.

    ``seat_index`` is the seat the socket occupies, or ``None`` for a
    spectator. ``group`` is exactly one group -- the seat's own group when
    seated, the public group when a spectator -- never both.
    """

    match_ref: str
    seat_index: int | None
    group: str
    view: Mapping


def resolve_seat_subscription(room_id, session_id, match_ref=None):
    """Return the subscription of ``session_id``, or ``None``.

    With ``match_ref`` given, only that match is considered, and only while it
    is still in progress and belongs to ``room_id``. Without it, the room's
    own in-progress match is used. A participant that occupies a seat gets
    that seat's group and view; a participant with no seat is a spectator of
    the public group and view. A room with no in-progress match, a session
    with no participant, and an unknown game all resolve to ``None``.
    """
    match = _find_in_progress_match(room_id, match_ref)
    if match is None:
        return None

    participant = Participant.objects.filter(
        room_id=room_id, session_id=session_id
    ).first()
    if participant is None:
        return None

    seat = MatchSeat.objects.filter(match=match, participant=participant).first()

    definition = GAME_REGISTRY.get(match.game_id)
    if definition is None:
        return None

    match_ref_value = str(match.public_id)
    if seat is None:
        return SeatSubscription(
            match_ref=match_ref_value,
            seat_index=None,
            group=match_public_group_name(match_ref_value),
            view=definition.view(match.state, None),
        )

    return SeatSubscription(
        match_ref=match_ref_value,
        seat_index=seat.index,
        group=match_seat_group_name(match_ref_value, seat.index),
        view=definition.view(match.state, seat.seat_id),
    )


def _find_in_progress_match(room_id, match_ref):
    """Return the in-progress match of the room, or ``None``.

    A malformed ``match_ref`` is a reference to no match at all, so the UUID
    validation error becomes ``None`` instead of escaping the resolver.
    """
    try:
        matches = Match.objects.filter(
            room_id=room_id, status=Match.Status.IN_PROGRESS
        )
        if match_ref is not None:
            matches = matches.filter(public_id=match_ref)
        return matches.first()
    except (ValidationError, ValueError, TypeError):
        return None
