"""Public-interface tests for the room entry role (S2, S4, S6).

Every assertion reads the role through the room snapshot the API returns, so
the tests exercise the policy end to end instead of internal storage.
"""

from unittest.mock import patch

from rest_framework.test import APITestCase

from modules.games.duelo import rules
from modules.games.models import Match
from modules.rooms.models import Room
from tests.games.support import SCOPING_TEST_REGISTRY


class SpectatorEntryTests(APITestCase):
    def setUp(self):
        registry_patcher = patch(
            'modules.rooms.serializers.GAME_REGISTRY', SCOPING_TEST_REGISTRY
        )
        registry_patcher.start()
        self.addCleanup(registry_patcher.stop)

    def create_room(self, **extra):
        data = {
            'game_id': 'duelo',
            'display_name': 'Guest One',
            'game_marker': 'guante-rojo',
        }
        data.update(extra)
        return self.client.post('/api/rooms/', data, format='json')

    def join_room(self, **extra):
        data = {'game_id': 'duelo'}
        data.update(extra)
        return self.client.post('/api/rooms/join/', data, format='json')

    def test_free_seat_without_a_match_enters_as_a_player(self):
        response = self.create_room(display_name='Guest One')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['room']['participants'][0]['role'], 'player')

    def test_third_participant_in_a_full_room_enters_as_a_spectator(self):
        self.create_room(display_name='Guest One', game_marker='guante-rojo')
        self.create_room(display_name='Guest Two', game_marker='guante-azul')

        response = self.create_room(display_name='Guest Three', game_marker='guante-verde')

        roles = [entry['role'] for entry in response.data['room']['participants']]
        self.assertEqual(roles, ['player', 'player', 'spectator'])

    def test_join_while_a_match_is_in_progress_enters_as_a_spectator(self):
        self.create_room(display_name='Guest One', game_marker='guante-rojo')
        room = Room.objects.get()
        Match.objects.create(
            room=room,
            game_id='duelo',
            status=Match.Status.IN_PROGRESS,
            state=rules.initial_state(['seat-0', 'seat-1']),
        )

        response = self.join_room(display_name='Guest Two', game_marker='guante-azul')

        participants = response.data['room']['participants']
        self.assertEqual(
            sum(entry['role'] == 'player' for entry in participants), 1
        )
        self.assertEqual(participants[-1]['role'], 'spectator')

    def test_explicit_spectator_with_a_free_seat_enters_as_a_spectator(self):
        response = self.create_room(display_name='Guest One', as_spectator=True)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['room']['participants'][0]['role'], 'spectator')

    def test_join_request_can_ask_for_the_spectator_role(self):
        self.create_room(display_name='Guest One', game_marker='guante-rojo')

        response = self.join_room(
            display_name='Guest Two',
            game_marker='guante-azul',
            as_spectator=True,
        )

        self.assertEqual(response.status_code, 200)
        roles = [entry['role'] for entry in response.data['room']['participants']]
        self.assertEqual(roles, ['player', 'spectator'])

    def test_rejoining_a_spectator_session_keeps_its_role(self):
        created = self.create_room(display_name='Guest One', as_spectator=True)
        session_id = created.data['session_id']

        rejoined = self.join_room(
            session_id=session_id,
            display_name='Guest One',
            game_marker='guante-rojo',
        )

        entry = rejoined.data['room']['participants'][0]
        self.assertEqual(entry['role'], 'spectator')

    def test_rejoining_a_player_with_as_spectator_keeps_its_player_role(self):
        created = self.create_room(display_name='Guest One')
        session_id = created.data['session_id']

        rejoined = self.join_room(
            session_id=session_id,
            display_name='Guest One',
            game_marker='guante-rojo',
            as_spectator=True,
        )

        entry = rejoined.data['room']['participants'][0]
        self.assertEqual(entry['role'], 'player')

    def test_a_returning_player_over_capacity_comes_back_as_a_spectator(self):
        first = self.create_room(display_name='Guest One', game_marker='guante-rojo')
        second = self.create_room(display_name='Guest Two', game_marker='guante-azul')
        third = self.create_room(display_name='Guest Three', game_marker='guante-verde')
        self.assertEqual(
            third.data['room']['participants'][-1]['role'], 'spectator'
        )

        # The player holding seat 0 leaves, so the spectator takes it.
        leave = self.client.post(
            '/api/rooms/leave/',
            {'session_id': first.data['session_id']},
            format='json',
        )
        self.assertEqual(leave.status_code, 204)
        promoted = self.client.post(
            '/api/rooms/play/',
            {'session_id': third.data['session_id']},
            format='json',
        )
        self.assertEqual(promoted.status_code, 200)

        # The first player comes back to a room that is full again. The room
        # must never hold more players than the game accepts.
        returned = self.join_room(
            session_id=first.data['session_id'],
            display_name='Guest One',
            game_marker='guante-rojo',
        )

        participants = returned.data['room']['participants']
        self.assertEqual(
            [entry['role'] for entry in participants],
            ['spectator', 'player', 'player'],
        )
        self.assertEqual(
            sum(entry['role'] == 'player' for entry in participants), 2
        )

        # The room is usable again: exactly the two players can confirm
        # readiness, and the returned session is refused like any spectator.
        refused = self.client.patch(
            '/api/rooms/ready/',
            {'session_id': first.data['session_id'], 'is_ready': True},
            format='json',
        )
        self.assertEqual(refused.status_code, 409)
        for session in (second, third):
            ready = self.client.patch(
                '/api/rooms/ready/',
                {'session_id': session.data['session_id'], 'is_ready': True},
                format='json',
            )
            self.assertEqual(ready.status_code, 200)
        self.assertEqual(
            [
                entry['is_ready']
                for entry in ready.data['room']['participants']
                if entry['role'] == 'player'
            ],
            [True, True],
        )
