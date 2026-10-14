"""Persistence-model tests for the match models of ``modules.games``.

These tests pin the datastore contract that the future runtime relies on: a
match owns a versioned state snapshot, actions are append-only, and the
database itself enforces at most one in-progress match per room and one seat
per index, seat id and participant.

The JSON round-trip test at the bottom is the important one: it proves the
``duelo`` rules are JSON-safe, which is why ``Match.state`` can be a Postgres
``jsonb`` column.
"""

import json
import uuid

from django.db import IntegrityError, transaction
from django.test import TestCase

from modules.games.contracts import Action, Seat
from modules.games.duelo import rules
from modules.games.duelo.game import DueloDefinition
from modules.games.models import Match, MatchAction, MatchSeat
from modules.rooms.models import Participant, Room


class MatchTestCase(TestCase):
    """Shared fixtures: one room with two participants."""

    def setUp(self):
        self.room = Room.objects.create(game_id='duelo')
        self.first = Participant.objects.create(
            room=self.room,
            session_id=uuid.uuid4(),
            display_name='Guest One',
            game_marker='blue-token',
        )
        self.second = Participant.objects.create(
            room=self.room,
            session_id=uuid.uuid4(),
            display_name='Guest Two',
            game_marker='red-token',
        )

    def create_match(self, room=None, **overrides):
        fields = {
            'room': room or self.room,
            'game_id': 'duelo',
            'version': 1,
            'state': {'round': 1},
        }
        fields.update(overrides)
        return Match.objects.create(**fields)


class MatchModelTests(MatchTestCase):
    def test_match_belongs_to_room_and_persists_its_snapshot(self):
        match = self.create_match()
        public_id = match.public_id

        match.refresh_from_db()

        self.assertEqual(match.room, self.room)
        self.assertEqual(match.game_id, 'duelo')
        self.assertEqual(match.status, Match.Status.IN_PROGRESS)
        self.assertEqual(match.version, 1)
        self.assertEqual(match.state, {'round': 1})
        self.assertEqual(match.winner_seat, '')
        self.assertIsNotNone(match.started_at)
        self.assertIsNone(match.finished_at)
        self.assertEqual(match.public_id, public_id)

    def test_public_id_is_unique_and_stable(self):
        first = self.create_match()
        other_room = Room.objects.create(game_id='duelo-second')
        second = self.create_match(room=other_room)

        self.assertNotEqual(first.public_id, second.public_id)

        first.refresh_from_db()
        self.assertEqual(first.public_id, Match.objects.get(pk=first.pk).public_id)

    def test_only_one_in_progress_match_is_allowed_per_room(self):
        first = self.create_match()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_match()

        first.status = Match.Status.FINISHED
        first.save(update_fields=('status', 'updated_at'))

        second = self.create_match()

        self.assertEqual(
            Match.objects.filter(status=Match.Status.IN_PROGRESS).count(), 1
        )
        self.assertEqual(
            set(Match.objects.values_list('pk', flat=True)), {first.pk, second.pk}
        )


class MatchSeatModelTests(MatchTestCase):
    def test_match_seat_ties_seat_identity_to_a_participant(self):
        match = self.create_match()
        seat = MatchSeat.objects.create(
            match=match,
            index=0,
            seat_id='seat-0',
            participant=self.first,
            badge='guante-rojo',
        )

        seat.refresh_from_db()

        self.assertEqual(seat.match, match)
        self.assertEqual(seat.index, 0)
        self.assertEqual(seat.seat_id, 'seat-0')
        self.assertEqual(seat.participant, self.first)
        self.assertEqual(seat.badge, 'guante-rojo')

    def test_match_seat_rejects_a_duplicate_index(self):
        match = self.create_match()
        MatchSeat.objects.create(
            match=match, index=0, seat_id='seat-0', participant=self.first
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchSeat.objects.create(
                    match=match, index=0, seat_id='seat-1', participant=self.second
                )

    def test_match_seat_rejects_a_duplicate_seat_id(self):
        match = self.create_match()
        MatchSeat.objects.create(
            match=match, index=0, seat_id='seat-0', participant=self.first
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchSeat.objects.create(
                    match=match, index=1, seat_id='seat-0', participant=self.second
                )

    def test_match_seat_rejects_a_duplicate_participant(self):
        match = self.create_match()
        MatchSeat.objects.create(
            match=match, index=0, seat_id='seat-0', participant=self.first
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchSeat.objects.create(
                    match=match, index=1, seat_id='seat-1', participant=self.first
                )


class MatchActionModelTests(MatchTestCase):
    def test_match_action_records_the_append_only_audit_entry(self):
        match = self.create_match()
        facts = [{'name': 'pick_recorded', 'seat': 'seat-0', 'detail': {}}]
        action = MatchAction.objects.create(
            match=match,
            sequence=0,
            seat_id='seat-0',
            action_name='pick',
            action_value='rock',
            version=1,
            facts=facts,
        )

        action.refresh_from_db()

        self.assertEqual(action.match, match)
        self.assertEqual(action.sequence, 0)
        self.assertEqual(action.seat_id, 'seat-0')
        self.assertEqual(action.action_name, 'pick')
        self.assertEqual(action.action_value, 'rock')
        self.assertEqual(action.version, 1)
        self.assertEqual(action.facts, facts)
        self.assertIsNotNone(action.created_at)

    def test_match_action_rejects_a_duplicate_sequence_within_a_match(self):
        match = self.create_match()
        MatchAction.objects.create(
            match=match,
            sequence=0,
            seat_id='seat-0',
            action_name='pick',
            action_value='rock',
            version=1,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchAction.objects.create(
                    match=match,
                    sequence=0,
                    seat_id='seat-1',
                    action_name='pick',
                    action_value='scissors',
                    version=1,
                )

    def test_match_action_sequence_is_scoped_to_its_match(self):
        first = self.create_match()
        other_room = Room.objects.create(game_id='duelo-second')
        second = self.create_match(room=other_room)

        MatchAction.objects.create(
            match=first,
            sequence=0,
            seat_id='seat-0',
            action_name='pick',
            action_value='rock',
            version=1,
        )
        action = MatchAction.objects.create(
            match=second,
            sequence=0,
            seat_id='seat-0',
            action_name='pick',
            action_value='paper',
            version=1,
        )

        self.assertEqual(action.sequence, 0)


class MatchCascadeTests(MatchTestCase):
    def test_deleting_room_cascades_to_matches_seats_and_actions(self):
        match = self.create_match()
        seat = MatchSeat.objects.create(
            match=match, index=0, seat_id='seat-0', participant=self.first
        )
        action = MatchAction.objects.create(
            match=match,
            sequence=0,
            seat_id='seat-0',
            action_name='pick',
            version=1,
        )

        self.room.delete()

        self.assertFalse(Match.objects.filter(pk=match.pk).exists())
        self.assertFalse(MatchSeat.objects.filter(pk=seat.pk).exists())
        self.assertFalse(MatchAction.objects.filter(pk=action.pk).exists())


class DueloJsonRoundTripTests(TestCase):
    """Pin that ``duelo`` state survives the JSON storage boundary.

    ``Match.state`` is a Postgres ``jsonb`` column: it does not preserve key
    order and it turns tuples into lists. The runtime therefore always reloads
    the state through JSON before feeding it back to the rules. If the rules
    ever depended on the in-memory tuple or dict identity, a match would behave
    correctly in a unit test and diverge only once it was persisted. This test
    drives a real mid-match ``duelo`` state through ``json.dumps``/``json.loads``
    and asserts the rules produce an equivalent round resolution and view, so it
    asserts the observable equivalence rather than the internal representation.
    """

    def setUp(self):
        self.definition = DueloDefinition()
        self.seats = (
            Seat(index=0, participant_ref=str(uuid.uuid4())),
            Seat(index=1, participant_ref=str(uuid.uuid4())),
        )

    def _mid_match_state(self):
        state = self.definition.start(self.seats, None)
        pick = Action(name='pick', value='rock')
        return self.definition.apply(state, 'seat-0', pick, None).state

    def test_json_reloaded_state_resolves_and_projects_like_the_in_memory_state(self):
        state = self._mid_match_state()
        reloaded = json.loads(json.dumps(state))

        expected_state = rules.apply_pick(state, 'seat-1', 'scissors')
        actual_state = rules.apply_pick(reloaded, 'seat-1', 'scissors')

        self.assertEqual(actual_state['picks'], expected_state['picks'])
        self.assertEqual(actual_state['scores'], expected_state['scores'])
        self.assertEqual(actual_state['reveal'], expected_state['reveal'])

        for seat in ('seat-0', 'seat-1', None):
            with self.subTest(seat=seat):
                self.assertEqual(
                    self.definition.view(actual_state, seat),
                    self.definition.view(expected_state, seat),
                )
