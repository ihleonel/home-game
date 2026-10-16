"""Runtime integration tests driving the real ``monopoly`` definition.

The definition is exercised through the framework-free use cases
(``start_match`` / ``submit_action`` / ``abandon_seat``) so the runtime's own
gates -- ``NotYourTurn``, ``IllegalAction`` and ``StaleVersion`` -- are proven
against the real game, not a fake. The dice are scripted, so the whole trace is
deterministic.

The use cases are handed their dependencies here on purpose: this file proves
the game against the runtime, and the **production** wiring of those
dependencies is pinned separately by the REST tests in ``test_match_api.py``.
An integration test that injects its own dependencies cannot prove the wiring,
which is exactly how a missing ``rng`` in the action view stayed invisible.
"""

from django.test import SimpleTestCase

from modules.games.monopoly.game import MonopolyDefinition
from modules.games.registry import GameRegistry
from modules.games.runtime.application.abandon_seat import abandon_seat
from modules.games.runtime.application.start_match import start_match
from modules.games.runtime.application.submit_action import submit_action
from modules.games.runtime.domain.errors import (
    IllegalAction,
    NotYourTurn,
    StaleVersion,
)
from tests.games.support import FakeLifecycle, FakeProjector, FakeStore


class ScriptedRng:
    """Deterministic ``RandomSource``: a fixed opening order plus dice faces."""

    def __init__(self, order=(), dice=()):
        self.order = list(order)
        self.dice = list(dice)

    def shuffle(self, items):
        return list(self.order)

    def roll(self, sides):
        if not self.dice:
            raise AssertionError('the match rolled more dice than the test scripted')
        return self.dice.pop(0)


class MonopolyRuntimeTests(SimpleTestCase):
    def setUp(self):
        self.definition = MonopolyDefinition()
        self.registry = GameRegistry((self.definition,))
        self.store = FakeStore()
        self.projector = FakeProjector()
        self.lifecycle = FakeLifecycle()
        # seat-0 opens, so seat-1 is the first seat made to wait its turn.
        self.rng = ScriptedRng(
            order=('seat-0', 'seat-1'),
            dice=[
                6, 6, 1, 1,  # the throw-off: seat-0 throws 12 and opens the match
                1, 2,  # seat-0: Baltic, bought
                1, 2,  # seat-1: pays Baltic's rent
                3, 3,  # seat-0: Connecticut on a double
                3, 3,  # seat-0: Pennsylvania Railroad on a second double
                3, 3,  # seat-0: third double, straight to jail
                2, 3,  # seat-1: Vermont, bought
                2, 3,  # seat-0 from jail: no double, stays in
            ],
        )
        self.record = start_match(
            room_id=7,
            game_id='monopoly',
            seats=((0, 'p0', 'sombrero'), (1, 'p1', 'perro')),
            store=self.store,
            registry=self.registry,
            projector=self.projector,
            rng=self.rng,
        )

    def _current(self):
        return self.store.records[self.record.match_ref]

    def _submit(self, participant_ref, name, value=None, expected_version=None):
        current = self._current()
        return submit_action(
            match_ref=self.record.match_ref,
            participant_ref=participant_ref,
            action_name=name,
            action_value=value,
            expected_version=(
                current.version if expected_version is None else expected_version
            ),
            store=self.store,
            registry=self.registry,
            projector=self.projector,
            lifecycle=self.lifecycle,
            rng=self.rng,
        )

    def test_start_publishes_the_view_with_the_first_seat_ready_to_roll(self):
        published = self.projector.publishes[0]

        self.assertEqual(published['event'], 'match_started')
        self.assertEqual(published['views']['seat-0']['turn'], 'seat-0')
        self.assertEqual(published['views']['seat-0']['you'], 'seat-0')
        self.assertEqual(
            [action['name'] for action in published['views']['seat-0']['actions']],
            ['roll'],
        )
        self.assertNotIn('you', published['views'][None])
        self.assertEqual(published['views'][None]['actions'], [])
        self.assertEqual(published['views'][None]['turn'], 'seat-0')

    def test_start_without_a_random_source_fails_loudly(self):
        with self.assertRaises(ValueError):
            start_match(
                room_id=7,
                game_id='monopoly',
                seats=((0, 'p0', 'sombrero'), (1, 'p1', 'perro')),
                store=FakeStore(),
                registry=self.registry,
                projector=self.projector,
                rng=None,
            )

    def test_an_eight_seat_room_opens_through_the_real_registry(self):
        seats = tuple(
            (index, f'p{index}', marker)
            for index, marker in enumerate(
                option.id for option in self.definition.seat_options
            )
        )
        record = start_match(
            room_id=8,
            game_id='monopoly',
            seats=seats,
            store=FakeStore(),
            registry=self.registry,
            projector=self.projector,
            # The throw-off: seat-0 throws 12, every other seat throws 2.
            rng=ScriptedRng(dice=[6, 6] + [1, 1] * 7),
        )

        self.assertEqual(len(record.state['seats']), 8)
        self.assertEqual(record.state['turn'], 'seat-0')

    def test_an_off_turn_seat_is_rejected_with_not_your_turn(self):
        with self.assertRaises(NotYourTurn) as caught:
            self._submit('p1', 'roll')

        self.assertEqual(caught.exception.seat_id, 'seat-1')

    def test_an_action_the_seat_was_not_offered_is_rejected(self):
        # No purchase is pending, so `buy` is not among the seat's actions.
        with self.assertRaises(IllegalAction) as caught:
            self._submit('p0', 'buy')

        self.assertEqual(caught.exception.action_name, 'buy')
        self.assertEqual(caught.exception.seat_id, 'seat-0')

    def test_a_value_for_a_valueless_action_is_rejected(self):
        with self.assertRaises(IllegalAction):
            self._submit('p0', 'roll', value='7')

    def test_a_stale_version_is_rejected_before_the_action_is_judged(self):
        current = self._current()

        with self.assertRaises(StaleVersion):
            self._submit('p0', 'roll', expected_version=current.version + 1)

    def test_a_full_trace_through_the_runtime_persists_every_step(self):
        self._submit('p0', 'roll')                    # 1: Baltic
        self._submit('p0', 'buy')                     # 2
        self._submit('p0', 'end_turn')                # 3
        self._submit('p1', 'roll')                    # 4: pays rent
        self._submit('p1', 'end_turn')                # 5
        self._submit('p0', 'roll')                    # 6: Connecticut, double
        self._submit('p0', 'buy')                     # 7
        self._submit('p0', 'roll')                    # 8: Pennsylvania RR, double
        self._submit('p0', 'decline')                 # 9: opens the auction
        self._submit('p0', 'pass')                    # 10
        self._submit('p1', 'pass')                    # 11: deserted, back to the turn
        jailed = self._submit('p0', 'roll')           # 12: third double
        jail_facts = [fact['name'] for fact in self.projector.publishes[-1]['facts']]
        self._submit('p1', 'roll')                    # 13: Vermont
        self._submit('p1', 'buy')                     # 14
        self._submit('p1', 'end_turn')                # 15
        stayed = self._submit('p0', 'roll')           # 16: no double, stays in jail

        self.assertEqual(jailed.version, 12)
        self.assertEqual(self._current().version, 16)
        self.assertEqual(jailed.state['players']['seat-0']['in_jail'], True)
        self.assertEqual(jailed.state['doubles_count'], 0)
        self.assertEqual(jailed.state['turn'], 'seat-1')
        self.assertIn('sent_to_jail', jail_facts)
        self.assertEqual(stayed.state['players']['seat-0']['in_jail'], True)
        self.assertEqual(stayed.state['players']['seat-0']['jail_turns'], 1)
        self.assertEqual(stayed.state['players']['seat-0']['position'], 10)

        players = stayed.state['players']
        self.assertEqual(players['seat-0']['cash'], 1444 - 120)
        self.assertEqual(players['seat-1']['cash'], 1496 - 100)
        self.assertEqual(
            stayed.state['owners'],
            {'3': 'seat-0', '9': 'seat-0', '8': 'seat-1'},
        )
        self.assertEqual(stayed.state['turn'], 'seat-1')
        self.assertEqual(
            [publish['event'] for publish in self.projector.publishes],
            ['match_started'] + ['match_updated'] * 16,
        )

    def test_the_published_facts_describe_each_step(self):
        self._submit('p0', 'roll')
        published = self.projector.publishes[-1]

        self.assertEqual(
            published['facts'],
            (
                {'name': 'roll_recorded', 'seat': 'seat-0', 'detail': {'dice': [1, 2], 'doubles': False}},
                {'name': 'moved', 'seat': 'seat-0', 'detail': {'from': 0, 'to': 3, 'passed_go': False}},
                {'name': 'purchase_offered', 'seat': 'seat-0', 'detail': {'space': 3}},
            ),
        )

    def test_the_spectator_view_never_names_a_seat_as_you(self):
        published = self.projector.publishes[0]

        self.assertNotIn('you', published['views'][None])
        self.assertEqual(published['views'][None]['actions'], [])
        self.assertEqual(
            [player['seat'] for player in published['views'][None]['players']],
            ['seat-0', 'seat-1'],
        )

    def test_abandon_finishes_the_match_for_the_seat_that_stayed(self):
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
        self.assertTrue(final.state['ended_by_abandon'])
        self.assertIs(final.state['players']['seat-1']['eliminated'], True)
        self.assertEqual(self.definition.outcome(final.state).winner_seat, 'seat-0')
        self.assertEqual(self.definition.outcome(final.state).reason, 'win_by_abandon')
        self.assertEqual(self.projector.publishes[-1]['event'], 'match_finished')
        self.assertEqual(final.state['turn'], None)
