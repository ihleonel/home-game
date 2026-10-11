from contextlib import contextmanager

from django.db import transaction
from django.utils import timezone

from ....infrastructure.events import room_snapshot
from ....models import Participant, Room
from ..domain.entities import PresenceParticipant


class DjangoPresenceGateway:
    def active_membership(self, session_id):
        participant = Participant.objects.select_related('room').filter(
            session_id=session_id,
            room__status=Room.Status.ACTIVE,
            left_at__isnull=True,
        ).first()
        if participant is None:
            return None
        return participant.room_id, str(participant.session_id)

    @contextmanager
    def atomic(self):
        with transaction.atomic():
            yield self

    def lock_active_room(self, room_id):
        return Room.objects.select_for_update().filter(
            pk=room_id,
            status=Room.Status.ACTIVE,
        ).first() is not None

    def active_participant_for_update(self, room_id, session_id):
        participant = Participant.objects.select_for_update().filter(
            room_id=room_id,
            session_id=session_id,
            left_at__isnull=True,
        ).first()
        return self._participant_state(participant) if participant else None

    def reconnecting_participant_for_update(
        self, room_id, session_id, disconnected_at
    ):
        participant = Participant.objects.select_for_update().filter(
            room_id=room_id,
            session_id=session_id,
            left_at__isnull=True,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=disconnected_at,
        ).first()
        return self._participant_state(participant) if participant else None

    def save_presence_changes(self, participant_id, changes):
        participant = Participant.objects.select_for_update().get(pk=participant_id)
        for field, value in changes.items():
            setattr(participant, field, value)
        participant.save(update_fields=(*changes, 'updated_at'))

    def room_snapshot(self, room_id):
        return room_snapshot(Room.objects.get(pk=room_id))

    def now(self):
        return timezone.now()

    @staticmethod
    def _participant_state(participant):
        return PresenceParticipant(
            id=participant.pk,
            session_id=participant.session_id,
            presence=participant.presence,
            disconnected_at=participant.disconnected_at,
        )
