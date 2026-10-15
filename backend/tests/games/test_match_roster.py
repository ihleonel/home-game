"""Datastore tests for the public per-seat identity projection (S1).

The projection gives every seat of a match a public identity: the seated
participant's display name and marker, plus the marker label resolved
centrally from the game's own ``seat_options`` catalog via ``GAME_REGISTRY``.
The list is public -- it carries no pick and no other hidden value -- so it is
identical for a seat and for a spectator. The suite runs against real Postgres
because it reads the persisted match, its seats and the participants behind
them through plain ORM queries.
"""

import uuid

from django.test import TestCase

from modules.games.duelo import rules
from modules.games.interfaces.match_roster import resolve_match_roster
from modules.games.models import Match, MatchSeat
from modules.rooms.models import Participant, Room


class MatchRosterTestCase(TestCase):
    """Shared fixture: one ``duelo`` room with two seated participants."""

    def setUp(self):
        self.room = Room.objects.create(game_id='duelo')
        self.first = Participant.objects.create(
            room=self.room,
            session_id=uuid.uuid4(),
            display_name='Guest One',
            game_marker='guante-rojo',
        )
        self.second = Participant.objects.create(
            room=self.room,
            session_id=uuid.uuid4(),
            display_name='Guest Two',
            game_marker='guante-azul',
        )

    def create_match(self, *, game_id='duelo', with_seats=True):
        match = Match.objects.create(
            room=self.room,
            game_id=game_id,
            status=Match.Status.IN_PROGRESS,
            state=rules.initial_state(['seat-0', 'seat-1']),
        )
        if with_seats:
            MatchSeat.objects.create(
                match=match,
                index=0,
                seat_id='seat-0',
                participant=self.first,
            )
            MatchSeat.objects.create(
                match=match,
                index=1,
                seat_id='seat-1',
                participant=self.second,
            )
        return match


class ResolveMatchRosterTests(MatchRosterTestCase):
    def test_each_seat_carries_its_name_and_centrally_resolved_marker_label(self):
        match = self.create_match()

        roster = resolve_match_roster(match)

        # The exact dicts pin the public shape: five keys and no hidden value.
        self.assertEqual(
            roster,
            (
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
            ),
        )

    def test_entries_are_ordered_by_index_ascending(self):
        # Insert seat 1 before seat 0, so primary-key insertion order cannot
        # accidentally satisfy the required ``index`` order.
        match = Match.objects.create(
            room=self.room,
            game_id='duelo',
            status=Match.Status.IN_PROGRESS,
            state=rules.initial_state(['seat-0', 'seat-1']),
        )
        MatchSeat.objects.create(
            match=match, index=1, seat_id='seat-1', participant=self.second
        )
        MatchSeat.objects.create(
            match=match, index=0, seat_id='seat-0', participant=self.first
        )

        roster = resolve_match_roster(match)

        self.assertEqual([entry['index'] for entry in roster], [0, 1])
        self.assertEqual(
            [entry['seat_id'] for entry in roster], ['seat-0', 'seat-1']
        )

    def test_an_unknown_marker_falls_back_to_the_raw_marker_id(self):
        self.second.game_marker = 'guante-desconocido'
        self.second.save(update_fields=('game_marker', 'updated_at'))
        match = self.create_match()

        roster = resolve_match_roster(match)

        self.assertEqual(roster[1]['game_marker'], 'guante-desconocido')
        self.assertEqual(
            roster[1]['game_marker_label'], 'guante-desconocido'
        )

    def test_an_unknown_game_falls_back_to_the_raw_marker_ids(self):
        match = self.create_match(game_id='mystery-game')

        roster = resolve_match_roster(match)

        self.assertEqual(
            [entry['game_marker_label'] for entry in roster],
            ['guante-rojo', 'guante-azul'],
        )
