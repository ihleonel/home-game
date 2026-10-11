from django.db import transaction

from ....events import room_snapshot, schedule_room_event
from ....models import Participant, Room
from ..domain.errors import ActiveParticipantNotFound, ActiveRoomNotFound
from ..domain.rules import readiness_change


class DjangoReadinessGateway:
    def set_ready(self, data):
        with transaction.atomic():
            room = Room.objects.select_for_update().filter(
                status=Room.Status.ACTIVE
            ).first()
            if room is None:
                raise ActiveRoomNotFound()
            participant = Participant.objects.select_for_update().filter(
                room=room,
                session_id=data['session_id'],
                left_at__isnull=True,
            ).first()
            if participant is None:
                raise ActiveParticipantNotFound()

            change = readiness_change(participant.is_ready, data['is_ready'])
            participant.is_ready = (
                change.value if change.changed else participant.is_ready
            )
            # Preserve the established write and timestamp behavior even for no-op PATCHes.
            participant.save(update_fields=('is_ready', 'updated_at'))
            response = {'room': room_snapshot(room)}
            schedule_room_event(room.pk, 'ready_changed', room_snapshot(room))
        return response
