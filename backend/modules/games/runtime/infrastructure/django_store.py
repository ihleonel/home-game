"""Django-backed ``MatchStore`` adapter for the match runtime.

``unit_of_work`` wraps ``transaction.atomic()``: atomicity and serialization
are the adapter's job, not the use case's. Every read-validate-write sequence
must run inside it, and ``load`` always issues ``SELECT ... FOR UPDATE`` so
the match row is locked for the rest of the transaction. That row lock is
what makes two simultaneous actors on the same match serialize instead of
both reading version N and one action being silently lost.

``load`` must therefore be called inside ``unit_of_work()``. Django requires
an active transaction for a locking read and raises
``TransactionManagementError`` in autocommit mode, so calling it outside the
unit of work fails loudly rather than silently reading the row unlocked.

``save`` is a compare-and-swap keyed on the previous version (``record.version
- 1``) rather than a blind write, and raises ``StaleVersion`` instead of
overwriting a row whose version has moved on. ``append_action`` only inserts:
the ``MatchAction`` log is append-only.
"""

import uuid
from contextlib import contextmanager

from django.db import transaction
from django.utils import timezone

from ....rooms.models import Participant
from ...models import Match, MatchAction, MatchSeat
from ..application.ports import MatchRecord, SeatRecord
from ..domain.errors import StaleVersion


class DjangoMatchStore:
    """``MatchStore`` port implemented over ``Match``/``MatchSeat``/``MatchAction``."""

    @contextmanager
    def unit_of_work(self):
        with transaction.atomic():
            yield self

    def load(self, match_ref):
        """Return the locked record for ``match_ref``, or ``None``.

        Runs a ``SELECT ... FOR UPDATE`` on the match row, so it must be called
        inside :meth:`unit_of_work`; outside a transaction Django raises
        ``TransactionManagementError`` instead of reading the row unlocked. A
        malformed reference and an unknown (but well-formed) reference both
        return ``None`` rather than raising.
        """
        try:
            public_id = uuid.UUID(str(match_ref))
        except (ValueError, TypeError, AttributeError):
            return None
        match = (
            Match.objects.select_for_update().filter(public_id=public_id).first()
        )
        if match is None:
            return None
        return self._reconstruct(match)

    def create(self, *, room_id, game_id, state, seats):
        match = Match.objects.create(
            room_id=room_id,
            game_id=game_id,
            state=state,
        )
        participants = {
            str(participant.public_id): participant
            for participant in Participant.objects.filter(
                room_id=room_id,
                public_id__in=[str(seat.participant_ref) for seat in seats],
            )
        }
        MatchSeat.objects.bulk_create(
            MatchSeat(
                match=match,
                index=seat.index,
                seat_id=seat.seat_id,
                participant=participants[str(seat.participant_ref)],
                badge=seat.badge,
            )
            for seat in seats
        )
        ordered_seats = tuple(
            SeatRecord(
                index=seat.index,
                seat_id=seat.seat_id,
                participant_ref=str(seat.participant_ref),
                badge=seat.badge,
            )
            for seat in sorted(seats, key=lambda seat: seat.index)
        )
        return MatchRecord(
            match_ref=str(match.public_id),
            room_id=match.room_id,
            game_id=match.game_id,
            version=0,
            state=state,
            status='in_progress',
            winner_seat=None,
            seats=ordered_seats,
        )

    def save(self, record):
        """Compare-and-swap ``record`` into the row it was read from.

        The update is filtered on ``public_id`` **and** the previous version,
        so a row that has moved on matches nothing and raises
        ``StaleVersion`` instead of overwriting the newer snapshot.
        """
        previous_version = record.version - 1
        finished_at = timezone.now() if record.status == 'finished' else None
        updated = Match.objects.filter(
            public_id=record.match_ref,
            version=previous_version,
        ).update(
            version=record.version,
            state=record.state,
            status=record.status,
            winner_seat=record.winner_seat or '',
            finished_at=finished_at,
        )
        if updated != 1:
            actual_version = (
                Match.objects.filter(public_id=record.match_ref)
                .values_list('version', flat=True)
                .first()
            )
            raise StaleVersion(record.match_ref, previous_version, actual_version)

    def append_action(self, *, record, seat_id, action, facts):
        """Insert the immutable audit row for ``record``'s transition."""
        match_id = (
            Match.objects.filter(public_id=record.match_ref)
            .values_list('id', flat=True)
            .get()
        )
        MatchAction.objects.create(
            match_id=match_id,
            sequence=record.version,
            seat_id=seat_id,
            action_name=action.name,
            action_value=action.value or '',
            version=record.version,
            facts=[dict(fact) for fact in facts],
        )

    def _reconstruct(self, match):
        """Build a ``MatchRecord``, ordering seats by their explicit index."""
        seats = tuple(
            SeatRecord(
                index=seat.index,
                seat_id=seat.seat_id,
                participant_ref=str(seat.participant.public_id),
                badge=seat.badge,
            )
            for seat in match.seats.select_related('participant').order_by('index')
        )
        return MatchRecord(
            match_ref=str(match.public_id),
            room_id=match.room_id,
            game_id=match.game_id,
            version=match.version,
            state=match.state,
            status=match.status,
            winner_seat=match.winner_seat or None,
            seats=seats,
        )
