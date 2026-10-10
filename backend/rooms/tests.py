import uuid

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from .models import Participant, Room


class RoomModelTests(TestCase):
    def test_only_one_active_room_can_exist_globally(self):
        Room.objects.create(game_id='first-game')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Room.objects.create(game_id='second-game')

        self.assertEqual(Room.objects.filter(status=Room.Status.ACTIVE).count(), 1)

    def test_ended_room_status_cannot_be_persisted(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Room.objects.create(game_id='ended-game', status='ended')

        self.assertEqual(Room.objects.count(), 0)

    def test_deleting_room_cascades_memberships_and_frees_active_slot(self):
        room = Room.objects.create(game_id='first-game')
        participant = Participant.objects.create(
            room=room,
            session_id=uuid.uuid4(),
            display_name='Guest One',
            game_marker='blue-token',
        )

        room.delete()

        self.assertFalse(Room.objects.filter(pk=room.pk).exists())
        self.assertFalse(Participant.objects.filter(pk=participant.pk).exists())

        next_room = Room.objects.create(game_id='second-game')
        self.assertEqual(next_room.status, Room.Status.ACTIVE)
        self.assertEqual(Room.objects.filter(status=Room.Status.ACTIVE).count(), 1)


class ParticipantModelTests(TestCase):
    def setUp(self):
        self.room = Room.objects.create(game_id='first-game')
        self.session_id = uuid.uuid4()

    def test_participant_identity_membership_and_leave_state_are_persisted(self):
        participant = Participant.objects.create(
            room=self.room,
            session_id=self.session_id,
            display_name='Guest One',
            game_marker='blue-token',
            is_ready=True,
        )
        participant.refresh_from_db()

        self.assertEqual(participant.room, self.room)
        self.assertEqual(participant.session_id, self.session_id)
        self.assertEqual(participant.display_name, 'Guest One')
        self.assertEqual(participant.game_marker, 'blue-token')
        self.assertTrue(participant.is_ready)
        self.assertIsNotNone(participant.joined_at)
        self.assertIsNone(participant.left_at)
        self.assertEqual(list(self.room.participants.filter(left_at__isnull=True)), [participant])

        participant.left_at = timezone.now()
        participant.save(update_fields=('left_at', 'updated_at'))
        self.assertFalse(self.room.participants.filter(left_at__isnull=True).exists())

        participant.left_at = None
        participant.save(update_fields=('left_at', 'updated_at'))
        self.assertTrue(self.room.participants.filter(left_at__isnull=True).exists())

    def test_session_identity_is_unique_within_a_room(self):
        Participant.objects.create(
            room=self.room,
            session_id=self.session_id,
            display_name='Guest One',
            game_marker='blue-token',
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Participant.objects.create(
                    room=self.room,
                    session_id=self.session_id,
                    display_name='Guest One Duplicate',
                    game_marker='red-token',
                )
