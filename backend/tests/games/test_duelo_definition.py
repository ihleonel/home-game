"""Runtime-contract tests for the ``duelo`` game definition.

The definition is stateless; these tests drive full match traces through the
framework-free contract and assert the privacy guarantees of emitted facts and
seat views.
"""

import json

from django.test import SimpleTestCase

from modules.games.contracts import Action, ActionSpec, Fact, Seat, SeatOption
from modules.games.duelo.game import DueloDefinition


def _seats():
    return (
        Seat(index=0, participant_ref='11111111-1111-1111-1111-111111111111'),
        Seat(index=1, participant_ref='22222222-2222-2222-2222-222222222222'),
    )


class DueloDefinitionTests(SimpleTestCase):
    def setUp(self):
        self.definition = DueloDefinition()
        self.seats = _seats()

    def _pick(self, state, seat, value):
        return self.definition.apply(state, seat, Action(name='pick', value=value), None)

    def _finished_state(self):
        """Play a 2-0 match for seat-0 and return the final state."""
        state = self.definition.start(self.seats, None)
        state = self._pick(state, 'seat-0', 'rock').state
        state = self._pick(state, 'seat-1', 'scissors').state
        state = self._pick(state, 'seat-0', 'paper').state
        return self._pick(state, 'seat-1', 'rock').state

    def test_metadata_describes_an_exactly_two_seat_game(self):
        """Catalog metadata pins the id, seat bounds and cosmetic badges."""
        self.assertEqual(self.definition.game_id, 'duelo')
        self.assertEqual(self.definition.min_seats, 2)
        self.assertEqual(self.definition.max_seats, 2)
        self.assertEqual(
            self.definition.seat_options,
            (
                SeatOption(id='guante-rojo', label='Guante rojo'),
                SeatOption(id='guante-azul', label='Guante azul'),
                SeatOption(id='guante-verde', label='Guante verde'),
            ),
        )

    def test_start_builds_the_initial_state_for_two_seats(self):
        """start maps seat indexes to seat ids and opens round one."""
        state = self.definition.start(self.seats, None)

        self.assertEqual(
            state,
            {
                'round': 1,
                'scores': {'seat-0': 0, 'seat-1': 0},
                'picks': {'seat-0': None, 'seat-1': None},
                'reveal': None,
                'winner': None,
                'history': (),
            },
        )

    def test_active_seats_track_who_still_owes_a_pick(self):
        """Both seats act first, then only the unpicked one, then both again."""
        state = self.definition.start(self.seats, None)
        self.assertEqual(self.definition.active_seats(state), ('seat-0', 'seat-1'))

        state = self._pick(state, 'seat-0', 'rock').state
        self.assertEqual(self.definition.active_seats(state), ('seat-1',))

        state = self._pick(state, 'seat-1', 'scissors').state
        self.assertEqual(self.definition.active_seats(state), ('seat-0', 'seat-1'))

        self.assertEqual(self.definition.active_seats(self._finished_state()), ())

    def test_legal_actions_gate_the_pick_for_the_right_seats(self):
        """Only an unpicked seat of an unfinished match may pick."""
        state = self.definition.start(self.seats, None)
        pick = (
            ActionSpec(
                name='pick', options=('rock', 'paper', 'scissors'), prompt='Elegí tu jugada.'
            ),
        )
        self.assertEqual(self.definition.legal_actions(state, 'seat-0'), pick)

        picked = self._pick(state, 'seat-0', 'rock').state
        self.assertEqual(self.definition.legal_actions(picked, 'seat-0'), ())
        self.assertEqual(self.definition.legal_actions(picked, 'seat-9'), ())
        self.assertEqual(self.definition.legal_actions(self._finished_state(), 'seat-0'), ())

    def test_pick_fact_and_opponent_view_never_leak_the_pick(self):
        """The central privacy assertion: a hidden pick stays hidden."""
        state = self.definition.start(self.seats, None)

        transition = self._pick(state, 'seat-0', 'rock')

        self.assertEqual(
            transition.facts,
            (Fact(name='pick_recorded', seat='seat-0', detail={}),),
        )
        self.assertNotIn('rock', json.dumps(self.definition.view(transition.state, 'seat-1')))
        self.assertNotIn('rock', json.dumps(self.definition.view(transition.state, None)))

    def test_seat_view_tracks_own_pick_and_opponent_progress(self):
        """A seat sees its own pick but only a boolean about the opponent."""
        state = self.definition.start(self.seats, None)
        before = self.definition.view(state, 'seat-0')
        self.assertEqual(before['you'], 'seat-0')
        self.assertIsNone(before['your_pick'])
        self.assertFalse(before['opponent_has_picked'])

        transition = self._pick(state, 'seat-0', 'rock')

        after = self.definition.view(transition.state, 'seat-0')
        self.assertEqual(after['your_pick'], 'rock')
        self.assertFalse(after['opponent_has_picked'])

        opponent = self.definition.view(transition.state, 'seat-1')
        self.assertIsNone(opponent['your_pick'])
        self.assertTrue(opponent['opponent_has_picked'])

    def test_resolved_round_is_visible_to_both_seats_and_spectators(self):
        """Once the round resolves, the reveal is public to everyone."""
        state = self.definition.start(self.seats, None)
        state = self._pick(state, 'seat-0', 'rock').state
        state = self._pick(state, 'seat-1', 'scissors').state

        expected_reveal = {
            'round': 1,
            'picks': {'seat-0': 'rock', 'seat-1': 'scissors'},
            'winner': 'seat-0',
        }
        for seat in ('seat-0', 'seat-1', None):
            with self.subTest(seat=seat):
                self.assertEqual(self.definition.view(state, seat)['reveal'], expected_reveal)

    def test_full_trace_to_two_zero_finishes_the_match(self):
        """A 2-0 trace closes the match and emits the finishing fact."""
        state = self.definition.start(self.seats, None)
        state = self._pick(state, 'seat-0', 'rock').state
        state = self._pick(state, 'seat-1', 'scissors').state
        state = self._pick(state, 'seat-0', 'paper').state
        final = self._pick(state, 'seat-1', 'rock')

        self.assertTrue(self.definition.is_finished(final.state))
        self.assertEqual(self.definition.active_seats(final.state), ())
        self.assertEqual(
            final.facts,
            (
                Fact(name='pick_recorded', seat='seat-1', detail={}),
                Fact(
                    name='round_resolved',
                    detail={
                        'round': 2,
                        'picks': {'seat-0': 'paper', 'seat-1': 'rock'},
                        'winner': 'seat-0',
                    },
                ),
                Fact(name='match_finished', detail={'winner': 'seat-0'}),
            ),
        )
        outcome = self.definition.outcome(final.state)
        self.assertEqual(outcome.winner_seat, 'seat-0')

    def test_legal_actions_and_apply_agree_for_a_seat_that_already_picked(self):
        """``legal_actions`` and ``apply`` must agree on an already-picked seat.

        ``legal_actions`` returns ``()`` for a seat that already picked, so
        ``apply`` must reject that same call instead of silently overwriting
        the recorded commitment. This test pins the agreement between the two
        methods for that seat.
        """
        state = self.definition.start(self.seats, None)
        state = self._pick(state, 'seat-0', 'rock').state

        self.assertEqual(self.definition.legal_actions(state, 'seat-0'), ())
        with self.assertRaises(ValueError):
            self._pick(state, 'seat-0', 'paper')
        self.assertEqual(state['picks']['seat-0'], 'rock')

    def test_apply_rejects_an_illegal_pick_value(self):
        """The definition must not shield callers from the rules pick guard."""
        state = self.definition.start(self.seats, None)

        with self.assertRaises(ValueError):
            self._pick(state, 'seat-0', 'banana')

    def test_apply_rejects_an_unknown_seat(self):
        """The definition must not shield callers from the rules seat guard."""
        state = self.definition.start(self.seats, None)

        with self.assertRaises(ValueError):
            self.definition.apply(
                state, 'seat-9', Action(name='pick', value='rock'), None
            )

    def test_apply_on_a_finished_match_propagates_the_rules_guard(self):
        """The definition must not shield callers from the finished-match trap."""
        final = self._finished_state()

        with self.assertRaises(ValueError):
            self._pick(final, 'seat-0', 'rock')
