from contextlib import contextmanager

from django.db import transaction
from django.utils import timezone

from ....infrastructure.events import room_snapshot, schedule_room_event
from ....models import Participant, Room
from ...membership.domain.entities import ActiveRoom, ParticipantMembership


class DjangoRoomMembershipGateway:
    @contextmanager
    def atomic(self):
        with transaction.atomic():
            yield self

    def get_active_room_snapshot(self):
        room = Room.objects.filter(status=Room.Status.ACTIVE).first()
        return room_snapshot(room) if room is not None else None

    def active_room_for_update(self):
        room = Room.objects.select_for_update().filter(
            status=Room.Status.ACTIVE
        ).first()
        return self._room_state(room) if room is not None else None

    def create_or_lock_active_room(self, game_id):
        room = Room.objects.select_for_update().filter(
            status=Room.Status.ACTIVE
        ).first()
        created = False
        if room is None:
            room, created = Room.objects.get_or_create(
                status=Room.Status.ACTIVE,
                defaults={'game_id': game_id},
            )
            room = Room.objects.select_for_update().get(pk=room.pk)
        return self._room_state(room), created

    def participant_for_session_for_update(self, room_id, session_id):
        participant = Participant.objects.select_for_update().filter(
            room_id=room_id,
            session_id=session_id,
        ).first()
        return self._participant_state(participant) if participant else None

    def active_participant_for_session_for_update(self, room_id, session_id):
        participant = Participant.objects.select_for_update().filter(
            room_id=room_id,
            session_id=session_id,
            left_at__isnull=True,
        ).first()
        return self._participant_state(participant) if participant else None

    def create_participant(self, room_id, display_name, game_marker):
        participant = Participant.objects.create(
            room_id=room_id,
            display_name=display_name,
            game_marker=game_marker,
        )
        return self._participant_state(participant)

    def save_membership_changes(self, participant_id, changes):
        participant = Participant.objects.select_for_update().get(pk=participant_id)
        for field, value in changes.items():
            setattr(participant, field, value)
        participant.save(update_fields=(*changes, 'updated_at'))
        return self._participant_state(participant)

    def room_snapshot(self, room_id):
        room = Room.objects.get(pk=room_id)
        return room_snapshot(room)

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

    def now(self):
        return timezone.now()

    @staticmethod
    def _room_state(room):
        return ActiveRoom(id=room.pk, game_id=room.game_id)

    @staticmethod
    def _participant_state(participant):
        return ParticipantMembership(
            id=participant.pk,
            session_id=participant.session_id,
            public_id=participant.public_id,
            display_name=participant.display_name,
            game_marker=participant.game_marker,
            presence=participant.presence,
            was_left=participant.left_at is not None,
        )
