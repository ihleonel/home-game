from contextlib import contextmanager

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ....infrastructure.events import room_snapshot, schedule_room_event
from ....models import Participant, Room
from .....games.models import Match
from ..domain.entities import ReapableParticipant
from ..domain.rules import GRACE


class DjangoRoomReapingGateway:
    @contextmanager
    def atomic(self):
        with transaction.atomic():
            yield self

    def now(self):
        return timezone.now()

    def active_room_ids(self, *, room_id=None):
        rooms = Room.objects.filter(status=Room.Status.ACTIVE)
        if room_id is not None:
            rooms = rooms.filter(pk=room_id)
        return tuple(rooms.order_by('pk').values_list('pk', flat=True))

    def room_ids_with_in_progress_match(self, room_ids):
        return set(
            Match.objects.filter(
                room_id__in=room_ids,
                status=Match.Status.IN_PROGRESS,
            ).values_list('room_id', flat=True)
        )

    def reapable_participants_for_update(self, room_ids, *, policy, cutoff):
        # The cutoff comparisons live in SQL on purpose: this query decides who
        # gets removed, so a participant inside the grace window must never
        # leave the database. The two grace branches mirror ``is_stale``
        # exactly; under ``STARTUP`` there is no presence predicate at all,
        # because every non-left row is a ghost at boot.
        participants = (
            Participant.objects.select_for_update()
            .filter(
                room_id__in=room_ids,
                left_at__isnull=True,
            )
            .order_by('pk')
        )
        if policy == GRACE:
            participants = participants.filter(
                Q(
                    presence__in=(
                        Participant.Presence.RECONNECTING,
                        Participant.Presence.INACTIVE,
                    ),
                    disconnected_at__isnull=False,
                    disconnected_at__lte=cutoff,
                )
                | Q(
                    presence=Participant.Presence.OFFLINE,
                    updated_at__isnull=False,
                    updated_at__lte=cutoff,
                )
            )
        return tuple(
            ReapableParticipant(
                id=participant.pk,
                room_id=participant.room_id,
                # session_id is an opaque pass-through: it feeds the
                # departed_session_id of the player_left event, so the real
                # value must not be stringified here.
                session_id=participant.session_id,
                presence=participant.presence,
                disconnected_at=participant.disconnected_at,
                updated_at=participant.updated_at,
            )
            for participant in participants
        )

    def save_reaped_changes(self, participant_id, changes):
        participant = Participant.objects.select_for_update().get(pk=participant_id)
        for field, value in changes.items():
            setattr(participant, field, value)
        participant.save(update_fields=(*changes, 'updated_at'))

    def room_snapshot(self, room_id):
        return room_snapshot(Room.objects.get(pk=room_id))

    def has_active_participants(self, room_id):
        return Participant.objects.filter(
            room_id=room_id,
            left_at__isnull=True,
        ).exists()

    def delete_room(self, room_id):
        Room.objects.filter(pk=room_id).delete()

    def schedule_room_event(
        self,
        room_id,
        event_name,
        snapshot,
        *,
        departed_session_id=None,
        vote=None,
    ):
        schedule_room_event(
            room_id,
            event_name,
            snapshot,
            departed_session_id=departed_session_id,
            vote=vote,
        )
