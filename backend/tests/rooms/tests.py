import uuid

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.test import APITestCase

from modules.rooms.catalog import GAMES
from modules.rooms.models import Participant, Room


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


class RoomApiTests(APITestCase):
    def setUp(self):
        self.game = GAMES[0]
        self.other_game = GAMES[1]

    def create_room(self, game=None, display_name='Guest One', game_marker=None, **extra):
        game = game or self.game
        data = {
            'game_id': game['id'],
            'display_name': display_name,
            'game_marker': game_marker or game['markers'][0]['id'],
        }
        data.update(extra)
        return self.client.post('/api/rooms/', data, format='json')

    def join_room(self, game=None, **identity):
        data = {'game_id': (game or self.game)['id']}
        data.update(identity)
        return self.client.post('/api/rooms/join/', data, format='json')

    def test_catalog_lists_stable_games_and_marker_options(self):
        response = self.client.get('/api/games/')

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual([game['id'] for game in response.data], [game['id'] for game in GAMES])
        for game in response.data:
            self.assertTrue(game['label'])
            self.assertTrue(game['description'])
            self.assertTrue(game['markers'])

    def test_active_room_is_not_found_when_no_room_exists(self):
        response = self.client.get('/api/rooms/active/')

        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)

    def test_first_guest_creates_room_and_receives_private_session_token(self):
        response = self.create_room()

        self.assertEqual(response.status_code, http_status.HTTP_201_CREATED)
        participant = Participant.objects.get()
        self.assertEqual(uuid.UUID(response.data['session_id']), participant.session_id)
        self.assertEqual(response.data['room']['game_id'], self.game['id'])
        self.assertEqual(response.data['room']['status'], Room.Status.ACTIVE)
        roster_entry = response.data['room']['participants'][0]
        self.assertEqual(roster_entry['display_name'], 'Guest One')
        self.assertNotIn('id', roster_entry)
        self.assertNotIn('session_id', roster_entry)
        self.assertNotIn('id', response.data['room'])

    def test_create_discovers_existing_room_without_changing_its_game(self):
        first = self.create_room(display_name='Same Name')
        room_id = Room.objects.get().pk

        second = self.create_room(display_name='Same Name')

        self.assertEqual(first.status_code, http_status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, http_status.HTTP_200_OK)
        self.assertEqual(Room.objects.count(), 1)
        self.assertEqual(Room.objects.get().pk, room_id)
        self.assertEqual(Participant.objects.count(), 2)
        self.assertEqual(
            set(Participant.objects.values_list('display_name', flat=True)),
            {'Same Name'},
        )

    def test_join_rejects_a_different_game_without_switching_the_room(self):
        self.create_room()

        response = self.join_room(
            game=self.other_game,
            display_name='Guest Two',
            game_marker=self.other_game['markers'][0]['id'],
        )

        self.assertEqual(response.status_code, http_status.HTTP_409_CONFLICT)
        self.assertEqual(Room.objects.get().game_id, self.game['id'])
        self.assertEqual(Participant.objects.count(), 1)

    def test_existing_token_can_join_without_resending_identity(self):
        created = self.create_room()

        response = self.join_room(session_id=created.data['session_id'])

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['session_id'], created.data['session_id'])
        self.assertEqual(Participant.objects.count(), 1)

    def test_unknown_token_is_not_used_as_a_participant_identity(self):
        self.create_room()
        unknown_token = uuid.uuid4()

        response = self.join_room(
            session_id=str(unknown_token),
            display_name='Guest Two',
            game_marker=self.game['markers'][1]['id'],
        )

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertNotEqual(uuid.UUID(response.data['session_id']), unknown_token)
        self.assertFalse(Participant.objects.filter(session_id=unknown_token).exists())

    def test_rejoining_reactivates_and_updates_the_same_membership(self):
        first = self.create_room()
        second = self.join_room(
            display_name='Guest One',
            game_marker=self.game['markers'][1]['id'],
        )
        session_id = uuid.UUID(first.data['session_id'])
        participant = Participant.objects.get(session_id=session_id)

        leave_response = self.client.post(
            '/api/rooms/leave/',
            {'session_id': str(session_id)},
            format='json',
        )
        participant.refresh_from_db()
        self.assertEqual(leave_response.status_code, http_status.HTTP_204_NO_CONTENT)
        self.assertIsNotNone(participant.left_at)

        rejoin_response = self.join_room(
            session_id=str(session_id),
            display_name='Guest One Updated',
            game_marker=self.game['markers'][2]['id'],
        )

        participant.refresh_from_db()
        self.assertEqual(second.status_code, http_status.HTTP_200_OK)
        self.assertEqual(rejoin_response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(rejoin_response.data['session_id'], str(session_id))
        self.assertEqual(Participant.objects.count(), 2)
        self.assertIsNone(participant.left_at)
        self.assertEqual(participant.display_name, 'Guest One Updated')
        self.assertEqual(participant.game_marker, self.game['markers'][2]['id'])

    def test_leaving_the_last_guest_deletes_room_and_memberships(self):
        created = self.create_room()

        response = self.client.post(
            '/api/rooms/leave/',
            {'session_id': created.data['session_id']},
            format='json',
        )

        self.assertEqual(response.status_code, http_status.HTTP_204_NO_CONTENT)
        self.assertEqual(Room.objects.count(), 0)
        self.assertEqual(Participant.objects.count(), 0)
        self.assertEqual(
            self.client.get('/api/rooms/active/').status_code,
            http_status.HTTP_404_NOT_FOUND,
        )

    def test_ready_state_uses_session_token_not_participant_database_id(self):
        created = self.create_room()
        participant = Participant.objects.get()

        response = self.client.patch(
            '/api/rooms/ready/',
            {'session_id': created.data['session_id'], 'is_ready': True},
            format='json',
        )

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        participant.refresh_from_db()
        self.assertTrue(participant.is_ready)

        invalid_response = self.client.patch(
            '/api/rooms/ready/',
            {'session_id': participant.pk, 'is_ready': False},
            format='json',
        )

        self.assertEqual(invalid_response.status_code, http_status.HTTP_400_BAD_REQUEST)
        participant.refresh_from_db()
        self.assertTrue(participant.is_ready)

    def test_marker_must_belong_to_the_selected_game(self):
        response = self.create_room(game_marker='unlisted-marker')

        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Room.objects.count(), 0)
        self.assertEqual(Participant.objects.count(), 0)
