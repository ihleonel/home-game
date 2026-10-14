"""Pure-rule tests for the ``ta_te_ti`` (tic-tac-toe) game.

``SimpleTestCase`` only provides the runner so the rules can be exercised
without the database. Every test asserts the full observable effect of the
rule it covers: the resulting board, whose turn it is, and the resolved
outcome.
"""

import copy

from django.test import SimpleTestCase

from modules.games.contracts import Outcome
from modules.games.ta_te_ti import rules

LINES = (
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),
    (0, 3, 6),
    (1, 4, 7),
    (2, 5, 8),
    (0, 4, 8),
    (2, 4, 6),
)


class TaTeTiRulesTests(SimpleTestCase):
    def _open(self, first='seat-0'):
        return rules.initial_state(('seat-0', 'seat-1'), first)

    def _other(self, seat):
        return 'seat-1' if seat == 'seat-0' else 'seat-0'

    def _finish_line(self, line, winner='seat-0'):
        """Play ``winner`` to a three-in-a-row on ``line`` and return the state."""
        loser = self._other(winner)
        fillers = [cell for cell in range(9) if cell not in line]
        state = self._open(first=winner)
        state = rules.apply_pick(state, winner, str(line[0]))
        state = rules.apply_pick(state, loser, str(fillers[0]))
        state = rules.apply_pick(state, winner, str(line[1]))
        state = rules.apply_pick(state, loser, str(fillers[1]))
        return rules.apply_pick(state, winner, str(line[2]))

    def _draw_state(self):
        """Play the classic cat's game: every cell filled with no line."""
        state = self._open()
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
            state = rules.apply_pick(state, seat, str(cell))
        return state

    def test_initial_state_opens_an_empty_board_with_the_given_first_seat(self):
        """A fresh match has nine empty cells and the supplied seat on turn."""
        self.assertEqual(
            self._open(),
            {
                'board': [None] * 9,
                'seats': ('seat-0', 'seat-1'),
                'turn': 'seat-0',
                'winner': None,
                'winner_line': None,
                'finished': False,
                'ended_by_abandon': False,
                'abandoned_seat': None,
            },
        )

    def test_symbols_assign_x_to_the_first_seat_and_o_to_the_second(self):
        """Symbols follow seat index, never the cosmetic room marker."""
        state = self._open()
        self.assertEqual(rules.symbols(state), {'seat-0': 'X', 'seat-1': 'O'})

        # The opening seat is random, but symbols stay keyed by index order.
        flipped = self._open(first='seat-1')
        self.assertEqual(rules.symbols(flipped), {'seat-0': 'X', 'seat-1': 'O'})

    def test_apply_pick_places_the_seat_and_passes_the_turn(self):
        """A legal pick marks the cell and hands the turn to the other seat."""
        state = self._open()

        after = rules.apply_pick(state, 'seat-0', '4')

        self.assertEqual(
            after['board'],
            [None, None, None, None, 'seat-0', None, None, None, None],
        )
        self.assertEqual(after['turn'], 'seat-1')
        self.assertIsNone(after['winner'])
        self.assertIsNone(after['winner_line'])
        self.assertFalse(after['finished'])

    def test_apply_pick_returns_a_new_state_without_mutating_the_input(self):
        """Applying a pick is a pure transform of the previous state."""
        state = self._open()
        original = copy.deepcopy(state)

        new_state = rules.apply_pick(state, 'seat-0', '0')

        self.assertIsNot(new_state, state)
        self.assertEqual(state, original)

    def test_apply_pick_rejects_an_occupied_cell_and_leaves_state_untouched(self):
        """A taken cell is a loud error, never a silent overwrite."""
        state = rules.apply_pick(self._open(), 'seat-0', '4')
        before = copy.deepcopy(state)

        with self.assertRaises(ValueError):
            rules.apply_pick(state, 'seat-1', '4')

        self.assertEqual(state, before)
        self.assertEqual(state['board'][4], 'seat-0')
        self.assertEqual(state['turn'], 'seat-1')

    def test_apply_pick_rejects_an_out_of_range_or_non_numeric_cell(self):
        """A cell outside ``0..8`` or a non-number is rejected loudly."""
        state = self._open()
        before = copy.deepcopy(state)

        for value in ('9', '-1', 'banana', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                rules.apply_pick(state, 'seat-0', value)

        self.assertEqual(state, before)

    def test_apply_pick_rejects_a_seat_out_of_turn(self):
        """Only the seat on turn may pick; the other is a loud error."""
        state = self._open()
        before = copy.deepcopy(state)

        with self.assertRaises(ValueError):
            rules.apply_pick(state, 'seat-1', '0')

        self.assertEqual(state, before)

    def test_apply_pick_rejects_an_unknown_seat(self):
        """An unknown seat is a loud error instead of a phantom third seat."""
        state = self._open()
        before = copy.deepcopy(state)

        with self.assertRaises(ValueError):
            rules.apply_pick(state, 'seat-9', '0')

        self.assertEqual(state, before)

    def test_apply_pick_rejects_a_finished_match(self):
        """A finished match is frozen; picking again is a loud error."""
        state = self._finish_line((0, 1, 2))
        before = copy.deepcopy(state)

        with self.assertRaises(ValueError):
            rules.apply_pick(state, state['turn'], '5')

        self.assertEqual(state, before)

    def test_every_standard_line_is_a_win_for_either_seat(self):
        """Each of the eight lines wins and records that exact line."""
        for winner in ('seat-0', 'seat-1'):
            for line in LINES:
                with self.subTest(winner=winner, line=line):
                    state = self._finish_line(line, winner=winner)

                    self.assertTrue(rules.is_finished(state))
                    self.assertEqual(state['winner'], winner)
                    self.assertEqual(state['winner_line'], line)
                    self.assertIsNone(state['turn'])
                    self.assertEqual(
                        rules.outcome(state),
                        Outcome(winner_seat=winner, reason='three_in_a_row'),
                    )

    def test_full_board_without_a_line_is_a_draw(self):
        """A filled board with no line finishes with no winner."""
        state = self._draw_state()

        self.assertTrue(rules.is_finished(state))
        self.assertIsNone(state['winner'])
        self.assertIsNone(state['winner_line'])
        self.assertTrue(all(cell is not None for cell in state['board']))
        self.assertEqual(
            rules.outcome(state), Outcome(winner_seat=None, reason='draw')
        )

    def test_outcome_is_none_while_the_match_runs(self):
        """An unfinished match has no outcome yet."""
        self.assertIsNone(rules.outcome(self._open()))
        self.assertIsNone(rules.outcome(rules.apply_pick(self._open(), 'seat-0', '0')))

    def test_abandon_hands_the_match_to_the_seat_that_stayed(self):
        """Expelling a seat in a two-seat game gives the win to the other."""
        state = self._open()

        after = rules.abandon(state, 'seat-1')

        self.assertTrue(rules.is_finished(after))
        self.assertEqual(after['winner'], 'seat-0')
        self.assertEqual(after['abandoned_seat'], 'seat-1')
        self.assertTrue(after['ended_by_abandon'])
        self.assertIsNone(after['turn'])
        self.assertEqual(
            rules.outcome(after),
            Outcome(winner_seat='seat-0', reason='win_by_abandon'),
        )

    def test_abandon_rejects_an_unknown_seat_and_a_finished_match(self):
        """Abandonment traps unknown seats and repeat resolutions loudly."""
        with self.assertRaises(ValueError):
            rules.abandon(self._open(), 'seat-9')

        with self.assertRaises(ValueError):
            rules.abandon(self._finish_line((0, 1, 2)), 'seat-0')

    def test_abandon_does_not_mutate_the_input_state(self):
        """Abandonment is a pure transform of the previous state."""
        state = self._open()
        original = copy.deepcopy(state)

        rules.abandon(state, 'seat-1')

        self.assertEqual(state, original)
