from contextlib import contextmanager

from django.db import transaction

from ....infrastructure.events import room_snapshot, schedule_room_event
from ....models import Participant, Room
from ..domain.entities import ReadinessParticipant


class DjangoReadinessGateway:
    @contextmanager
    def atomic(self):
        with transaction.atomic():
            yield self

    def active_room_for_update(self):
        room = Room.objects.select_for_update().filter(
            status=Room.Status.ACTIVE
        ).first()
        return room.pk if room else None

    def active_participant_for_session_for_update(self, room_id, session_id):
        participant = Participant.objects.select_for_update().filter(
            room_id=room_id,
            session_id=session_id,
            left_at__isnull=True,
        ).first()
        if participant is None:
            return None
        return ReadinessParticipant(id=participant.pk, is_ready=participant.is_ready)

    def save_readiness(self, participant_id, is_ready):
        participant = Participant.objects.select_for_update().get(pk=participant_id)
        participant.is_ready = is_ready
        participant.save(update_fields=('is_ready', 'updated_at'))

    def room_snapshot(self, room_id):
        return room_snapshot(Room.objects.get(pk=room_id))

    def schedule_room_event(self, room_id, event_name, snapshot):
        schedule_room_event(room_id, event_name, snapshot)
