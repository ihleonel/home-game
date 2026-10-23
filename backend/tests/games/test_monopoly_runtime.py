"""Runtime integration tests driving the real ``monopoly`` definition.

The definition is exercised through the framework-free use cases
(``start_match`` / ``submit_action`` / ``abandon_seat``) so the runtime's own
gates -- ``IllegalAction`` and ``StaleVersion`` -- are proven
against the real game, not a fake. The dice are scripted, so the whole trace is
deterministic.

The use cases are handed their dependencies here on purpose: this file proves
the game against the runtime, and the **production** wiring of those
dependencies is pinned separately by the REST tests in ``test_match_api.py``.
An integration test that injects its own dependencies cannot prove the wiring,
which is exactly how a missing ``rng`` in the action view stayed invisible.
"""

from django.test import SimpleTestCase

from modules.games.contracts import ActionSpec, Fact, Transition, seat_id
from modules.games.monopoly.game import MonopolyDefinition
from modules.games.registry import GameRegistry
from modules.games.runtime.application.abandon_seat import abandon_seat
from modules.games.runtime.application.start_match import start_match
from modules.games.runtime.application.submit_action import submit_action
from modules.games.runtime.domain.errors import (
    IllegalAction,
    StaleVersion,
)
from tests.games.support import FakeLifecycle, FakeProjector, FakeStore


class ScriptedRng:
    """Deterministic ``RandomSource``: scripted dice, decks left in printed order.

    The opening seat comes from the scripted faces, never from the shuffle, so
    ``shuffle`` returns the cards it was handed: a source that answers a deck
    shuffle with anything else stores that other thing as the deck, which is
    the defect this class carried as ``order`` and the reason the suite was
    flaky. ``fresh_decks`` now rejects such a source outright.
    """

    def __init__(self, dice=()):
        self.dice = list(dice)

    def shuffle(self, items):
        return list(items)

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
            ['roll', 'propose'],
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
        # The table seats eight, and the marker catalogue is larger than that
        # (`monopoly-flat-figures.md`, S2): the seats take the first eight markers
        # instead of one per catalogue entry, which is what this test used to do.
        seats = tuple(
            (index, f'p{index}', option.id)
            for index, option in enumerate(
                self.definition.seat_options[: self.definition.max_seats]
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

    def test_an_off_turn_seat_negotiates_but_cannot_roll(self):
        # Every solvent seat is active (D1), so an off-turn seat is no longer
        # ``NotYourTurn``: it is offered the trade actions, and its illegal
        # action is rejected because the engine never offered it ``roll``.
        with self.assertRaises(IllegalAction) as caught:
            self._submit('p1', 'roll')

        self.assertEqual(caught.exception.action_name, 'roll')
        self.assertEqual(caught.exception.seat_id, 'seat-1')

        proposed = self._submit(
            'p1',
            'propose',
            value='to=seat-0;give=;cash=100|want=;cash=0',
        )

        self.assertEqual(proposed.state['offers']['1']['proposer'], 'seat-1')
        self.assertEqual(proposed.state['offers']['1']['receiver'], 'seat-0')

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

    def _seed_managing_brown(self):
        """Give seat-0 complete brown and hand it the free building window."""
        current = self._current()
        current.state['owners'] = {'1': 'seat-0', '3': 'seat-0'}
        current.state['players']['seat-0']['properties'] = [1, 3]
        current.state['players']['seat-0']['cash'] = 1500
        current.state['phase'] = 'managing'
        current.state['turn'] = 'seat-0'
        return current

    def test_a_build_through_the_runtime_publishes_the_buildings(self):
        current = self._seed_managing_brown()

        result = self._submit('p0', 'build', value='1')

        published = self.projector.publishes[-1]
        self.assertEqual(result.version, current.version + 1)
        self.assertEqual(result.state['buildings'], {'1': 1})
        self.assertEqual(result.state['bank'], {'houses': 31, 'hotels': 12})
        self.assertEqual(published['event'], 'match_updated')
        self.assertEqual(
            published['facts'],
            (
                {
                    'name': 'building_bought',
                    'seat': 'seat-0',
                    'detail': {'space': 1, 'level': 1, 'price': 50},
                },
            ),
        )
        self.assertEqual(published['views']['seat-0']['buildings'], {'1': 1})
        self.assertEqual(
            published['views'][None]['bank'], {'houses': 31, 'hotels': 12}
        )

    def test_a_build_the_seat_was_not_offered_is_rejected(self):
        self._seed_managing_brown()

        with self.assertRaises(IllegalAction) as caught:
            self._submit('p0', 'build', value='39')

        self.assertEqual(caught.exception.action_name, 'build')

    def test_a_mortgage_through_the_runtime_publishes_the_mortgaged_map(self):
        current = self._seed_managing_brown()

        result = self._submit('p0', 'mortgage', value='1')

        published = self.projector.publishes[-1]
        self.assertEqual(result.version, current.version + 1)
        self.assertEqual(result.state['mortgaged'], {'1': True})
        self.assertEqual(published['views']['seat-0']['mortgaged'], {'1': True})
        self.assertEqual(published['views'][None]['mortgaged'], {'1': True})
        self.assertEqual(
            published['facts'],
            (
                {
                    'name': 'property_mortgaged',
                    'seat': 'seat-0',
                    'detail': {'space': 1, 'amount': 30},
                },
            ),
        )

    def test_a_trade_through_the_runtime_settles_and_publishes_the_offer(self):
        current = self._seed_managing_brown()
        current.state['owners']['6'] = 'seat-1'
        current.state['players']['seat-1']['properties'] = [6]

        proposed = self._submit(
            'p0',
            'propose',
            value='to=seat-1;give=1;cash=0|want=6;cash=0',
        )

        published = self.projector.publishes[-1]
        self.assertEqual(proposed.state['offers']['1']['proposer'], 'seat-0')
        self.assertEqual(
            published['views']['seat-0']['offers'][0]['valid'], True
        )
        self.assertEqual(published['views'][None]['offers'][0]['id'], '1')
        accept = next(
            action
            for action in published['views']['seat-1']['actions']
            if action['name'] == 'accept'
        )
        self.assertEqual(accept['options'], ['1'])

        accepted = self._submit('p1', 'accept', value='1')

        self.assertEqual(accepted.state['owners']['1'], 'seat-1')
        self.assertEqual(accepted.state['owners']['6'], 'seat-0')
        self.assertEqual(
            sorted(accepted.state['players']['seat-0']['properties']), [3, 6]
        )
        self.assertEqual(accepted.state['offers'], {})
        self.assertEqual(
            [fact['name'] for fact in self.projector.publishes[-1]['facts']],
            ['offer_accepted', 'trade_settled'],
        )

    def test_a_malformed_proposal_is_an_illegal_action_through_the_runtime(self):
        self._seed_managing_brown()

        with self.assertRaises(IllegalAction) as caught:
            self._submit('p0', 'propose', value='not-a-proposal')

        self.assertEqual(caught.exception.action_name, 'propose')
        self.assertEqual(caught.exception.seat_id, 'seat-0')

    def test_the_debt_window_is_driven_through_the_runtime(self):
        current = self._current()
        current.state['phase'] = 'raising_cash'
        current.state['turn'] = 'seat-0'
        current.state['players']['seat-0']['cash'] = 50
        current.state['debt'] = {
            'seat': 'seat-0',
            'creditor': 'seat-1',
            'amount': 50,
            'resume': {'kind': 'settle_step', 'extra': False},
            'fact': {
                'name': 'rent_paid',
                'seat': 'seat-0',
                'detail': {
                    'from': 'seat-0',
                    'to': 'seat-1',
                    'space': 39,
                    'amount': 50,
                },
            },
        }

        result = self._submit('p0', 'pay_debt')

        published = self.projector.publishes[-1]
        self.assertEqual(result.version, current.version + 1)
        self.assertIsNone(result.state['debt'])
        self.assertEqual(result.state['phase'], 'managing')
        self.assertEqual(result.state['players']['seat-1']['cash'], 1550)
        self.assertIsNone(published['views']['seat-0']['debt'])
        self.assertIsNone(published['views'][None]['debt'])
        self.assertEqual(
            published['facts'],
            (
                {
                    'name': 'rent_paid',
                    'seat': 'seat-0',
                    'detail': {
                        'from': 'seat-0',
                        'to': 'seat-1',
                        'space': 39,
                        'amount': 50,
                    },
                },
            ),
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


class FreeformDefinition:
    """Runtime probe whose single action carries a composed value (S3).

    The channel is generic runtime behaviour, not a Monopoly rule, so the test
    drives a definition that isolates it: one freeform action whose engine
    optionally raises ``ValueError`` so the masking rule can be observed.
    """

    game_id = 'freeform-probe'
    label = 'Freeform probe'
    description = 'Test double: a single freeform action.'
    min_seats = 2
    max_seats = 2
    seat_options = ()

    def __init__(self):
        self.apply_calls = []

    def start(self, seats, rng):
        return {
            'seat_ids': [seat_id(seat.index) for seat in seats],
            'submitted': {},
        }

    def active_seats(self, state):
        return tuple(
            seat for seat in state['seat_ids'] if seat not in state['submitted']
        )

    def legal_actions(self, state, seat):
        if seat not in state['seat_ids'] or seat in state['submitted']:
            return ()
        return (ActionSpec(name='submit', freeform=True, prompt='Send a value.'),)

    def apply(self, state, seat, action, rng):
        self.apply_calls.append((seat, action.value))
        if action.value == 'engine-rejects':
            raise ValueError('the engine rejected the composed value')
        return Transition(
            state={
                **state,
                'submitted': {**state['submitted'], seat: action.value},
            },
            facts=(Fact(name='submitted', seat=seat, detail={'value': action.value}),),
        )

    def abandon(self, state, seat, rng):
        return Transition(state=state, facts=())

    def view(self, state, seat):
        return {'submitted': dict(state['submitted'])}

    def is_finished(self, state):
        return len(state['submitted']) == len(state['seat_ids'])

    def outcome(self, state):
        return None


class FreeformChannelRuntimeTests(SimpleTestCase):
    """The runtime accepts a composed value only for a freeform spec (S3)."""

    def setUp(self):
        self.definition = FreeformDefinition()
        self.registry = GameRegistry((self.definition,))
        self.store = FakeStore()
        self.projector = FakeProjector()
        self.lifecycle = FakeLifecycle()
        self.record = start_match(
            room_id=11,
            game_id='freeform-probe',
            seats=((0, 'p0', 'red'), (1, 'p1', 'blue')),
            store=self.store,
            registry=self.registry,
            projector=self.projector,
        )

    def _submit(self, participant_ref, value, expected_version=None):
        current = self.store.records[self.record.match_ref]
        return submit_action(
            match_ref=self.record.match_ref,
            participant_ref=participant_ref,
            action_name='submit',
            action_value=value,
            expected_version=(
                current.version if expected_version is None else expected_version
            ),
            store=self.store,
            registry=self.registry,
            projector=self.projector,
            lifecycle=self.lifecycle,
        )

    def test_a_freeform_spec_accepts_any_non_empty_string(self):
        result = self._submit('p0', 'anything the client composed')

        self.assertEqual(
            result.state['submitted']['seat-0'], 'anything the client composed'
        )

    def test_a_freeform_spec_rejects_none_and_the_empty_string(self):
        for value in (None, ''):
            with self.subTest(value=value):
                with self.assertRaises(IllegalAction):
                    self._submit('p0', value)
        self.assertEqual(self.definition.apply_calls, [])

    def test_an_engine_rejection_of_a_freeform_value_is_a_client_error(self):
        with self.assertRaises(IllegalAction) as caught:
            self._submit('p0', 'engine-rejects')

        self.assertEqual(caught.exception.action_name, 'submit')
        self.assertEqual(caught.exception.seat_id, 'seat-0')

    def test_a_long_value_round_trips_into_the_audit_row(self):
        value = 'x' * 240

        self._submit('p0', value)

        self.assertEqual(self.store.actions[0]['action'].value, value)


class NonFreeformRuntimeTests(SimpleTestCase):
    """A non-freeform spec keeps the enumerated/None contract (S3)."""

    game_id = 'options-probe'

    class _OptionsDefinition(FreeformDefinition):
        game_id = 'options-probe'

        def legal_actions(self, state, seat):
            if seat not in state['seat_ids'] or seat in state['submitted']:
                return ()
            return (
                ActionSpec(name='submit', options=('low', 'high')),
                ActionSpec(name='pass'),
            )

        def apply(self, state, seat, action, rng):
            self.apply_calls.append((seat, action.value))
            if action.value == 'high':
                raise ValueError('a programming error, not a client error')
            return Transition(
                state={
                    **state,
                    'submitted': {**state['submitted'], seat: action.value},
                },
                facts=(Fact(name='submitted', seat=seat, detail={}),),
            )

    def setUp(self):
        self.definition = self._OptionsDefinition()
        self.registry = GameRegistry((self.definition,))
        self.store = FakeStore()
        self.projector = FakeProjector()
        self.lifecycle = FakeLifecycle()
        self.record = start_match(
            room_id=12,
            game_id='options-probe',
            seats=((0, 'p0', 'red'), (1, 'p1', 'blue')),
            store=self.store,
            registry=self.registry,
            projector=self.projector,
        )

    def _submit(self, name, value):
        current = self.store.records[self.record.match_ref]
        return submit_action(
            match_ref=self.record.match_ref,
            participant_ref='p0',
            action_name=name,
            action_value=value,
            expected_version=current.version,
            store=self.store,
            registry=self.registry,
            projector=self.projector,
            lifecycle=self.lifecycle,
        )

    def test_an_enumerated_spec_keeps_its_options_check(self):
        with self.assertRaises(IllegalAction):
            self._submit('submit', 'medium')
        self.assertEqual(self.definition.apply_calls, [])

    def test_a_spec_without_options_still_requires_none(self):
        with self.assertRaises(IllegalAction):
            self._submit('pass', 'anything')
        self.assertEqual(self.definition.apply_calls, [])
        # A null value is still accepted for the optionless spec.
        result = self._submit('pass', None)
        self.assertEqual(result.state['submitted']['seat-0'], None)

    def test_a_programming_error_from_apply_is_never_masked(self):
        with self.assertRaises(ValueError):
            self._submit('submit', 'high')

        self.assertEqual(self.definition.apply_calls, [('seat-0', 'high')])
