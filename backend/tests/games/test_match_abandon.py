"""Datastore tests for the interface-layer abandonment entry point (S2).

The entry point is the single translation from a room and a session to the
runtime use case that resolves the seat: it must resolve the room's running
match and the participant that occupies a seat in it, and it must be a no-op
for every ordinary miss instead of calling the use case with nothing to do.
"""

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from modules.games.duelo import rules
from modules.games.interfaces.match_abandon import (
    abandon_expired_seats,
    abandon_seat_for_session,
)
from modules.games.models import Match, MatchSeat
from modules.rooms.constants import RECONNECT_GRACE_SECONDS
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


class AbandonExpiredSeatsTests(TestCase):
    """The lazy sweep resolves every already-expired seat of a running match.

    A process restart in the middle of the grace window loses the in-process
    timer, so the read paths that already reap ask for the expired seats first.
    These tests drive the real entry point against real rows, so the sweep
    counts, the match resolution and the idempotence are all observed end to
    end.
    """

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

    def expire(self, participant, **changes):
        for field, value in changes.items():
            setattr(participant, field, value)
        participant.save(update_fields=(*changes, 'updated_at'))

    def assert_match_finished_by_abandonment(self):
        self.match.refresh_from_db()
        self.assertEqual(self.match.status, Match.Status.FINISHED)
        self.assertEqual(self.match.winner_seat, 'seat-0')
        self.assertEqual(self.match.state['abandoned_seat'], 'seat-1')

    def test_resolves_an_inactive_seat(self):
        self.expire(
            self.second, presence=Participant.Presence.INACTIVE
        )

        outcome = abandon_expired_seats()

        self.assertEqual(outcome.seats_resolved, 1)
        self.assert_match_finished_by_abandonment()

    def test_resolves_a_seat_whose_membership_was_already_removed(self):
        self.expire(self.second, left_at=timezone.now())

        outcome = abandon_expired_seats()

        self.assertEqual(outcome.seats_resolved, 1)
        self.assert_match_finished_by_abandonment()

    def test_resolves_a_reconnecting_seat_past_the_grace(self):
        self.expire(
            self.second,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=timezone.now()
            - timedelta(seconds=RECONNECT_GRACE_SECONDS + 1),
        )

        outcome = abandon_expired_seats()

        self.assertEqual(outcome.seats_resolved, 1)
        self.assert_match_finished_by_abandonment()

    def test_leaves_an_online_seat_alone(self):
        outcome = abandon_expired_seats()

        self.assertEqual(outcome.seats_resolved, 0)
        self.match.refresh_from_db()
        self.assertEqual(self.match.status, Match.Status.IN_PROGRESS)
        self.assertEqual(self.match.winner_seat, '')

    def test_leaves_a_reconnecting_seat_inside_the_grace_alone(self):
        self.expire(
            self.second,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=timezone.now(),
        )

        outcome = abandon_expired_seats()

        self.assertEqual(outcome.seats_resolved, 0)
        self.match.refresh_from_db()
        self.assertEqual(self.match.status, Match.Status.IN_PROGRESS)

    def test_resolves_a_never_socketed_seat_once_its_window_expires(self):
        # A membership posted over REST whose socket never opened carries no
        # ``disconnected_at`` to measure, so its window is its last write --
        # the same rule the membership reaper already applies to an offline
        # row. Without it the seat has no exit at all: it cannot leave while
        # it is ready, the reaper skips a busy room, and the vote never
        # targets an offline row, so the match waits forever for somebody who
        # is not there.
        self.expire(self.second, presence=Participant.Presence.OFFLINE)
        Participant.objects.filter(pk=self.second.pk).update(
            updated_at=timezone.now()
            - timedelta(seconds=RECONNECT_GRACE_SECONDS + 1)
        )

        outcome = abandon_expired_seats()

        self.assertEqual(outcome.seats_resolved, 1)
        self.assert_match_finished_by_abandonment()

    def test_leaves_a_fresh_never_socketed_seat_alone(self):
        # A row written moments ago keeps its whole window: the arrival may
        # still be opening its socket, which is the race the window bounds.
        self.expire(self.second, presence=Participant.Presence.OFFLINE)

        outcome = abandon_expired_seats()

        self.assertEqual(outcome.seats_resolved, 0)
        self.match.refresh_from_db()
        self.assertEqual(self.match.status, Match.Status.IN_PROGRESS)

    def test_ignores_a_room_without_an_in_progress_match(self):
        self.match.status = Match.Status.FINISHED
        self.match.save(update_fields=('status', 'updated_at'))
        self.expire(
            self.second, presence=Participant.Presence.INACTIVE
        )

        outcome = abandon_expired_seats()

        self.assertEqual(outcome.seats_resolved, 0)

    def test_a_second_sweep_resolves_nothing_again(self):
        self.expire(
            self.second, presence=Participant.Presence.INACTIVE
        )

        first = abandon_expired_seats()
        second = abandon_expired_seats()

        self.assertEqual(first.seats_resolved, 1)
        self.assertEqual(second.seats_resolved, 0)
        self.assert_match_finished_by_abandonment()

    def test_scopes_the_sweep_to_the_given_room(self):
        other_room = Room.objects.create(game_id='otro-juego')
        other_first = Participant.objects.create(
            room=other_room,
            session_id=uuid.uuid4(),
            display_name='Other One',
            game_marker='guante-verde',
            presence=Participant.Presence.ONLINE,
        )
        other_second = Participant.objects.create(
            room=other_room,
            session_id=uuid.uuid4(),
            display_name='Other Two',
            game_marker='guante-azul',
            presence=Participant.Presence.INACTIVE,
        )
        other_match = Match.objects.create(
            room=other_room,
            game_id='duelo',
            status=Match.Status.IN_PROGRESS,
            state=rules.initial_state(['seat-0', 'seat-1']),
        )
        MatchSeat.objects.create(
            match=other_match,
            index=0,
            seat_id='seat-0',
            participant=other_first,
        )
        MatchSeat.objects.create(
            match=other_match,
            index=1,
            seat_id='seat-1',
            participant=other_second,
        )
        self.expire(
            self.second, presence=Participant.Presence.INACTIVE
        )

        scoped = abandon_expired_seats(room_id=self.room.id)

        self.assertEqual(scoped.seats_resolved, 1)
        self.assert_match_finished_by_abandonment()
        other_match.refresh_from_db()
        self.assertEqual(other_match.status, Match.Status.IN_PROGRESS)

        # The default sweep still covers every room. Both matches are already
        # resolved by then, so it reports no further work.
        self.assertEqual(abandon_expired_seats().seats_resolved, 1)
        other_match.refresh_from_db()
        self.assertEqual(other_match.status, Match.Status.FINISHED)
