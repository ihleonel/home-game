from contextlib import contextmanager

from django.db import transaction
from django.utils import timezone

from ....infrastructure.events import room_snapshot, schedule_room_event
from ....models import Participant, Room
from .....games.composition import GAME_REGISTRY
from .....games.models import Match
from ...membership.domain.entities import ActiveRoom, ParticipantMembership
from ...membership.domain.rules import PLAYER_ROLE


class DjangoRoomMembershipGateway:
    @contextmanager
    def atomic(self):
        with transaction.atomic():
            yield self

    def get_active_room_snapshot(self, game_id=None, session_id=None):
        rooms = Room.objects.filter(status=Room.Status.ACTIVE)
        if game_id is not None:
            rooms = rooms.filter(game_id=game_id)
        if session_id is not None:
            memberships = Participant.objects.filter(
                session_id=session_id,
                left_at__isnull=True,
                room__status=Room.Status.ACTIVE,
            )
            if game_id is not None:
                memberships = memberships.filter(room__game_id=game_id)
            room_ids = list(
                memberships.values_list('room_id', flat=True).distinct()[:2]
            )
            if len(room_ids) != 1:
                return None
            rooms = rooms.filter(pk=room_ids[0])
        room = rooms.first()
        return room_snapshot(room) if room is not None else None

    def get_active_room_snapshots(self):
        rooms = Room.objects.filter(status=Room.Status.ACTIVE).order_by('pk')
        return [room_snapshot(room) for room in rooms]

    def active_room_for_update(self, *, game_id=None, session_id=None):
        if game_id is not None and session_id is None:
            room = Room.objects.select_for_update().filter(
                game_id=game_id,
                status=Room.Status.ACTIVE,
            ).first()
        elif session_id is not None and game_id is None:
            memberships = list(
                Participant.objects.select_for_update()
                .select_related('room')
                .filter(
                    session_id=session_id,
                    left_at__isnull=True,
                    room__status=Room.Status.ACTIVE,
                )[:2]
            )
            if len(memberships) != 1:
                return None
            room = memberships[0].room
        else:
            return None
        return self._room_state(room) if room is not None else None

    def create_or_lock_active_room(self, game_id):
        room = Room.objects.select_for_update().filter(
            game_id=game_id,
            status=Room.Status.ACTIVE,
        ).first()
        created = False
        if room is None:
            room, created = Room.objects.get_or_create(
                game_id=game_id,
                status=Room.Status.ACTIVE,
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

    def create_participant(self, room_id, display_name, game_marker, role):
        participant = Participant.objects.create(
            room_id=room_id,
            display_name=display_name,
            game_marker=game_marker,
            role=role,
        )
        return self._participant_state(participant)

    def has_in_progress_match(self, room_id):
        return Match.objects.filter(
            room_id=room_id,
            status=Match.Status.IN_PROGRESS,
        ).exists()

    def count_active_players(self, room_id):
        return Participant.objects.filter(
            room_id=room_id,
            left_at__isnull=True,
            role=PLAYER_ROLE,
        ).count()

    def game_max_seats(self, game_id):
        definition = GAME_REGISTRY.get(game_id)
        return definition.max_seats if definition is not None else None

    def set_participant_role(self, participant_id, role):
        participant = Participant.objects.select_for_update().get(
            pk=participant_id
        )
        participant.role = role
        participant.save(update_fields=('role', 'updated_at'))

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
            is_ready=participant.is_ready,
            role=participant.role,
        )
