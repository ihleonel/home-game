"""Datastore tests for the interface-layer abandonment entry point (S2).

The entry point is the single translation from a room and a session to the
runtime use case that resolves the seat: it must resolve the room's running
match and the participant that occupies a seat in it, and it must be a no-op
for every ordinary miss instead of calling the use case with nothing to do.
"""

import uuid
from unittest.mock import patch

from django.test import TestCase

from modules.games.duelo import rules
from modules.games.interfaces.match_abandon import abandon_seat_for_session
from modules.games.models import Match, MatchSeat
from modules.rooms.models import Participant, Room

USE_CASE = 'modules.games.interfaces.match_abandon.abandon_seat'


class AbandonSeatForSessionTests(TestCase):
    def setUp(self):
        self.room = Room.objects.create(game_id='duelo')
        self.first = Participant.objects.create(
            room=self.room,
            session_id=uuid.uuid4(),
            display_name='Guest One',
            game_marker='guante-rojo',
            presence=Participant.Presence.ONLINE,
        )
        self.second = Participant.objects.create(
            room=self.room,
            session_id=uuid.uuid4(),
            display_name='Guest Two',
            game_marker='guante-azul',
            presence=Participant.Presence.ONLINE,
        )
        self.match = Match.objects.create(
            room=self.room,
            game_id='duelo',
            status=Match.Status.IN_PROGRESS,
            state=rules.initial_state(['seat-0', 'seat-1']),
        )
        MatchSeat.objects.create(
            match=self.match, index=0, seat_id='seat-0', participant=self.first
        )
        MatchSeat.objects.create(
            match=self.match,
            index=1,
            seat_id='seat-1',
            participant=self.second,
        )

    def test_resolves_the_room_match_and_forwards_both_references(self):
        resolved = object()

        with patch(USE_CASE, return_value=resolved) as use_case:
            result = abandon_seat_for_session(
                self.room.id, self.second.session_id
            )

        self.assertIs(result, resolved)
        use_case.assert_called_once()
        kwargs = use_case.call_args.kwargs
        self.assertEqual(kwargs['match_ref'], str(self.match.public_id))
        self.assertEqual(kwargs['participant_ref'], str(self.second.public_id))
        for name in ('store', 'registry', 'projector', 'lifecycle'):
            self.assertIn(name, kwargs)

    def test_without_an_in_progress_match_it_is_a_no_op(self):
        self.match.status = Match.Status.FINISHED
        self.match.save(update_fields=('status', 'updated_at'))

        with patch(USE_CASE) as use_case:
            result = abandon_seat_for_session(
                self.room.id, self.second.session_id
            )

        self.assertIsNone(result)
        use_case.assert_not_called()

    def test_a_participant_without_a_seat_is_a_no_op(self):
        spectator = Participant.objects.create(
            room=self.room,
            session_id=uuid.uuid4(),
            display_name='Guest Three',
            game_marker='guante-verde',
            presence=Participant.Presence.ONLINE,
        )

        with patch(USE_CASE) as use_case:
            result = abandon_seat_for_session(
                self.room.id, spectator.session_id
            )

        self.assertIsNone(result)
        use_case.assert_not_called()

    def test_a_session_without_a_participant_is_a_no_op(self):
        with patch(USE_CASE) as use_case:
            result = abandon_seat_for_session(self.room.id, uuid.uuid4())

        self.assertIsNone(result)
        use_case.assert_not_called()
