"""Runtime integration tests driving the real ``ta_te_ti`` definition.

The definition is exercised through the framework-free use cases
(``start_match`` / ``submit_action``) so the runtime's own gates --
``NotYourTurn`` and ``IllegalAction`` -- are proven against the real game, not
a fake.
"""

from django.test import SimpleTestCase

from modules.games.registry import GameRegistry
from modules.games.runtime.application.start_match import start_match
from modules.games.runtime.application.submit_action import submit_action
from modules.games.runtime.domain.errors import IllegalAction, NotYourTurn
from modules.games.runtime.infrastructure.random_source import SystemRandomSource
from modules.games.ta_te_ti.game import TaTeTiDefinition
from tests.games.support import FakeLifecycle, FakeProjector, FakeStore


class StubRng:
    """Deterministic ``RandomSource`` that plays back a fixed order."""

    def __init__(self, order):
        self.order = list(order)

    def shuffle(self, items):
        return list(self.order)

    def roll(self, sides):
        return 1


class TaTeTiRuntimeTests(SimpleTestCase):
    def setUp(self):
        self.definition = TaTeTiDefinition()
        self.registry = GameRegistry((self.definition,))
        self.store = FakeStore()
        self.projector = FakeProjector()
        self.lifecycle = FakeLifecycle()
        # seat-0 opens, so seat-1 is the first seat made to wait its turn.
        self.record = start_match(
            room_id=7,
            game_id='ta-te-ti',
            seats=((0, 'p0', 'sol'), (1, 'p1', 'luna')),
            store=self.store,
            registry=self.registry,
            projector=self.projector,
            rng=StubRng(('seat-0', 'seat-1')),
        )

    def _submit(self, participant_ref, value, *, name='pick'):
        current = self.store.records[self.record.match_ref]
        return submit_action(
            match_ref=self.record.match_ref,
            participant_ref=participant_ref,
            action_name=name,
            action_value=value,
            expected_version=current.version,
            store=self.store,
            registry=self.registry,
            projector=self.projector,
            lifecycle=self.lifecycle,
        )

    def test_start_without_a_random_source_fails_loudly(self):
        """The runtime must not open a ta-te-ti match without an rng."""
        with self.assertRaises(ValueError):
            start_match(
                room_id=7,
                game_id='ta-te-ti',
                seats=((0, 'p0', 'sol'), (1, 'p1', 'luna')),
                store=FakeStore(),
                registry=self.registry,
                projector=self.projector,
                rng=None,
            )

    def test_start_publishes_the_fixed_view_for_the_random_opening_seat(self):
        """The runtime publishes the frozen view with the random actor on turn."""
        published = self.projector.publishes[0]

        self.assertEqual(published['event'], 'match_started')
        self.assertEqual(published['views']['seat-0']['turn'], 'seat-0')
        self.assertEqual(published['views']['seat-0']['you'], 'seat-0')
        self.assertNotIn('you', published['views'][None])
        self.assertEqual(published['views'][None]['symbols'], {'seat-0': 'X', 'seat-1': 'O'})

    def test_an_off_turn_seat_is_rejected_with_not_your_turn(self):
        """The runtime rejects an action from the seat that is not on turn."""
        with self.assertRaises(NotYourTurn) as caught:
            self._submit('p1', '0')

        self.assertEqual(caught.exception.seat_id, 'seat-1')

    def test_an_occupied_cell_is_rejected_with_illegal_action(self):
        """The runtime rejects a cell that is already taken as an illegal action."""
        self._submit('p0', '0')

        with self.assertRaises(IllegalAction) as caught:
            self._submit('p1', '0')

        self.assertEqual(caught.exception.action_name, 'pick')
        self.assertEqual(caught.exception.seat_id, 'seat-1')

    def test_a_winning_trace_finishes_the_match_for_the_winner(self):
        """Three in a row through the runtime persists the winner."""
        self._submit('p0', '0')
        self._submit('p1', '3')
        self._submit('p0', '1')
        self._submit('p1', '4')
        final = self._submit('p0', '2')

        self.assertEqual(final.status, 'finished')
        self.assertEqual(final.winner_seat, 'seat-0')
        self.assertEqual(final.state['winner_line'], (0, 1, 2))
        self.assertEqual(
            [publish['event'] for publish in self.projector.publishes],
            [
                'match_started',
                'match_updated',
                'match_updated',
                'match_updated',
                'match_updated',
                'match_finished',
            ],
        )
        self.assertEqual(
            self.definition.view(final.state, None)['winner_line'], [0, 1, 2]
        )

    def test_a_full_board_without_a_line_finishes_in_a_draw(self):
        """A cat's game through the runtime persists a winnerless finish."""
        for participant_ref, value in (
            ('p0', '0'),
            ('p1', '1'),
            ('p0', '2'),
            ('p1', '4'),
            ('p0', '3'),
            ('p1', '5'),
            ('p0', '7'),
            ('p1', '6'),
            ('p0', '8'),
        ):
            final = self._submit(participant_ref, value)

        self.assertEqual(final.status, 'finished')
        self.assertIsNone(final.winner_seat)
        self.assertTrue(final.state['finished'])
        self.assertIsNone(final.state['winner'])
        self.assertEqual(self.definition.outcome(final.state).reason, 'draw')

    def test_abandon_awards_the_win_to_the_remaining_seat(self):
        """Expelling a seat through the runtime finishes the match for the other."""
        from modules.games.runtime.application.abandon_seat import abandon_seat

        final = abandon_seat(
            match_ref=self.record.match_ref,
            participant_ref='p1',
            store=self.store,
            registry=self.registry,
            projector=self.projector,
            lifecycle=self.lifecycle,
        )

        self.assertEqual(final.status, 'finished')
        self.assertEqual(final.winner_seat, 'seat-0')
        self.assertEqual(self.definition.outcome(final.state).reason, 'win_by_abandon')
        self.assertTrue(self.definition.view(final.state, None)['ended_by_abandon'])


class SystemRandomSourceTests(SimpleTestCase):
    """The production ``RandomSource`` adapter must satisfy the protocol."""

    def test_shuffle_returns_a_permutation_without_mutating_the_input(self):
        items = ('seat-0', 'seat-1', 'seat-2')

        shuffled = SystemRandomSource().shuffle(items)

        self.assertEqual(items, ('seat-0', 'seat-1', 'seat-2'))
        self.assertEqual(sorted(shuffled), ['seat-0', 'seat-1', 'seat-2'])

    def test_roll_stays_within_one_to_sides_inclusive(self):
        source = SystemRandomSource()

        for _ in range(64):
            self.assertIn(source.roll(6), range(1, 7))

    def test_roll_rejects_a_non_positive_sides(self):
        with self.assertRaises(ValueError):
            SystemRandomSource().roll(0)


class CompositionWiringTests(SimpleTestCase):
    """The production composition root must expose a real ``RandomSource``."""

    def test_composed_dependencies_carry_a_random_source(self):
        from modules.games.interfaces.composition import compose_match_dependencies

        dependencies = compose_match_dependencies()

        self.assertIsInstance(dependencies.rng, SystemRandomSource)
        self.assertTrue(callable(dependencies.rng.shuffle))
        self.assertTrue(callable(dependencies.rng.roll))
