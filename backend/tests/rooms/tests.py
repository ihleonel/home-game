import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.db import close_old_connections, IntegrityError, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.test import APIClient, APITestCase

from modules.rooms.constants import RECONNECT_GRACE_SECONDS
from modules.rooms.models import Participant, Room
from tests.games.support import SCOPING_TEST_GAMES, SCOPING_TEST_REGISTRY


# Aliases into the single shared two-game fixture in tests.games.support. The
# real ``duelo`` definition plus the test-only second game keep the per-game
# scoping assertions without shipping any fake game.
TEST_GAME_REGISTRY = SCOPING_TEST_REGISTRY
TEST_GAMES = SCOPING_TEST_GAMES


class RoomModelTests(TestCase):
    def test_only_one_active_room_can_exist_per_game(self):
        first = Room.objects.create(game_id='first-game')
        second = Room.objects.create(game_id='second-game')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Room.objects.create(game_id='first-game')

        active_room_ids = set(
            Room.objects.filter(status=Room.Status.ACTIVE).values_list('pk', flat=True)
        )
        self.assertEqual(active_room_ids, {first.pk, second.pk})

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
        self.game = TEST_GAMES[0]
        self.other_game = TEST_GAMES[1]
        registry_patcher = patch(
            'modules.rooms.serializers.GAME_REGISTRY', TEST_GAME_REGISTRY
        )
        registry_patcher.start()
        self.addCleanup(registry_patcher.stop)

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

    def create_ghost_room(
        self,
        game=None,
        *,
        presence=Participant.Presence.RECONNECTING,
        is_ready=False,
        disconnected_at=None,
    ):
        """A room whose only participant disconnected and never came back."""
        game = game or self.game
        room = Room.objects.create(game_id=game['id'])
        participant = Participant.objects.create(
            room=room,
            session_id=uuid.uuid4(),
            display_name='Ghost Guest',
            game_marker=game['markers'][0]['id'],
            presence=presence,
            disconnected_at=(
                disconnected_at
                if disconnected_at is not None
                else timezone.now()
                - timedelta(seconds=RECONNECT_GRACE_SECONDS + 30)
            ),
            is_ready=is_ready,
        )
        return room, participant

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


    def test_create_joins_or_creates_the_selected_games_room(self):
        first = self.create_room(game=self.game, display_name='First Guest')
        second_game_first_entry = self.create_room(
            game=self.other_game, display_name='Second Game Guest'
        )
        first_game_second_entry = self.create_room(
            game=self.game, display_name='First Game Guest Two'
        )

        self.assertEqual(first.status_code, http_status.HTTP_201_CREATED)
        self.assertEqual(
            second_game_first_entry.status_code, http_status.HTTP_201_CREATED
        )
        self.assertEqual(first_game_second_entry.status_code, http_status.HTTP_200_OK)
        self.assertEqual(
            set(Room.objects.values_list('game_id', flat=True)),
            {self.game['id'], self.other_game['id']},
        )
        self.assertEqual(
            Room.objects.get(game_id=self.game['id']).participants.count(), 2
        )
        self.assertEqual(
            Room.objects.get(game_id=self.other_game['id']).participants.count(), 1
        )
        self.assertEqual(Participant.objects.count(), 3)


    def test_join_returns_not_found_when_selected_game_has_no_room(self):
        self.create_room()

        response = self.join_room(
            game=self.other_game,
            display_name='Guest Two',
            game_marker=self.other_game['markers'][0]['id'],
        )

        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)
        self.assertEqual(Room.objects.get().game_id, self.game['id'])
        self.assertEqual(Participant.objects.count(), 1)

    def test_join_targets_the_selected_game_when_multiple_rooms_are_active(self):
        first = self.create_room(game=self.game, display_name='First Game Guest')
        second = self.create_room(
            game=self.other_game, display_name='Second Game Guest'
        )

        response = self.join_room(
            game=self.other_game,
            display_name='Second Game Guest Two',
            game_marker=self.other_game['markers'][1]['id'],
        )

        self.assertEqual(first.status_code, http_status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, http_status.HTTP_201_CREATED)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['room']['game_id'], self.other_game['id'])
        self.assertEqual(
            Room.objects.get(game_id=self.game['id']).participants.count(), 1
        )
        self.assertEqual(
            Room.objects.get(game_id=self.other_game['id']).participants.count(), 2
        )

    def test_leave_targets_the_room_containing_the_session(self):
        first = self.create_room(game=self.game, display_name='First Game Guest')
        second = self.create_room(
            game=self.other_game, display_name='Second Game Guest'
        )

        response = self.client.post(
            '/api/rooms/leave/',
            {'session_id': second.data['session_id']},
            format='json',
        )

        self.assertEqual(response.status_code, http_status.HTTP_204_NO_CONTENT)
        self.assertTrue(
            Participant.objects.filter(
                session_id=first.data['session_id'], left_at__isnull=True
            ).exists()
        )
        self.assertFalse(
            Participant.objects.filter(
                session_id=second.data['session_id'], left_at__isnull=True
            ).exists()
        )
        self.assertEqual(Room.objects.count(), 1)
        self.assertEqual(Room.objects.get().game_id, self.game['id'])

    def test_ready_participant_cannot_leave_until_readiness_is_cleared(self):
        created = self.create_room()
        self.join_room(
            display_name='Guest Two',
            game_marker=self.game['markers'][1]['id'],
        )
        session_id = created.data['session_id']

        ready_response = self.client.patch(
            '/api/rooms/ready/',
            {'session_id': session_id, 'is_ready': True},
            format='json',
        )
        self.assertEqual(ready_response.status_code, http_status.HTTP_200_OK)

        with patch(
            'modules.rooms.infrastructure.events.broadcast_room_event'
        ) as broadcast:
            with self.captureOnCommitCallbacks(execute=True):
                blocked_leave = self.client.post(
                    '/api/rooms/leave/',
                    {'session_id': session_id},
                    format='json',
                )

        self.assertEqual(blocked_leave.status_code, http_status.HTTP_409_CONFLICT)
        broadcast.assert_not_called()
        participant = Participant.objects.get(session_id=session_id)
        self.assertIsNone(participant.left_at)
        self.assertTrue(participant.is_ready)

        not_ready_response = self.client.patch(
            '/api/rooms/ready/',
            {'session_id': session_id, 'is_ready': False},
            format='json',
        )
        self.assertEqual(not_ready_response.status_code, http_status.HTTP_200_OK)

        with self.captureOnCommitCallbacks(execute=True):
            allowed_leave = self.client.post(
                '/api/rooms/leave/',
                {'session_id': session_id},
                format='json',
            )

        self.assertEqual(allowed_leave.status_code, http_status.HTTP_204_NO_CONTENT)
        participant.refresh_from_db()
        self.assertIsNotNone(participant.left_at)

    def test_readiness_targets_the_room_containing_the_session(self):
        self.create_room(game=self.game, display_name='First Game Guest')
        second = self.create_room(
            game=self.other_game, display_name='Second Game Guest'
        )

        response = self.client.patch(
            '/api/rooms/ready/',
            {'session_id': second.data['session_id'], 'is_ready': True},
            format='json',
        )

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['room']['game_id'], self.other_game['id'])
        self.assertTrue(
            Participant.objects.get(session_id=second.data['session_id']).is_ready
        )
        self.assertFalse(
            Participant.objects.get(room__game_id=self.game['id']).is_ready
        )

    def test_active_room_lookup_uses_game_or_session_and_rejects_ambiguity(self):
        self.create_room(game=self.game, display_name='First Game Guest')
        second = self.create_room(
            game=self.other_game, display_name='Second Game Guest'
        )

        by_game = self.client.get(
            '/api/rooms/active/', {'game_id': self.other_game['id']}
        )
        by_session = self.client.get(
            '/api/rooms/active/', {'session_id': second.data['session_id']}
        )
        ambiguous = self.client.get('/api/rooms/active/')
        unknown_session = self.client.get(
            '/api/rooms/active/', {'session_id': str(uuid.uuid4())}
        )

        self.assertEqual(by_game.status_code, http_status.HTTP_200_OK)
        self.assertEqual(by_game.data['room']['game_id'], self.other_game['id'])
        self.assertEqual(by_session.status_code, http_status.HTTP_200_OK)
        self.assertEqual(by_session.data['room']['game_id'], self.other_game['id'])
        self.assertEqual(ambiguous.status_code, http_status.HTTP_404_NOT_FOUND)
        self.assertEqual(unknown_session.status_code, http_status.HTTP_404_NOT_FOUND)

    def test_ambiguous_session_does_not_select_a_room_for_mutations(self):
        first = self.create_room(game=self.game, display_name='First Game Guest')
        second = self.create_room(
            game=self.other_game, display_name='Second Game Guest'
        )
        first_session = uuid.UUID(first.data['session_id'])
        second_participant = Participant.objects.get(
            session_id=second.data['session_id']
        )
        second_participant.session_id = first_session
        second_participant.save(update_fields=('session_id', 'updated_at'))

        scoped_lookup = self.client.get(
            '/api/rooms/active/',
            {
                'game_id': self.other_game['id'],
                'session_id': str(first_session),
            },
        )
        readiness = self.client.patch(
            '/api/rooms/ready/',
            {'session_id': str(first_session), 'is_ready': True},
            format='json',
        )
        leave = self.client.post(
            '/api/rooms/leave/',
            {'session_id': str(first_session)},
            format='json',
        )

        self.assertEqual(scoped_lookup.status_code, http_status.HTTP_200_OK)
        self.assertEqual(scoped_lookup.data['room']['game_id'], self.other_game['id'])
        self.assertEqual(readiness.status_code, http_status.HTTP_404_NOT_FOUND)
        self.assertEqual(leave.status_code, http_status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            Participant.objects.filter(session_id=first_session, left_at__isnull=True).count(),
            2,
        )
        self.assertFalse(
            Participant.objects.filter(session_id=first_session, is_ready=True).exists()
        )

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

    def test_active_room_lookup_reaps_a_ghost_room_and_answers_not_found(self):
        room, _ = self.create_ghost_room()

        response = self.client.get(
            '/api/rooms/active/', {'game_id': self.game['id']}
        )

        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)
        self.assertFalse(Room.objects.filter(pk=room.pk).exists())
        self.assertEqual(Participant.objects.count(), 0)

    def test_active_room_lookup_keeps_a_room_inside_the_grace_window(self):
        room, participant = self.create_ghost_room(
            disconnected_at=timezone.now()
            - timedelta(seconds=RECONNECT_GRACE_SECONDS - 5),
        )

        response = self.client.get(
            '/api/rooms/active/', {'game_id': self.game['id']}
        )

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['room']['game_id'], self.game['id'])
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())
        participant.refresh_from_db()
        self.assertIsNone(participant.left_at)
        self.assertEqual(participant.presence, Participant.Presence.RECONNECTING)

    def test_join_after_a_ghost_room_answers_not_found_without_recreating_it(self):
        self.create_ghost_room()

        response = self.join_room(
            display_name='Guest Two',
            game_marker=self.game['markers'][1]['id'],
        )

        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            response.data['detail'],
            'No hay ninguna sala activa a la que unirse.',
        )
        self.assertEqual(Room.objects.count(), 0)
        self.assertEqual(Participant.objects.count(), 0)

    def test_create_after_a_ghost_room_returns_created_with_a_clean_roster(self):
        _, ghost = self.create_ghost_room()

        response = self.create_room(display_name='Guest Two')

        self.assertEqual(response.status_code, http_status.HTTP_201_CREATED)
        self.assertEqual(Room.objects.count(), 1)
        self.assertEqual(Participant.objects.count(), 1)
        roster = response.data['room']['participants']
        self.assertEqual([entry['display_name'] for entry in roster], ['Guest Two'])
        self.assertNotIn(
            str(ghost.public_id), [entry['participant_ref'] for entry in roster]
        )

    def test_reaped_ready_participant_does_not_come_back_ready_on_rejoin(self):
        room, ghost = self.create_ghost_room(is_ready=True)
        # A live companion keeps the room alive across the reap, so the ghost's
        # row is revived rather than cascade-deleted with the room.
        Participant.objects.create(
            room=room,
            session_id=uuid.uuid4(),
            display_name='Companion',
            game_marker=self.game['markers'][1]['id'],
            presence=Participant.Presence.ONLINE,
        )
        self.assertEqual(Room.objects.count(), 1)

        response = self.join_room(
            session_id=str(ghost.session_id),
            display_name='Ghost Guest',
        )

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        rejoin_entry = next(
            entry
            for entry in response.data['room']['participants']
            if entry['participant_ref'] == str(ghost.public_id)
        )
        self.assertFalse(rejoin_entry['is_ready'])
        ghost.refresh_from_db()
        self.assertFalse(ghost.is_ready)

    def test_marker_must_belong_to_the_selected_game(self):
        response = self.create_room(game_marker='unlisted-marker')

        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Room.objects.count(), 0)
        self.assertEqual(Participant.objects.count(), 0)


class ConcurrentRoomApiTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        registry_patcher = patch(
            'modules.rooms.serializers.GAME_REGISTRY', TEST_GAME_REGISTRY
        )
        registry_patcher.start()
        self.addCleanup(registry_patcher.stop)

    def test_competing_entries_for_one_game_converge_on_one_room(self):
        game = TEST_GAMES[0]
        start = Barrier(2)

        def enter_game(index):
            close_old_connections()
            try:
                client = APIClient()
                start.wait(timeout=10)
                return client.post(
                    '/api/rooms/',
                    {
                        'game_id': game['id'],
                        'display_name': f'Guest {index}',
                        'game_marker': game['markers'][index]['id'],
                    },
                    format='json',
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(enter_game, range(2)))

        self.assertEqual(
            sorted(response.status_code for response in responses),
            [http_status.HTTP_200_OK, http_status.HTTP_201_CREATED],
        )
        self.assertEqual(Room.objects.filter(game_id=game['id']).count(), 1)
        self.assertEqual(Participant.objects.count(), 2)
        self.assertEqual(
            set(Participant.objects.values_list('room_id', flat=True)),
            set(Room.objects.filter(game_id=game['id']).values_list('pk', flat=True)),
        )
