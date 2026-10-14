"""Interface-layer publication of per-seat presence for a running match (S1).

While a match is in progress the remaining seats must learn that an opponent
is disconnected, and later that the opponent is not coming back. That notice
is emitted by the runtime, not by each game, so it works for every registered
game without the game knowing anything about presence (S1).

The presence travels in the match's own messages (S6). This module resolves
the room's in-progress match and each of its seats' participant presence, and
fans a single ``game.presence`` frame out to one group per seat plus the
public group, reusing the projector's group naming so a seat group can never
collide with the public group. A room with no in-progress match publishes
nothing and never fails: an ordinary lobby socket has no match to announce.

The presence value is derived with the same criterion the room snapshot
already applies: a ``reconnecting`` participant whose reconnect grace has
elapsed is reported as ``inactive`` (they did not come back in time). The
grace rule itself is imported rather than re-implemented, so the two readers
cannot drift on what "expired" means.

Each seat also carries ``remaining_seconds``: the whole seconds left before a
``reconnecting`` seat's grace window closes (S8). The server computes that
number so the match screen never has to derive it from the browser's clock,
which may be skewed (D6). ``None`` means the seat is not counting down, and a
``0`` means the window has already ended -- it does not promise that the seat
was expelled at that very instant, only that no reconnect time is left.
"""

from dataclasses import dataclass
from datetime import timedelta
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

from ...rooms.constants import RECONNECT_GRACE_SECONDS
from ...rooms.features.presence.domain.rules import grace_expired
from ...rooms.models import Participant
from ..models import Match, MatchSeat
from ..runtime.infrastructure.channel_projector import (
    match_public_group_name,
    match_seat_group_name,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SeatPresence:
    """The presence of one seat, keyed by the seat's stable ``index``.

    ``remaining_seconds`` is the server-computed reconnect countdown, present
    for every seat and ``None`` unless the seat is ``reconnecting`` inside its
    window (S8).
    """

    index: int
    presence: str
    remaining_seconds: int | None = None


@dataclass(frozen=True)
class MatchPresence:
    """The presence of every seat of an in-progress match."""

    match_ref: str
    seats: tuple[SeatPresence, ...]

    def payload(self):
        """Return the ``seats`` list as the client message carries it."""
        return [
            {
                'index': seat.index,
                'presence': seat.presence,
                'remaining_seconds': seat.remaining_seconds,
            }
            for seat in self.seats
        ]


def seat_presence(participant, now):
    """Return the presence of a seat's participant, with the grace applied.

    An expired ``reconnecting`` is reported as ``inactive``, exactly like
    ``rooms.infrastructure.snapshots`` reports it. An ``offline`` participant
    has no socket for its seat at all, so it is not present either; reporting
    it as ``inactive`` keeps the seat-facing presence inside the closed set
    S6 fixes (a seat is only ever ``online``, ``reconnecting`` or
    ``inactive``) instead of leaking a fourth value the client must tolerate.
    """
    presence = participant.presence
    if presence == Participant.Presence.RECONNECTING and grace_expired(
        participant.disconnected_at, now, RECONNECT_GRACE_SECONDS
    ):
        return Participant.Presence.INACTIVE
    if presence == Participant.Presence.OFFLINE:
        return Participant.Presence.INACTIVE
    return presence


def seat_remaining_seconds(participant, now):
    """Return the whole seconds left in a seat's reconnect window, or ``None``.

    Only a ``reconnecting`` participant still inside its window counts down;
    an ``online``, ``inactive`` or expired seat has no window left, and an
    inconsistent ``reconnecting`` row without ``disconnected_at`` has nothing
    to measure from (it is reported as-is, never a crash). The value floors
    with ``int`` and clamps at 0 so it is never negative and never promises
    more time than is left (S8, D6).
    """
    if participant.presence != Participant.Presence.RECONNECTING:
        return None
    if participant.disconnected_at is None:
        return None
    if grace_expired(
        participant.disconnected_at, now, RECONNECT_GRACE_SECONDS
    ):
        return None
    deadline = participant.disconnected_at + timedelta(
        seconds=RECONNECT_GRACE_SECONDS
    )
    return max(0, int((deadline - now).total_seconds()))


def resolve_match_presence(room_id):
    """Return the seat presence of ``room_id``'s running match, or ``None``.

    Total: a room without an in-progress match resolves to ``None`` and never
    raises, like the socket-side seat resolver.
    """
    match = Match.objects.filter(
        room_id=room_id, status=Match.Status.IN_PROGRESS
    ).first()
    if match is None:
        return None

    now = timezone.now()
    seats = (
        MatchSeat.objects.filter(match=match)
        .select_related('participant')
        .order_by('index')
    )
    return MatchPresence(
        match_ref=str(match.public_id),
        seats=tuple(
            SeatPresence(
                index=seat.index,
                presence=seat_presence(seat.participant, now),
                remaining_seconds=seat_remaining_seconds(seat.participant, now),
            )
            for seat in seats
        ),
    )


def publish_match_presence(room_id, channel_layer=None):
    """Publish the running match's seat presence and return what was published.

    One ``game.presence`` message is sent to each seat's group and to the
    public group. A room with no in-progress match sends nothing and returns
    ``None``. The caller owns transport failures overall: a layer error is
    logged here and the remaining targets are still sent, so one unreachable
    group cannot silence every other seat of the match -- the same per-send
    isolation the match projector applies (and for the same reason). Only the
    resolution itself can raise, and the socket path logs that and continues
    without aborting the presence transition that triggered the publish.
    """
    presence = resolve_match_presence(room_id)
    if presence is None:
        return None

    layer = (
        channel_layer if channel_layer is not None else get_channel_layer()
    )
    if layer is None:
        return presence

    message = {
        'type': 'game.presence',
        'match_ref': presence.match_ref,
        'seats': presence.payload(),
    }
    send = async_to_sync(layer.group_send)
    for seat in presence.seats:
        group = match_seat_group_name(presence.match_ref, seat.index)
        try:
            send(group, message)
        except Exception:
            logger.exception(
                'Unable to publish seat %s presence to channel group %s.',
                seat.index,
                group,
            )
    public_group = match_public_group_name(presence.match_ref)
    try:
        send(public_group, message)
    except Exception:
        logger.exception(
            'Unable to publish match %s presence to channel group %s.',
            presence.match_ref,
            public_group,
        )
    return presence
