"""Interface-layer sequence that opens a match for an already-resolved room.

Both the REST view and the in-process lobby countdown open a match from the
same room state: reap the room's ghost memberships, reject a room that already
has an in-progress match, read the room's ready seats under one transaction,
and only then call the framework-free ``start_match`` use case so the runtime's
own transaction is never nested. That sequence lives here exactly once so the
two callers cannot drift.

The caller resolves *which* room is being opened and owns its own transport
concerns (HTTP status codes, channel messages); this module only needs a
``Room`` instance and the runtime adapters. It deliberately has no DRF import
so the async consumer can call it without the REST stack.
"""

from dataclasses import dataclass

from django.db import IntegrityError, transaction

from ...rooms.models import Participant
from ..models import Match
from ..runtime.application.ports import MatchRecord
from ..runtime.application.start_match import start_match


class MatchAlreadyInProgress(Exception):
    """The room already has an in-progress match.

    The rejection belongs to the opening sequence, not to the runtime's
    ``start_match``: the runtime is never even reached while an in-progress
    match exists, so this is not a ``runtime.domain.errors.MatchError``. Each
    adapter translates it into its own transport response.
    """


@dataclass(frozen=True)
class OpenedMatch:
    """A freshly opened match and the room participants that supplied its seats.

    ``participants`` is the post-reap ready set the seats were built from,
    returned as-is so a caller can resolve the requester's own seat and the
    display-name map without re-running the seat query outside the
    transaction.
    """

    record: MatchRecord
    participants: tuple


def open_match_for_room(*, room, reaping, store, registry, projector):
    """Open a match in ``room`` from its ready participants.

    The room is reaped before the seats are resolved, inside the same atomic
    block as the seat read, so a ready participant who disconnected past the
    grace window cannot occupy a seat. The runtime's own transaction starts
    only after this block closes, so it is never nested here.

    Raises :class:`MatchAlreadyInProgress` when the room already has an
    in-progress match, including when two concurrent starts slip past the
    check and ``one_active_match_per_room`` rejects the later one. The
    runtime's own rejections (``UnknownGame``, ``WrongSeatCount``) propagate
    unchanged for the caller to translate.
    """
    with transaction.atomic():
        # Reap first: the seat query below must read post-reap state, so a
        # ghost-ready membership is gone before seats are enumerated.
        reaping.reap(room_id=room.id)

        if Match.objects.filter(
            room_id=room.id, status=Match.Status.IN_PROGRESS
        ).exists():
            raise MatchAlreadyInProgress()

        # The seats are the room's own active participants that are ready,
        # ordered by join time. Nothing is taken from the request body, so an
        # unvalidated participant reference can never reach
        # ``DjangoMatchStore.create``.
        participants = list(
            Participant.objects.filter(
                room_id=room.id, left_at__isnull=True, is_ready=True
            ).order_by('joined_at', 'pk')
        )
        seats = [
            (index, str(participant.public_id), participant.game_marker)
            for index, participant in enumerate(participants)
        ]

    try:
        record = start_match(
            room_id=room.id,
            game_id=room.game_id,
            seats=seats,
            store=store,
            registry=registry,
            projector=projector,
        )
    except IntegrityError:
        # ``one_active_match_per_room`` is the only integrity error the check
        # above cannot fully rule out: two concurrent starts can both pass it
        # before either commits. Map the constraint to the same clean case.
        raise MatchAlreadyInProgress() from None

    return OpenedMatch(record=record, participants=tuple(participants))
