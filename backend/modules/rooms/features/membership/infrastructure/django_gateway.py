from django.db import transaction
from django.utils import timezone

from ....events import room_snapshot, schedule_room_event
from ....models import ExpulsionVote, Participant, Room
from ....voting import cancel_pending_vote_for_target, cancel_pending_vote_for_participant
from ..domain.errors import (
    ActiveRoomGameConflict,
    MissingParticipantIdentity,
    RemovedSession,
)
from ..domain.rules import membership_change


class DjangoRoomMembershipGateway:
    def get_active_room(self):
        return Room.objects.filter(status=Room.Status.ACTIVE).first()

    def create_or_discover(self, data):
        with transaction.atomic():
            room = Room.objects.select_for_update().filter(
                status=Room.Status.ACTIVE
            ).first()
            created = False
            if room is None:
                room, created = Room.objects.get_or_create(
                    status=Room.Status.ACTIVE,
                    defaults={'game_id': data['game_id']},
                )
                room = Room.objects.select_for_update().get(pk=room.pk)

            if room.game_id != data['game_id']:
                raise ActiveRoomGameConflict()

            participant, event_name = self._membership_for(room, data)
            cancelled_vote = cancel_pending_vote_for_target(
                room, participant, 'target_reconnected'
            )
            response = (self._membership_response(room, participant), created)
            if event_name is not None:
                schedule_room_event(room.pk, event_name, room_snapshot(room))
            if cancelled_vote is not None:
                schedule_room_event(
                    room.pk,
                    'expulsion_vote_cancelled',
                    room_snapshot(room),
                    vote=cancelled_vote,
                )
        return response

    def join(self, data):
        with transaction.atomic():
            room = Room.objects.select_for_update().filter(
                status=Room.Status.ACTIVE
            ).first()
            if room is None:
                return None
            if room.game_id != data['game_id']:
                raise ActiveRoomGameConflict()
            participant, event_name = self._membership_for(room, data)
            cancelled_vote = cancel_pending_vote_for_target(
                room, participant, 'target_reconnected'
            )
            response = self._membership_response(room, participant)
            if event_name is not None:
                schedule_room_event(room.pk, event_name, room_snapshot(room))
            if cancelled_vote is not None:
                schedule_room_event(
                    room.pk,
                    'expulsion_vote_cancelled',
                    room_snapshot(room),
                    vote=cancelled_vote,
                )
        return response

    def leave(self, data):
        with transaction.atomic():
            room = Room.objects.select_for_update().filter(
                status=Room.Status.ACTIVE
            ).first()
            if room is None:
                return None
            participant = Participant.objects.select_for_update().filter(
                room=room,
                session_id=data['session_id'],
                left_at__isnull=True,
            ).first()
            if participant is None:
                return room, None

            participant.left_at = timezone.now()
            participant.presence = Participant.Presence.OFFLINE
            participant.disconnected_at = None
            participant.save(
                update_fields=(
                    'left_at', 'presence', 'disconnected_at', 'updated_at'
                )
            )
            cancelled_vote = cancel_pending_vote_for_participant(
                room,
                participant,
                target_reason='target_left',
                voter_reason='eligible_voter_left',
            )
            room_id = room.pk
            snapshot = room_snapshot(room)
            if not room.participants.filter(left_at__isnull=True).exists():
                room.delete()
            schedule_room_event(
                room_id,
                'player_left',
                snapshot,
                departed_session_id=participant.session_id,
            )
            if cancelled_vote is not None:
                schedule_room_event(
                    room_id,
                    'expulsion_vote_cancelled',
                    snapshot,
                    vote=cancelled_vote,
                )
        return room, participant

    def _membership_for(self, room, data):
        session_id = data.get('session_id')
        participant = None
        if session_id is not None:
            participant = Participant.objects.select_for_update().filter(
                room=room, session_id=session_id
            ).first()

        if participant is not None:
            if ExpulsionVote.objects.filter(
                room=room,
                target=participant,
                status=ExpulsionVote.Status.APPROVED,
            ).exists():
                raise RemovedSession()

            was_left = participant.left_at is not None
            was_disconnected = participant.presence in (
                Participant.Presence.RECONNECTING,
                Participant.Presence.INACTIVE,
            )
            change = membership_change(
                was_left=was_left,
                was_disconnected=was_disconnected,
                current_display_name=participant.display_name,
                current_game_marker=participant.game_marker,
                data=data,
            )
            for field in ('display_name', 'game_marker'):
                if field in change.update_fields:
                    setattr(participant, field, data[field])
            if was_left:
                participant.left_at = None
            if was_left or was_disconnected:
                participant.presence = Participant.Presence.OFFLINE
                participant.disconnected_at = None
            if change.update_fields:
                participant.save(update_fields=(*change.update_fields, 'updated_at'))
            return participant, change.event_name

        missing_fields = {
            field: 'This field is required for a new room participant.'
            for field in ('display_name', 'game_marker')
            if field not in data
        }
        if missing_fields:
            raise MissingParticipantIdentity(missing_fields)
        participant = Participant.objects.create(
            room=room,
            display_name=data['display_name'],
            game_marker=data['game_marker'],
        )
        return participant, 'player_joined'

    @staticmethod
    def _membership_response(room, participant):
        return {
            'room': room_snapshot(room),
            'session_id': str(participant.session_id),
            'participant_ref': str(participant.public_id),
        }
