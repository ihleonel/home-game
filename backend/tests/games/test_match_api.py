"""API tests for the match REST endpoints (FRG-06).

The suite runs against real Postgres because the start path persists a match
through ``DjangoMatchStore`` and resolves seats from the room's own
``Participant`` rows. The channel layer is the in-memory default, so the
projector's fan-out is a local no-op with no connected socket.

Start fixtures drive ``open_match_for_room`` directly, the same interface
gateway the lobby countdown calls, because the reap-before-seats rule lives
there and not in the REST view. Rejection assertions on the HTTP path check
the machine-readable ``code`` carried by the body, so the frontend can tell a
resync-worthy conflict from an illegal action without parsing the Spanish
prose; the relocated start tests assert on the domain error instead.
"""

import uuid
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from modules.games.duelo import rules
from modules.games.interfaces.composition import compose_match_dependencies
from modules.games.interfaces.match_start import open_match_for_room
from modules.games.models import Match, MatchSeat
from modules.games.runtime.domain.errors import WrongSeatCount
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

    def disconnect(
        self,
        participant,
        *,
        presence=Participant.Presence.INACTIVE,
        seconds_ago=61,
    ):
        """Mark ``participant`` as disconnected for the given grace offset.

        The default 61s is past the 60s reconnect grace, so the row is stale
        and reapable; a smaller ``seconds_ago`` keeps it inside the window.
        """
        participant.presence = presence
        participant.disconnected_at = timezone.now() - timedelta(
            seconds=seconds_ago
        )
        participant.save(update_fields=('presence', 'disconnected_at'))
        return participant

    def open_match(self, *, reaping=None, rng=None):
        """Open a match for ``self.room`` through the shared interface gateway.

        This is the non-HTTP start every non-start test uses: it drives
        ``open_match_for_room`` with the production dependencies, so the
        reap-before-seats rule is exercised where the lobby countdown also
        exercises it. The reaping service is injectable so a test can prove
        that rule is load-bearing rather than incidental. ``rng`` is forwarded
        to ``start_match``; the production caller passes
        ``dependencies.rng`` and only games that need randomness require it.
        """
        dependencies = compose_match_dependencies()
        return open_match_for_room(
            room=self.room,
            reaping=dependencies.reaping if reaping is None else reaping,
            store=dependencies.store,
            registry=dependencies.registry,
            projector=dependencies.projector,
            rng=rng,
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


class GhostReadyParticipantApiTests(MatchApiTestCase):
    """A ready participant who closed the tab must not take a seat.

    Seats come from ``left_at IS NULL AND is_ready=True``, and ``disconnect``
    never clears readiness, so a stale ready row used to be seated from index
    0. The reaping pass inside ``open_match_for_room``, the shared interface
    gateway the lobby countdown also calls, must remove it before the seats
    are resolved.
    """

    def test_a_ghost_ready_participant_leaves_only_the_live_player_ready(self):
        # The only other ready participant is the ghost, so after the reap the
        # room has a single ready player and the start must fail honestly
        # instead of seating a phantom.
        self.disconnect(self.second)

        with self.assertRaises(WrongSeatCount):
            self.open_match()

        # The prose assertion moved out with the HTTP transport.
        self.assertFalse(Match.objects.exists())
        self.assertFalse(MatchSeat.objects.exists())
        self.second.refresh_from_db()
        self.assertIsNotNone(self.second.left_at)
        self.assertFalse(self.second.is_ready)

    def test_a_ghost_ready_participant_never_becomes_a_seat(self):
        ghost = self.create_participant('Ghost', 'guante-fantasma')
        self.disconnect(ghost, presence=Participant.Presence.RECONNECTING)

        opened = self.open_match()

        seat_refs = [seat.participant_ref for seat in opened.record.seats]
        self.assertEqual(
            seat_refs,
            [str(self.first.public_id), str(self.second.public_id)],
        )
        self.assertNotIn(str(ghost.public_id), seat_refs)
        match = Match.objects.get()
        self.assertFalse(
            MatchSeat.objects.filter(match=match, participant=ghost).exists()
        )
        ghost.refresh_from_db()
        self.assertIsNotNone(ghost.left_at)
        self.assertFalse(ghost.is_ready)

    def test_a_ready_participant_inside_the_grace_window_is_kept(self):
        inside = self.create_participant('Inside', 'guante-ambar')
        self.disconnect(inside, seconds_ago=30)

        # Three ready rows still reach the seat check, so the existing honest
        # count rejection is unchanged for a participant inside the grace.
        with self.assertRaises(WrongSeatCount):
            self.open_match()

        # The prose assertion moved out with the HTTP transport.
        self.assertFalse(Match.objects.exists())
        inside.refresh_from_db()
        self.assertIsNotNone(inside.disconnected_at)
        self.assertTrue(inside.is_ready)
        self.assertIsNone(inside.left_at)


class ReadySeatsOnlyApiTests(MatchApiTestCase):
    """Seats come from the room's ready members, so readiness is the filter."""

    def test_a_not_ready_member_is_neither_a_seat_nor_a_ready_participant(self):
        # A third member who never marked ready must not shift the seats: the
        # room opens with exactly its two ready participants, so the
        # ``is_ready=True`` half of the seat query stays load-bearing. A member
        # that did reach the ready set is covered by the ghost and seat-count
        # tests above.
        third = self.create_participant(
            'Guest Three', 'guante-verde', is_ready=False
        )

        opened = self.open_match()

        seat_refs = [seat.participant_ref for seat in opened.record.seats]
        self.assertEqual(
            seat_refs,
            [str(self.first.public_id), str(self.second.public_id)],
        )
        self.assertNotIn(str(third.public_id), seat_refs)
        self.assertEqual(
            [str(participant.public_id) for participant in opened.participants],
            [str(self.first.public_id), str(self.second.public_id)],
        )


class SpectatorSeatExclusionApiTests(MatchApiTestCase):
    """A spectator never occupies a seat, even with a stray ``is_ready``."""

    def test_a_ready_spectator_is_not_seated(self):
        spectator = self.create_participant('Guest Three', 'guante-verde')
        spectator.role = Participant.Role.SPECTATOR
        # Pin the query filter: readiness alone must not buy a seat.
        spectator.is_ready = True
        spectator.save(update_fields=('role', 'is_ready'))

        opened = self.open_match()

        seat_refs = [seat.participant_ref for seat in opened.record.seats]
        self.assertEqual(
            seat_refs,
            [str(self.first.public_id), str(self.second.public_id)],
        )
        self.assertNotIn(str(spectator.public_id), seat_refs)
        match = Match.objects.get()
        self.assertFalse(
            MatchSeat.objects.filter(match=match, participant=spectator).exists()
        )


class GhostFirstSeatOrderApiTests(MatchApiTestCase):
    """The ghost that joined first would otherwise occupy seat 0."""

    def setUp(self):
        self.room = Room.objects.create(game_id='duelo')
        self.ghost = self.create_participant('Ghost First', 'guante-fantasma')
        self.disconnect(self.ghost)
        self.first = self.create_participant('Guest One', 'guante-rojo')
        self.second = self.create_participant('Guest Two', 'guante-azul')

    def test_the_reaped_ghost_does_not_push_the_live_players_off_seat_zero(self):
        opened = self.open_match()

        self.assertEqual(
            [seat.participant_ref for seat in opened.record.seats],
            [str(self.first.public_id), str(self.second.public_id)],
        )
        self.assertFalse(
            MatchSeat.objects.filter(participant=self.ghost).exists()
        )
        self.ghost.refresh_from_db()
        self.assertIsNotNone(self.ghost.left_at)
        self.assertFalse(self.ghost.is_ready)


class SubmitActionApiTests(MatchApiTestCase):
    def setUp(self):
        super().setUp()
        self.match_ref = self.open_match().record.match_ref

    def test_seat_owner_applies_an_action_and_receives_its_own_view(self):
        response = self.submit_action(self.match_ref, self.first, value='rock', version=0)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['match_ref'], self.match_ref)
        self.assertEqual(response.data['version'], 1)
        self.assertEqual(response.data['status'], 'in_progress')
        self.assertEqual(response.data['seat_index'], 0)
        self.assertEqual(response.data['view']['your_pick'], 'rock')
        self.assertEqual(Match.objects.get(public_id=self.match_ref).version, 1)

    def test_action_response_carries_the_public_roster(self):
        response = self.submit_action(
            self.match_ref, self.first, value='rock', version=0
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data['roster'],
            [
                {
                    'seat_id': 'seat-0',
                    'index': 0,
                    'display_name': 'Guest One',
                    'game_marker': 'guante-rojo',
                    'game_marker_label': 'Guante rojo',
                },
                {
                    'seat_id': 'seat-1',
                    'index': 1,
                    'display_name': 'Guest Two',
                    'game_marker': 'guante-azul',
                    'game_marker_label': 'Guante azul',
                },
            ],
        )

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
        match_ref = self.open_match().record.match_ref

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
        self.match_ref = self.open_match().record.match_ref

    def test_seat_owner_resyncs_to_its_own_view(self):
        response = self.resync(self.match_ref, self.first)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['match_ref'], self.match_ref)
        self.assertEqual(response.data['version'], 0)
        self.assertEqual(response.data['status'], 'in_progress')
        self.assertEqual(response.data['seat_index'], 0)
        self.assertEqual(response.data['view']['you'], 'seat-0')

    def test_resync_response_carries_the_public_roster(self):
        response = self.resync(self.match_ref, self.first)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [entry['display_name'] for entry in response.data['roster']],
            ['Guest One', 'Guest Two'],
        )
        self.assertEqual(
            [entry['game_marker_label'] for entry in response.data['roster']],
            ['Guante rojo', 'Guante azul'],
        )

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
        match_ref = self.open_match().record.match_ref
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


class ManualStartRetiredApiTests(MatchApiTestCase):
    """The room owns the start decision, so no manual start endpoint is served."""

    def test_the_manual_start_endpoint_is_not_served(self):
        response = self.client.post(
            '/api/matches/', {'session_id': str(self.first.session_id)}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(Match.objects.exists())


class _FixedRng:
    """Deterministic ``RandomSource`` used to pin the random opening seat."""

    def __init__(self, order):
        self.order = list(order)

    def shuffle(self, items):
        return list(self.order)

    def roll(self, sides):
        return 1


class TaTeTiStartApiTests(APITestCase):
    """The ta-te-ti start path through the real interface gateway.

    This pins the S4 seam end to end: ``open_match_for_room`` must forward the
    ``RandomSource`` to ``start_match``, and a missing source must fail loudly
    instead of silently opening with seat 0 on turn.
    """

    def setUp(self):
        self.room = Room.objects.create(game_id='ta-te-ti')
        self.first = Participant.objects.create(
            room=self.room,
            session_id=uuid.uuid4(),
            display_name='Guest One',
            game_marker='sol',
            is_ready=True,
        )
        self.second = Participant.objects.create(
            room=self.room,
            session_id=uuid.uuid4(),
            display_name='Guest Two',
            game_marker='luna',
            is_ready=True,
        )

    def _open(self, rng):
        dependencies = compose_match_dependencies()
        return open_match_for_room(
            room=self.room,
            reaping=dependencies.reaping,
            store=dependencies.store,
            registry=dependencies.registry,
            projector=dependencies.projector,
            rng=rng,
        )

    def test_open_without_rng_fails_loudly_and_persists_nothing(self):
        with self.assertRaises(ValueError):
            self._open(None)

        self.assertFalse(Match.objects.exists())
        self.assertFalse(MatchSeat.objects.exists())

    def test_open_with_rng_persists_the_drawn_opening_seat_and_empty_board(self):
        opened = self._open(_FixedRng(('seat-1', 'seat-0')))

        match = Match.objects.get(public_id=opened.record.match_ref)
        self.assertEqual(match.game_id, 'ta-te-ti')
        self.assertEqual(match.state['turn'], 'seat-1')
        self.assertEqual(match.state['board'], [None] * 9)
        self.assertFalse(match.state['finished'])
        # The seat ids are still index-ordered, so seat-0 keeps X and seat-1 O.
        self.assertEqual(match.state['seats'], ['seat-0', 'seat-1'])

    def test_open_with_the_composed_rng_draws_one_of_the_two_seats(self):
        dependencies = compose_match_dependencies()

        opened = self._open(dependencies.rng)

        match = Match.objects.get(public_id=opened.record.match_ref)
        self.assertIn(match.state['turn'], ('seat-0', 'seat-1'))


class TaTeTiDrawApiTests(APITestCase):
    """A full ta-te-ti draw driven end to end through the real REST path.

    The draw is ta-te-ti's novel ending (duelo has none), so it is exercised
    through the real action endpoint and the real ``DjangoMatchStore`` rather
    than a fake: the round-trip that matters is that a finished match with no
    winner persists ``winner_seat=''`` and reads back as ``None`` instead of
    failing on the model's non-null char column.
    """

    def setUp(self):
        self.room = Room.objects.create(game_id='ta-te-ti')
        self.first = self._participant('Guest One', 'sol')
        self.second = self._participant('Guest Two', 'luna')

    def _participant(self, display_name, marker):
        return Participant.objects.create(
            room=self.room,
            session_id=uuid.uuid4(),
            display_name=display_name,
            game_marker=marker,
            is_ready=True,
        )

    def _open(self):
        dependencies = compose_match_dependencies()
        # seat-0 opens the match, so the draw sequence below alternates from it.
        return open_match_for_room(
            room=self.room,
            reaping=dependencies.reaping,
            store=dependencies.store,
            registry=dependencies.registry,
            projector=dependencies.projector,
            rng=_FixedRng(('seat-0', 'seat-1')),
        )

    def test_a_full_board_without_a_line_persists_a_draw(self):
        opened = self._open()
        match_ref = opened.record.match_ref
        moves = (
            (self.first, '0'),
            (self.second, '4'),
            (self.first, '1'),
            (self.second, '2'),
            (self.first, '6'),
            (self.second, '3'),
            (self.first, '5'),
            (self.second, '7'),
            (self.first, '8'),
        )
        response = None
        for version, (participant, cell) in enumerate(moves):
            response = self.client.post(
                f'/api/matches/{match_ref}/actions/',
                {
                    'session_id': str(participant.session_id),
                    'action_name': 'pick',
                    'action_value': cell,
                    'expected_version': version,
                },
                format='json',
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        self.assertEqual(response.data['status'], 'finished')
        self.assertTrue(response.data['view']['finished'])
        self.assertIsNone(response.data['view']['winner'])

        stored = Match.objects.get(public_id=match_ref)
        self.assertEqual(stored.status, Match.Status.FINISHED)
        self.assertFalse(stored.winner_seat)

        resync = self.client.get(
            f'/api/matches/{match_ref}/',
            {'session_id': str(self.first.session_id)},
        )
        self.assertEqual(resync.status_code, status.HTTP_200_OK)
        self.assertTrue(resync.data['view']['finished'])
        self.assertIsNone(resync.data['view']['winner'])
