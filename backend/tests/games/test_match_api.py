"""API tests for the match REST endpoints (FRG-06).

The suite runs against real Postgres because the endpoints persist a match
through ``DjangoMatchStore`` and resolve seats from the room's own
``Participant`` rows. The channel layer is the in-memory default, so the
projector's fan-out is a local no-op with no connected socket.

Every assertion about a rejection checks the machine-readable ``code`` carried
by the body, so the frontend can tell a resync-worthy conflict from an illegal
action without parsing the Spanish prose.
"""

import uuid

from rest_framework import status
from rest_framework.test import APITestCase

from modules.games.duelo import rules
from modules.games.models import Match, MatchSeat
from modules.rooms.models import Participant, Room


class MatchApiTestCase(APITestCase):
    """One ``duelo`` room holding two ready participants."""

    def setUp(self):
        self.room = Room.objects.create(game_id='duelo')
        self.first = self.create_participant('Guest One', 'guante-rojo')
        self.second = self.create_participant('Guest Two', 'guante-azul')

    def create_participant(
        self,
        display_name,
        marker,
        *,
        room=None,
        is_ready=True,
        session_id=None,
    ):
        return Participant.objects.create(
            room=room if room is not None else self.room,
            session_id=session_id if session_id is not None else uuid.uuid4(),
            display_name=display_name,
            game_marker=marker,
            is_ready=is_ready,
        )

    def start_match(self, participant=None):
        return self.client.post(
            '/api/matches/',
            {'session_id': str((participant or self.first).session_id)},
            format='json',
        )

    def submit_action(
        self,
        match_ref,
        participant,
        *,
        name='pick',
        value='rock',
        version=0,
    ):
        return self.client.post(
            f'/api/matches/{match_ref}/actions/',
            {
                'session_id': str(participant.session_id),
                'action_name': name,
                'action_value': value,
                'expected_version': version,
            },
            format='json',
        )

    def resync(self, match_ref, participant):
        return self.client.get(
            f'/api/matches/{match_ref}/',
            {'session_id': str(participant.session_id)},
        )

    def assert_error(self, response, status_code, code, contains=None):
        self.assertEqual(response.status_code, status_code)
        self.assertEqual(response.data['code'], code)
        if contains is not None:
            self.assertIn(contains, response.data['detail'])


class StartMatchApiTests(MatchApiTestCase):
    def test_starts_a_match_from_the_rooms_ready_participants(self):
        response = self.start_match()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        match = Match.objects.get()
        self.assertEqual(response.data['match_ref'], str(match.public_id))
        self.assertEqual(response.data['version'], 0)
        self.assertEqual(response.data['status'], 'in_progress')
        self.assertEqual(response.data['seat_index'], 0)
        self.assertEqual(response.data['view']['you'], 'seat-0')
        self.assertIsNone(response.data['view']['your_pick'])
        self.assertEqual(
            response.data['seats'],
            [
                {
                    'seat_index': 0,
                    'participant_ref': str(self.first.public_id),
                    'display_name': 'Guest One',
                },
                {
                    'seat_index': 1,
                    'participant_ref': str(self.second.public_id),
                    'display_name': 'Guest Two',
                },
            ],
        )
        # The seats are the room's own ready participants, not anything the
        # request could have supplied.
        self.assertEqual(
            set(match.seats.values_list('participant__public_id', flat=True)),
            {self.first.public_id, self.second.public_id},
        )

    def test_not_ready_participant_is_not_a_seat_and_sees_the_public_view(self):
        third = self.create_participant(
            'Guest Three', 'guante-verde', is_ready=False
        )

        response = self.start_match(third)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data['seat_index'])
        self.assertNotIn('you', response.data['view'])
        seat_refs = {seat['participant_ref'] for seat in response.data['seats']}
        self.assertNotIn(str(third.public_id), seat_refs)

    def test_client_supplied_participant_reference_and_game_id_are_rejected(self):
        response = self.client.post(
            '/api/matches/',
            {
                'session_id': str(self.first.session_id),
                'game_id': 'mystery-game',
                'participant_ref': str(uuid.uuid4()),
                'seats': [
                    {'seat_index': 0, 'participant_ref': str(uuid.uuid4())},
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Match.objects.exists())

    def test_seat_count_outside_the_definition_range_names_the_range(self):
        self.second.is_ready = False
        self.second.save(update_fields=('is_ready',))

        response = self.start_match()

        self.assert_error(response, status.HTTP_409_CONFLICT, 'wrong_seat_count')
        self.assertIn('2', str(response.data['detail']))
        self.assertIn('1', str(response.data['detail']))
        self.assertFalse(Match.objects.exists())

    def test_unknown_game_in_the_room_is_rejected(self):
        room = Room.objects.create(game_id='mystery-game')
        session_id = uuid.uuid4()
        self.create_participant('Mystery One', 'token', room=room, session_id=session_id)
        self.create_participant('Mystery Two', 'token', room=room)

        response = self.client.post(
            '/api/matches/', {'session_id': str(session_id)}, format='json'
        )

        self.assert_error(response, status.HTTP_409_CONFLICT, 'unknown_game')

    def test_match_already_in_progress_is_rejected_with_its_own_code(self):
        first = self.start_match()
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        response = self.start_match()

        self.assert_error(
            response, status.HTTP_409_CONFLICT, 'match_already_in_progress'
        )
        self.assertEqual(Match.objects.count(), 1)

    def test_start_without_an_active_room_is_not_found(self):
        response = self.client.post(
            '/api/matches/', {'session_id': str(uuid.uuid4())}, format='json'
        )

        self.assert_error(response, status.HTTP_404_NOT_FOUND, 'active_room_not_found')


class SubmitActionApiTests(MatchApiTestCase):
    def setUp(self):
        super().setUp()
        self.match_ref = self.start_match().data['match_ref']

    def test_seat_owner_applies_an_action_and_receives_its_own_view(self):
        response = self.submit_action(self.match_ref, self.first, value='rock', version=0)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['match_ref'], self.match_ref)
        self.assertEqual(response.data['version'], 1)
        self.assertEqual(response.data['status'], 'in_progress')
        self.assertEqual(response.data['seat_index'], 0)
        self.assertEqual(response.data['view']['your_pick'], 'rock')
        self.assertEqual(Match.objects.get(public_id=self.match_ref).version, 1)

    def test_unknown_match_is_not_found(self):
        response = self.submit_action(str(uuid.uuid4()), self.first)

        self.assert_error(response, status.HTTP_404_NOT_FOUND, 'match_not_found')

    def test_match_of_an_unknown_game_is_rejected(self):
        match = Match.objects.create(
            room=self.room,
            game_id='mystery-game',
            status=Match.Status.FINISHED,
            state={},
        )
        MatchSeat.objects.create(
            match=match, index=0, seat_id='seat-0', participant=self.first
        )

        response = self.submit_action(str(match.public_id), self.first, version=0)

        self.assert_error(response, status.HTTP_409_CONFLICT, 'unknown_game')

    def test_action_on_a_finished_match_is_rejected(self):
        match = Match.objects.create(
            room=self.room,
            game_id='duelo',
            status=Match.Status.FINISHED,
            state=rules.initial_state(['seat-0', 'seat-1']),
        )

        response = self.submit_action(str(match.public_id), self.first, version=0)

        self.assert_error(response, status.HTTP_409_CONFLICT, 'match_not_playable')

    def test_participant_without_a_seat_is_forbidden(self):
        third = self.create_participant(
            'Guest Three', 'guante-verde', is_ready=False
        )

        response = self.submit_action(self.match_ref, third, version=0)

        self.assert_error(response, status.HTTP_403_FORBIDDEN, 'not_a_seat')

    def test_stale_version_is_rejected_and_carries_the_current_version(self):
        response = self.submit_action(self.match_ref, self.first, version=99)

        self.assert_error(response, status.HTTP_409_CONFLICT, 'stale_version')
        self.assertEqual(response.data['version'], 0)

    def test_seat_out_of_turn_is_rejected(self):
        first = self.submit_action(self.match_ref, self.first, value='rock', version=0)
        self.assertEqual(first.status_code, status.HTTP_200_OK)

        response = self.submit_action(self.match_ref, self.first, value='paper', version=1)

        self.assert_error(response, status.HTTP_409_CONFLICT, 'not_your_turn')

    def test_illegal_action_name_is_rejected(self):
        response = self.submit_action(self.match_ref, self.first, name='fold', version=0)

        self.assert_error(response, status.HTTP_400_BAD_REQUEST, 'illegal_action')

    def test_illegal_action_value_is_rejected(self):
        response = self.submit_action(self.match_ref, self.first, value='bomb', version=0)

        self.assert_error(response, status.HTTP_400_BAD_REQUEST, 'illegal_action')


class MatchFinishResetsReadinessApiTests(MatchApiTestCase):
    def test_finishing_a_match_resets_readiness_and_unblocks_leaving(self):
        match_ref = self.start_match().data['match_ref']

        # The dead end this unit closes: while both seats are ready, leaving
        # the room is refused with 409.
        blocked = self.client.post(
            '/api/rooms/leave/',
            {'session_id': str(self.first.session_id)},
            format='json',
        )
        self.assertEqual(blocked.status_code, status.HTTP_409_CONFLICT)

        # Seat 0 takes both rounds 2-0 through the real API.
        for participant, value, version in (
            (self.first, 'rock', 0),
            (self.second, 'scissors', 1),
            (self.first, 'rock', 2),
            (self.second, 'scissors', 3),
        ):
            response = self.submit_action(
                match_ref, participant, value=value, version=version
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'finished')

        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertFalse(self.first.is_ready)
        self.assertFalse(self.second.is_ready)

        # The user-facing proof that the dead end is gone: the same leave that
        # was a 409 while ready now succeeds.
        left = self.client.post(
            '/api/rooms/leave/',
            {'session_id': str(self.first.session_id)},
            format='json',
        )
        self.assertEqual(left.status_code, status.HTTP_204_NO_CONTENT)
        self.first.refresh_from_db()
        self.assertIsNotNone(self.first.left_at)


class ResyncApiTests(MatchApiTestCase):
    def setUp(self):
        super().setUp()
        self.match_ref = self.start_match().data['match_ref']

    def test_seat_owner_resyncs_to_its_own_view(self):
        response = self.resync(self.match_ref, self.first)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['match_ref'], self.match_ref)
        self.assertEqual(response.data['version'], 0)
        self.assertEqual(response.data['status'], 'in_progress')
        self.assertEqual(response.data['seat_index'], 0)
        self.assertEqual(response.data['view']['you'], 'seat-0')

    def test_spectator_resyncs_to_the_public_view(self):
        spectator = self.create_participant(
            'Guest Three', 'guante-verde', is_ready=False
        )

        response = self.resync(self.match_ref, spectator)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['seat_index'])
        self.assertNotIn('you', response.data['view'])
        self.assertNotIn('your_pick', response.data['view'])

    def test_unknown_match_is_not_found(self):
        response = self.resync(str(uuid.uuid4()), self.first)

        self.assert_error(response, status.HTTP_404_NOT_FOUND, 'match_not_found')


class NoPickLeakTests(MatchApiTestCase):
    def test_other_seats_pending_pick_is_never_in_a_response_body(self):
        match_ref = self.start_match().data['match_ref']
        acted = self.submit_action(match_ref, self.first, value='rock', version=0)

        # The acting seat's own view carries its own pick...
        self.assertEqual(acted.data['view']['your_pick'], 'rock')
        self.assertIn(b'rock', acted.content)

        # ...but the opponent's view and the public view never do.
        opponent = self.resync(match_ref, self.second)
        self.assertEqual(opponent.status_code, status.HTTP_200_OK)
        self.assertIsNone(opponent.data['view']['your_pick'])
        self.assertTrue(opponent.data['view']['opponent_has_picked'])
        self.assertNotIn(b'rock', opponent.content)

        spectator = self.create_participant(
            'Guest Three', 'guante-verde', is_ready=False
        )
        public = self.resync(match_ref, spectator)
        self.assertEqual(public.status_code, status.HTTP_200_OK)
        self.assertNotIn(b'rock', public.content)
