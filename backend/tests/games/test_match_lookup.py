"""Datastore tests for the interface-layer seat subscription resolver.

The resolver is the read side of the per-seat projection (FRG-05C): a socket
must be handed only its own seat's view, and an ordinary subscription request
that simply has no match must resolve to ``None`` instead of raising. The
suite runs against real Postgres because it reads the persisted match and the
seat bindings through plain ORM queries.
"""

import json
import uuid

from django.test import TestCase

from modules.games.duelo import rules
from modules.games.interfaces.match_lookup import resolve_seat_subscription
from modules.games.models import Match, MatchSeat
from modules.games.runtime.infrastructure.channel_projector import (
    match_public_group_name,
    match_seat_group_name,
)
from modules.rooms.models import Participant, Room


class MatchLookupTestCase(TestCase):
    """Shared fixture: one room with two participants and a match factory."""

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

    def create_match(
        self,
        *,
        room=None,
        game_id='duelo',
        status=Match.Status.IN_PROGRESS,
        state=None,
        with_seats=True,
    ):
        match = Match.objects.create(
            room=room if room is not None else self.room,
            game_id=game_id,
            status=status,
            state=(
                state
                if state is not None
                else rules.initial_state(['seat-0', 'seat-1'])
            ),
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


class NoSubscriptionTests(MatchLookupTestCase):
    def test_room_without_a_match_returns_none(self):
        self.assertIsNone(
            resolve_seat_subscription(self.room.id, self.first.session_id)
        )

    def test_finished_match_returns_none(self):
        match = self.create_match(status=Match.Status.FINISHED)

        self.assertIsNone(
            resolve_seat_subscription(
                self.room.id, self.first.session_id, str(match.public_id)
            )
        )

    def test_match_that_belongs_to_another_room_returns_none(self):
        other_room = Room.objects.create(game_id='cloud-couriers')
        other_participant = Participant.objects.create(
            room=other_room,
            session_id=self.first.session_id,
            display_name='Courier One',
            game_marker='wind-kite',
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
            participant=other_participant,
        )

        self.assertIsNone(
            resolve_seat_subscription(
                self.room.id, self.first.session_id, str(other_match.public_id)
            )
        )

    def test_session_without_a_participant_returns_none(self):
        self.create_match()

        self.assertIsNone(
            resolve_seat_subscription(self.room.id, uuid.uuid4())
        )

    def test_unknown_game_id_returns_none(self):
        match = self.create_match(game_id='mystery-game')

        self.assertIsNone(
            resolve_seat_subscription(
                self.room.id, self.first.session_id, str(match.public_id)
            )
        )


class OwnSeatSubscriptionTests(MatchLookupTestCase):
    def test_valid_seat_returns_its_own_view_and_projector_groups(self):
        # Seat 0 has committed to 'rock'; seat 1 must receive only its own view,
        # which never contains the opponent's pending pick.
        state = rules.apply_pick(
            rules.initial_state(['seat-0', 'seat-1']), 'seat-0', 'rock'
        )
        match = self.create_match(state=state)
        match_ref = str(match.public_id)

        subscription = resolve_seat_subscription(
            self.room.id, self.second.session_id
        )

        self.assertIsNotNone(subscription)
        self.assertEqual(subscription.match_ref, match_ref)
        self.assertEqual(subscription.seat_index, 1)
        self.assertEqual(
            subscription.group, match_seat_group_name(match_ref, 1)
        )
        self.assertNotEqual(
            subscription.group, match_public_group_name(match_ref)
        )
        self.assertEqual(subscription.view['you'], 'seat-1')
        self.assertIsNone(subscription.view['your_pick'])
        self.assertTrue(subscription.view['opponent_has_picked'])
        self.assertNotIn('rock', json.dumps(subscription.view))

    def test_explicit_match_ref_resolves_the_same_own_seat_view(self):
        match = self.create_match()
        match_ref = str(match.public_id)

        subscription = resolve_seat_subscription(
            self.room.id, self.first.session_id, match_ref
        )

        self.assertIsNotNone(subscription)
        self.assertEqual(subscription.match_ref, match_ref)
        self.assertEqual(subscription.seat_index, 0)
        self.assertEqual(subscription.view['you'], 'seat-0')
        self.assertEqual(
            subscription.group, match_seat_group_name(match_ref, 0)
        )


class SpectatorSubscriptionTests(MatchLookupTestCase):
    def test_participant_without_a_seat_is_a_spectator_of_the_public_view(self):
        # Seat 0 has committed to 'rock'. Only the seat that committed may see
        # that value; the spectator's public view must not carry it.
        state = rules.apply_pick(
            rules.initial_state(['seat-0', 'seat-1']), 'seat-0', 'rock'
        )
        match = self.create_match(state=state, with_seats=False)
        MatchSeat.objects.create(
            match=match,
            index=0,
            seat_id='seat-0',
            participant=self.first,
        )
        match_ref = str(match.public_id)

        subscription = resolve_seat_subscription(
            self.room.id, self.second.session_id
        )

        self.assertIsNotNone(subscription)
        self.assertEqual(subscription.match_ref, match_ref)
        self.assertIsNone(subscription.seat_index)
        self.assertEqual(
            subscription.group, match_public_group_name(match_ref)
        )
        self.assertNotEqual(
            subscription.group, match_seat_group_name(match_ref, 0)
        )
        self.assertNotIn('you', subscription.view)
        self.assertNotIn('your_pick', subscription.view)
        self.assertNotIn('rock', json.dumps(subscription.view))


class CompositionRegistryTests(TestCase):
    def test_composition_exposes_the_single_registry_the_resolver_uses(self):
        from modules.games.composition import GAME_REGISTRY
        from modules.games.duelo.game import DueloDefinition
        from modules.games.interfaces import match_lookup

        definition = GAME_REGISTRY.get('duelo')
        self.assertIsInstance(definition, DueloDefinition)
        self.assertEqual(definition.game_id, 'duelo')
        self.assertIs(match_lookup.GAME_REGISTRY, GAME_REGISTRY)
