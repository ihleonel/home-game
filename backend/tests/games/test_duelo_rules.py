"""Pure-rule tests for the ``duelo`` (rock-paper-scissors) game.

These tests are deliberately Django-free in spirit: ``SimpleTestCase`` only
provides the runner so the rules can be exercised without the database.
"""

import copy

from django.test import SimpleTestCase

from modules.games.duelo import rules


# The full 3x3 resolution matrix spelled out explicitly. Each row is
# ``(first_pick, second_pick, expected)`` where ``expected`` is ``'first'``,
# ``'second'``, or ``None`` for a draw. The table is intentionally literal so
# a change to ``BEATS`` alone cannot rewrite the expected behaviour.
_RESOLVE_MATRIX = (
    ('rock', 'rock', None),
    ('rock', 'paper', 'second'),
    ('rock', 'scissors', 'first'),
    ('paper', 'rock', 'first'),
    ('paper', 'paper', None),
    ('paper', 'scissors', 'second'),
    ('scissors', 'rock', 'second'),
    ('scissors', 'paper', 'first'),
    ('scissors', 'scissors', None),
)


class DueloRulesTests(SimpleTestCase):
    def _open_match(self):
        return rules.initial_state(('seat-0', 'seat-1'))

    def _resolve_round(self, state, first_pick, second_pick):
        state = rules.apply_pick(state, 'seat-0', first_pick)
        return rules.apply_pick(state, 'seat-1', second_pick)

    def test_resolve_covers_the_full_three_by_three_matrix(self):
        """Every ordered pick pair resolves exactly as the explicit table says."""
        for first_pick, second_pick, expected in _RESOLVE_MATRIX:
            with self.subTest(first=first_pick, second=second_pick):
                self.assertEqual(rules.resolve(first_pick, second_pick), expected)

    def test_initial_state_shape_matches_the_contract(self):
        """A fresh match opens at round one with empty picks and no winner."""
        self.assertEqual(
            self._open_match(),
            {
                'round': 1,
                'scores': {'seat-0': 0, 'seat-1': 0},
                'picks': {'seat-0': None, 'seat-1': None},
                'reveal': None,
                'winner': None,
                'history': (),
            },
        )

    def test_apply_pick_returns_a_new_state_without_mutating_the_input(self):
        """Applying a pick is a pure transform of the previous state."""
        state = self._open_match()
        original = copy.deepcopy(state)

        new_state = rules.apply_pick(state, 'seat-0', 'rock')

        self.assertIsNot(new_state, state)
        self.assertEqual(state, original)

    def test_single_pick_records_only_the_pick(self):
        """One pick is recorded while round, scores, reveal and history wait."""
        state = self._open_match()

        after = rules.apply_pick(state, 'seat-0', 'rock')

        self.assertEqual(after['picks'], {'seat-0': 'rock', 'seat-1': None})
        self.assertIsNone(after['reveal'])
        self.assertEqual(after['round'], state['round'])
        self.assertEqual(after['scores'], state['scores'])
        self.assertEqual(after['history'], ())

    def test_decided_round_scores_the_winner_and_advances_the_round(self):
        """A decisive round moves one point, records history and resets picks."""
        state = self._resolve_round(self._open_match(), 'rock', 'scissors')

        self.assertEqual(state['scores'], {'seat-0': 1, 'seat-1': 0})
        self.assertEqual(
            state['reveal'],
            {
                'round': 1,
                'picks': {'seat-0': 'rock', 'seat-1': 'scissors'},
                'winner': 'seat-0',
            },
        )
        self.assertEqual(state['history'], (state['reveal'],))
        self.assertEqual(state['round'], 2)
        self.assertEqual(state['picks'], {'seat-0': None, 'seat-1': None})

    def test_draw_increments_the_round_without_scoring(self):
        """A draw changes neither score and reveals a round with no winner."""
        state = self._resolve_round(self._open_match(), 'paper', 'paper')

        self.assertEqual(state['scores'], {'seat-0': 0, 'seat-1': 0})
        self.assertEqual(state['round'], 2)
        self.assertEqual(len(state['history']), 1)
        self.assertEqual(state['reveal']['winner'], None)
        self.assertEqual(state['picks'], {'seat-0': None, 'seat-1': None})

    def test_winner_stays_none_until_a_seat_reaches_two_wins(self):
        """One win is not enough; the second win ends the match."""
        state = self._resolve_round(self._open_match(), 'rock', 'scissors')

        self.assertEqual(state['scores']['seat-0'], 1)
        self.assertIsNone(rules.winner(state))
        self.assertFalse(rules.is_finished(state))

        state = self._resolve_round(state, 'paper', 'rock')

        self.assertEqual(state['scores']['seat-0'], 2)
        self.assertEqual(rules.winner(state), 'seat-0')
        self.assertTrue(rules.is_finished(state))

    def test_apply_pick_on_a_finished_match_raises_and_leaves_it_untouched(self):
        """Re-resolving a finished match is a loud programming error, not a no-op."""
        state = self._resolve_round(self._open_match(), 'rock', 'scissors')
        state = self._resolve_round(state, 'paper', 'rock')
        self.assertTrue(rules.is_finished(state))
        before = copy.deepcopy(state)

        with self.assertRaises(ValueError):
            rules.apply_pick(state, 'seat-0', 'rock')

        self.assertEqual(state['scores'], before['scores'])
        self.assertEqual(state['history'], before['history'])
        self.assertEqual(state['reveal'], before['reveal'])
        self.assertEqual(state['winner'], before['winner'])
        self.assertEqual(state['picks'], before['picks'])

    def test_apply_pick_rejects_an_unknown_seat_and_leaves_state_untouched(self):
        """An unknown seat is a loud error, not a silent third-key corruption.

        Accepting ``seat-9`` would add a third key to ``picks`` while ``scores``
        still held two, and the corruption only surfaced later as a
        ``ValueError: too many values to unpack`` from the reveal step.
        """
        state = self._open_match()
        before = copy.deepcopy(state)

        with self.assertRaises(ValueError):
            rules.apply_pick(state, 'seat-9', 'rock')

        self.assertEqual(state, before)
        self.assertEqual(set(state['picks']), {'seat-0', 'seat-1'})

    def test_apply_pick_rejects_an_illegal_value_and_leaves_state_untouched(self):
        """An illegal pick is a loud error, not a silent state corruption."""
        state = self._open_match()
        before = copy.deepcopy(state)

        with self.assertRaises(ValueError):
            rules.apply_pick(state, 'seat-0', 'banana')

        self.assertEqual(state['picks'], before['picks'])
        self.assertEqual(state['scores'], before['scores'])
        self.assertEqual(state['reveal'], before['reveal'])
        self.assertEqual(state['history'], before['history'])
        self.assertEqual(state['winner'], before['winner'])

    def test_apply_pick_rejects_a_second_pick_from_the_same_seat(self):
        """A committed pick cannot be silently overwritten by the same seat.

        ``legal_actions`` already returns ``()`` for a seat that has picked,
        so ``apply_pick`` accepting the same call would contradict the declared
        rules and let a seat change a commitment that was already recorded and
        broadcast.
        """
        state = rules.apply_pick(self._open_match(), 'seat-0', 'rock')
        before = copy.deepcopy(state)

        with self.assertRaises(ValueError):
            rules.apply_pick(state, 'seat-0', 'paper')

        self.assertEqual(state, before)
        self.assertEqual(state['picks']['seat-0'], 'rock')

    def test_illegal_second_pick_never_wins_the_round(self):
        """Regression for an illegal pick previously winning the round.

        With seat-0 legally holding ``rock``, a seat-1 pick of ``banana`` was
        silently accepted and scored as the round winner because ``resolve``
        fell through to ``'second'`` for any non-beaten value. It must raise
        and must never produce a winner.
        """
        state = rules.apply_pick(self._open_match(), 'seat-0', 'rock')

        with self.assertRaises(ValueError):
            rules.apply_pick(state, 'seat-1', 'banana')

        self.assertIsNone(state['winner'])
        self.assertIsNone(state['reveal'])

    def test_resolve_rejects_an_illegal_value_in_either_position(self):
        """``resolve`` raises ``ValueError``, not ``KeyError``, for bad input."""
        with self.assertRaises(ValueError):
            rules.resolve('banana', 'rock')
        with self.assertRaises(ValueError):
            rules.resolve('rock', 'banana')

    def test_outcome_is_none_until_the_match_is_finished(self):
        """Only a finished match yields an outcome naming the winner."""
        state = self._open_match()
        self.assertIsNone(rules.outcome(state))

        state = self._resolve_round(state, 'rock', 'scissors')
        self.assertIsNone(rules.outcome(state))

        state = self._resolve_round(state, 'paper', 'rock')
        outcome = rules.outcome(state)

        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.winner_seat, 'seat-0')
        self.assertEqual(outcome.reason, 'best_of_three')
