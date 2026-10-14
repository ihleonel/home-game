"""Runtime-contract tests for the ``ta_te_ti`` game definition.

The definition is stateless; these tests drive full match traces through the
framework-free contract and assert the frozen ``view`` shape (S6) plus the
loud-failure rule for a missing ``RandomSource`` (S4).
"""

import copy
import json

from django.test import SimpleTestCase

from modules.games.contracts import (
    Action,
    ActionSpec,
    Fact,
    Outcome,
    Seat,
    SeatOption,
)
from modules.games.ta_te_ti.game import TaTeTiDefinition


class StubRng:
    """Deterministic ``RandomSource`` that plays back a fixed order."""

    def __init__(self, order):
        self.order = list(order)
        self.shuffle_calls = []

    def shuffle(self, items):
        self.shuffle_calls.append(tuple(items))
        return list(self.order)

    def roll(self, sides):
        return 1


def _seats():
    return (
        Seat(index=0, participant_ref='11111111-1111-1111-1111-111111111111'),
        Seat(index=1, participant_ref='22222222-2222-2222-2222-222222222222'),
    )


class TaTeTiDefinitionTests(SimpleTestCase):
    def setUp(self):
        self.definition = TaTeTiDefinition()
        self.seats = _seats()

    def _start(self, first='seat-0'):
        # seat-0 opens unless the test asks for the other order.
        order = (first, 'seat-1' if first == 'seat-0' else 'seat-0')
        self.rng = StubRng(order)
        return self.definition.start(self.seats, self.rng)

    def _pick(self, state, seat, value):
        return self.definition.apply(
            state, seat, Action(name='pick', value=value), None
        )

    def _finish_line(self, line, winner='seat-0'):
        loser = 'seat-1' if winner == 'seat-0' else 'seat-0'
        fillers = [cell for cell in range(9) if cell not in line]
        state = self._start(first=winner)
        state = self._pick(state, winner, str(line[0])).state
        state = self._pick(state, loser, str(fillers[0])).state
        state = self._pick(state, winner, str(line[1])).state
        state = self._pick(state, loser, str(fillers[1])).state
        return self._pick(state, winner, str(line[2])).state

    def _draw_state(self):
        state = self._start()
        moves = (
            ('seat-0', 0),
            ('seat-1', 1),
            ('seat-0', 2),
            ('seat-1', 4),
            ('seat-0', 3),
            ('seat-1', 5),
            ('seat-0', 7),
            ('seat-1', 6),
            ('seat-0', 8),
        )
        for seat, cell in moves:
            state = self._pick(state, seat, str(cell)).state
        return state

    def test_metadata_matches_the_frozen_catalog_contract(self):
        """The catalog metadata pins the id, copy, bounds and cosmetic chips."""
        self.assertEqual(self.definition.game_id, 'ta-te-ti')
        self.assertEqual(self.definition.label, 'Ta-te-ti')
        self.assertEqual(
            self.definition.description, 'Formá una línea de tres y ganá la partida.'
        )
        self.assertEqual(self.definition.min_seats, 2)
        self.assertEqual(self.definition.max_seats, 2)
        self.assertEqual(
            self.definition.seat_options,
            (
                SeatOption(id='sol', label='Sol'),
                SeatOption(id='luna', label='Luna'),
                SeatOption(id='estrella', label='Estrella'),
            ),
        )

    def test_start_without_rng_fails_loudly(self):
        """No silent seat-0 default: a missing ``RandomSource`` raises."""
        with self.assertRaises(ValueError) as caught:
            self.definition.start(self.seats, None)

        self.assertIn('rng', str(caught.exception))

    def test_start_uses_the_random_source_for_the_opening_seat(self):
        """The opening seat comes from the injected ``RandomSource``."""
        state = self._start(first='seat-1')

        self.assertEqual(state['turn'], 'seat-1')
        self.assertEqual(self.rng.shuffle_calls, [('seat-0', 'seat-1')])

        other = self._start(first='seat-0')
        self.assertEqual(other['turn'], 'seat-0')

    def test_start_builds_the_initial_board(self):
        """A fresh match opens with an empty nine-cell board and no winner."""
        state = self._start()

        self.assertEqual(state['board'], [None] * 9)
        self.assertFalse(self.definition.is_finished(state))
        self.assertEqual(self.definition.active_seats(state), ('seat-0',))
        self.assertIsNone(self.definition.outcome(state))

    def test_active_seats_returns_the_seat_on_turn_then_empty_when_finished(self):
        """Exactly the seat on turn may act; a finished match has no actor."""
        state = self._start()
        self.assertEqual(self.definition.active_seats(state), ('seat-0',))

        state = self._pick(state, 'seat-0', '0').state
        self.assertEqual(self.definition.active_seats(state), ('seat-1',))

        state = self._finish_line((0, 1, 2))
        self.assertEqual(self.definition.active_seats(state), ())

    def test_legal_actions_offers_the_free_cells_to_the_seat_on_turn_only(self):
        """The active seat gets one ``pick`` action whose options are free cells."""
        state = self._start()

        self.assertEqual(
            self.definition.legal_actions(state, 'seat-0'),
            (
                ActionSpec(
                    name='pick',
                    options=tuple(str(cell) for cell in range(9)),
                    prompt='Elegí una celda.',
                ),
            ),
        )
        # Off turn, unknown seat and finished match all offer nothing.
        self.assertEqual(self.definition.legal_actions(state, 'seat-1'), ())
        self.assertEqual(self.definition.legal_actions(state, 'seat-9'), ())

        state = self._pick(state, 'seat-0', '4').state
        self.assertEqual(
            self.definition.legal_actions(state, 'seat-1')[0].options,
            ('0', '1', '2', '3', '5', '6', '7', '8'),
        )
        self.assertEqual(
            self.definition.legal_actions(self._finish_line((0, 1, 2)), 'seat-0'),
            (),
        )

    def test_a_legal_pick_marks_the_board_and_emits_a_fact(self):
        """Applying a pick records the cell and emits ``pick_recorded``."""
        state = self._start()

        transition = self._pick(state, 'seat-0', '4')

        self.assertEqual(transition.state['board'][4], 'seat-0')
        self.assertEqual(transition.state['turn'], 'seat-1')
        self.assertEqual(
            transition.facts,
            (Fact(name='pick_recorded', seat='seat-0', detail={'cell': 4}),),
        )

    def test_an_occupied_cell_is_rejected(self):
        """An occupied cell is never silently accepted."""
        state = self._pick(self._start(), 'seat-0', '4').state
        before = copy.deepcopy(state)

        with self.assertRaises(ValueError):
            self._pick(state, 'seat-1', '4')

        self.assertEqual(state, before)

    def test_a_winning_line_finishes_the_match_for_its_seat(self):
        """Three in a row sets the winner, the line and the finished flag."""
        state = self._finish_line((0, 4, 8), winner='seat-1')

        view = self.definition.view(state, None)
        self.assertTrue(view['finished'])
        self.assertEqual(view['winner'], 'seat-1')
        self.assertEqual(view['winner_line'], [0, 4, 8])
        self.assertIsNone(view['turn'])
        self.assertEqual(
            self.definition.outcome(state),
            Outcome(winner_seat='seat-1', reason='three_in_a_row'),
        )

    def test_a_full_board_without_a_line_produces_a_draw(self):
        """A cat's game finishes with ``finished`` true and no winner."""
        state = self._draw_state()

        view = self.definition.view(state, None)
        self.assertTrue(view['finished'])
        self.assertIsNone(view['winner'])
        self.assertIsNone(view['winner_line'])
        self.assertIsNone(view['turn'])
        self.assertEqual(
            self.definition.outcome(state), Outcome(winner_seat=None, reason='draw')
        )

    def test_abandon_awards_the_win_to_the_remaining_seat(self):
        """Expelling a seat hands the match to the seat that stayed."""
        transition = self.definition.abandon(self._start(), 'seat-1', None)

        self.assertTrue(self.definition.is_finished(transition.state))
        self.assertEqual(self.definition.active_seats(transition.state), ())
        self.assertEqual(
            self.definition.outcome(transition.state),
            Outcome(winner_seat='seat-0', reason='win_by_abandon'),
        )
        self.assertEqual(
            transition.facts,
            (
                Fact(name='seat_abandoned', seat='seat-1', detail={}),
                Fact(name='match_finished', detail={'winner': 'seat-0'}),
            ),
        )

    def test_abandon_rejects_an_unknown_seat_and_a_finished_match(self):
        """Abandonment traps unknown seats and repeat resolutions loudly."""
        with self.assertRaises(ValueError):
            self.definition.abandon(self._start(), 'seat-9', None)

        with self.assertRaises(ValueError):
            self.definition.abandon(self._finish_line((0, 1, 2)), 'seat-0', None)

    def test_abandon_does_not_mutate_the_input_state(self):
        """The definition delegates to a pure transform of the previous state."""
        state = self._start()
        original = copy.deepcopy(state)

        self.definition.abandon(state, 'seat-1', None)

        self.assertEqual(state, original)

    def test_view_shape_is_frozen_for_a_running_match(self):
        """Every public key is present, with ``turn`` reporting the actor."""
        state = self._start()

        view = self.definition.view(state, None)

        self.assertEqual(
            view,
            {
                'board': [None] * 9,
                'turn': 'seat-0',
                'symbols': {'seat-0': 'X', 'seat-1': 'O'},
                'winner_line': None,
                'winner': None,
                'finished': False,
                'ended_by_abandon': False,
            },
        )

    def test_seat_view_adds_you_while_spectator_view_does_not(self):
        """The board is public; ``you`` exists only for a real seat."""
        state = self._pick(self._start(), 'seat-0', '4').state

        seat_view = self.definition.view(state, 'seat-1')
        spectator = self.definition.view(state, None)

        self.assertEqual(seat_view['you'], 'seat-1')
        self.assertNotIn('you', spectator)
        for key in ('board', 'turn', 'symbols', 'winner_line', 'winner', 'finished'):
            with self.subTest(key=key):
                self.assertEqual(seat_view[key], spectator[key])
        # The board is public, so no seat view hides the other seat's mark.
        self.assertEqual(seat_view['board'][4], 'seat-0')

    def test_views_flag_ended_by_abandon_only_after_an_abandonment(self):
        """A snapshot alone must tell an abandonment finish from a normal one."""
        abandoned = self.definition.abandon(self._start(), 'seat-1', None).state
        normal = self._finish_line((0, 1, 2))

        for seat in ('seat-0', 'seat-1', None):
            with self.subTest(seat=seat, case='abandoned'):
                self.assertTrue(self.definition.view(abandoned, seat)['ended_by_abandon'])
            with self.subTest(seat=seat, case='normal'):
                self.assertFalse(self.definition.view(normal, seat)['ended_by_abandon'])
            with self.subTest(seat=seat, case='running'):
                self.assertFalse(
                    self.definition.view(self._start(), seat)['ended_by_abandon']
                )

    def test_view_is_json_serializable(self):
        """The frozen view must survive the JSON transport unchanged."""
        state = self._finish_line((0, 1, 2))

        for seat in ('seat-0', 'seat-1', None):
            with self.subTest(seat=seat):
                json.dumps(self.definition.view(state, seat))
