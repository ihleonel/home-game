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
