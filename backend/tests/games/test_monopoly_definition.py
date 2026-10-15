"""Runtime-contract tests for the ``monopoly`` game definition (S1, S13-S15).

The definition is stateless; these tests drive it through the framework-free
contract and assert the frozen ``view`` shape the match screen consumes, the
registration fields the catalog serves, and the loud-failure rule for a missing
``RandomSource``.
"""

import copy
import json

from django.test import SimpleTestCase

from modules.games.contracts import Action, Seat
from modules.games.monopoly import board
from modules.games.monopoly.game import MonopolyDefinition


class StubRng:
    """Deterministic ``RandomSource`` that plays back a fixed order and dice."""

    def __init__(self, order=(), dice=()):
        self.order = list(order)
        self.dice = list(dice)
        self.shuffle_calls = []

    def shuffle(self, items):
        self.shuffle_calls.append(tuple(items))
        return list(self.order)

    def roll(self, sides):
        if not self.dice:
            raise AssertionError('the definition rolled more dice than the test gave')
        return self.dice.pop(0)


def _seats(count=2):
    return tuple(
        Seat(
            index=index,
            participant_ref=f'{index:08d}-1111-1111-1111-111111111111',
        )
        for index in range(count)
    )


class MonopolyDefinitionTests(SimpleTestCase):
    def setUp(self):
        self.definition = MonopolyDefinition()
        self.seats = _seats()

    def _start(self, first='seat-0', seats=None):
        seats = self.seats if seats is None else seats
        order = [first] + [seat for seat in ('seat-0', 'seat-1') if seat != first]
        self.rng = StubRng(order=order)
        return self.definition.start(seats, self.rng)

    def test_registration_fields(self):
        self.assertEqual(self.definition.game_id, 'monopoly')
        self.assertEqual(self.definition.label, 'Monopoly')
        self.assertEqual(
            self.definition.description,
            'Comprá, alquilá y llevá a la quiebra a tus rivales: gana el último solvente.',
        )
        self.assertEqual(self.definition.min_seats, 2)
        self.assertEqual(self.definition.max_seats, 8)
        self.assertEqual(
            tuple(option.id for option in self.definition.seat_options),
            (
                'sombrero',
                'automovil',
                'perro',
                'barco',
                'gato',
                'plancha',
                'botin',
                'dedal',
            ),
        )
        self.assertEqual(
            len(self.definition.seat_options), self.definition.max_seats
        )

    def test_start_requires_a_random_source(self):
        with self.assertRaises(ValueError):
            self.definition.start(self.seats, None)

    def test_start_draws_the_opening_seat_from_the_rng(self):
        state = self._start(first='seat-1')
        self.assertEqual(state['turn'], 'seat-1')
        self.assertEqual(self.rng.shuffle_calls, [('seat-0', 'seat-1')])

    def test_start_seats_every_player_at_go_with_the_starting_cash(self):
        state = self._start()
        for seat in ('seat-0', 'seat-1'):
            with self.subTest(seat=seat):
                player = state['players'][seat]
                self.assertEqual(player['position'], board.GO_INDEX)
                self.assertEqual(player['cash'], 1500)
                self.assertEqual(player['properties'], [])
                self.assertIs(player['eliminated'], False)

    def test_start_rejects_a_roster_outside_the_seat_range(self):
        for count in (1, 9):
            with self.subTest(count=count):
                seats = _seats(count)
                order = [f'seat-{seat.index}' for seat in seats]
                with self.assertRaises(ValueError):
                    self.definition.start(seats, StubRng(order=order))

    def test_active_seats_is_the_seat_on_turn(self):
        state = self._start(first='seat-1')
        self.assertEqual(self.definition.active_seats(state), ('seat-1',))

    def test_legal_actions_are_emitted_only_for_the_seat_on_turn(self):
        state = self._start()
        self.assertEqual(
            tuple(
                spec.name for spec in self.definition.legal_actions(state, 'seat-0')
            ),
            ('roll',),
        )
        self.assertEqual(self.definition.legal_actions(state, 'seat-1'), ())

    def test_apply_drives_the_match_through_the_contract(self):
        state = self._start()
        transition = self.definition.apply(
            state, 'seat-0', Action(name='roll'), StubRng(dice=[1, 2])
        )
        self.assertEqual(transition.state['players']['seat-0']['position'], 3)
        self.assertEqual(
            tuple(fact.name for fact in transition.facts),
            ('roll_recorded', 'moved', 'purchase_offered'),
        )

    def test_an_action_out_of_turn_is_rejected_by_the_contract(self):
        state = self._start()
        with self.assertRaises(ValueError):
            self.definition.apply(
                state, 'seat-1', Action(name='roll'), StubRng(dice=[1, 2])
            )

    def test_the_view_carries_the_fields_every_match_screen_reads(self):
        state = self._start()
        view = self.definition.view(state, 'seat-0')
        self.assertIs(view['finished'], False)
        self.assertIsNone(view['winner'])
        self.assertIs(view['ended_by_abandon'], False)
        self.assertEqual(view['you'], 'seat-0')
        self.assertEqual(view['phase'], 'awaiting_roll')
        self.assertEqual(view['turn'], 'seat-0')
        self.assertIsNone(view['last_roll'])
        self.assertIsNone(view['pending'])
        self.assertEqual(view['owners'], {})

    def test_the_view_projects_every_player_in_seat_order(self):
        state = self._start()
        view = self.definition.view(state, None)
        self.assertEqual(
            [player['seat'] for player in view['players']],
            ['seat-0', 'seat-1'],
        )
        self.assertEqual(
            view['players'][0],
            {
                'seat': 'seat-0',
                'cash': 1500,
                'position': board.GO_INDEX,
                'properties': [],
                'in_jail': False,
                'jail_turns': 0,
                'eliminated': False,
            },
        )

    def test_the_seat_view_carries_its_legal_actions_and_the_spectator_none(self):
        state = self._start()
        player_view = self.definition.view(state, 'seat-0')
        self.assertEqual(
            player_view['actions'],
            [
                {
                    'name': 'roll',
                    'prompt': 'Tirá los dados.',
                    'options': [],
                }
            ],
        )
        idle_view = self.definition.view(state, 'seat-1')
        self.assertEqual(idle_view['actions'], [])
        spectator_view = self.definition.view(state, None)
        self.assertEqual(spectator_view['actions'], [])
        self.assertNotIn('you', spectator_view)

    def test_the_view_tracks_a_pending_purchase(self):
        state = self.definition.apply(
            self._start(), 'seat-0', Action(name='roll'), StubRng(dice=[1, 2])
        ).state
        player_view = self.definition.view(state, 'seat-0')
        self.assertEqual(player_view['pending'], {'kind': 'purchase', 'space': 3})
        self.assertEqual(
            [action['name'] for action in player_view['actions']],
            ['buy', 'decline'],
        )
        self.assertEqual(player_view['last_roll'], [1, 2])
        self.assertEqual(
            self.definition.view(state, None)['pending'],
            {'kind': 'purchase', 'space': 3},
        )

    def test_the_view_is_json_serializable_and_survives_a_state_round_trip(self):
        state = self._start()
        state = self.definition.apply(
            state, 'seat-0', Action(name='roll'), StubRng(dice=[1, 2])
        ).state
        state = self.definition.apply(state, 'seat-0', Action(name='buy'), None).state
        before = self.definition.view(state, 'seat-0')
        # The runtime persists the state in a jsonb column and reads it back, so
        # the projection must be identical after a round trip: no tuple may leak
        # into the state and no key may depend on Python-only types.
        round_tripped = json.loads(json.dumps(state))
        self.assertEqual(round_tripped, state)
        self.assertEqual(self.definition.view(round_tripped, 'seat-0'), before)
        self.assertEqual(
            json.loads(json.dumps(self.definition.view(round_tripped, None))),
            self.definition.view(state, None),
        )

    def test_a_finished_match_reports_the_winner_and_no_turn(self):
        state = self.definition.abandon(self._start(), 'seat-1', None).state
        view = self.definition.view(state, 'seat-0')
        self.assertIs(view['finished'], True)
        self.assertEqual(view['winner'], 'seat-0')
        self.assertIs(view['ended_by_abandon'], True)
        self.assertIsNone(view['turn'])
        self.assertEqual(self.definition.active_seats(state), ())
        self.assertEqual(view['actions'], [])
        self.assertEqual(
            self.definition.outcome(state).reason, 'win_by_abandon'
        )

    def test_abandon_delegates_to_the_rules(self):
        state = self._start()
        transition = self.definition.abandon(state, 'seat-0', None)
        self.assertIs(transition.state['players']['seat-0']['eliminated'], True)
        self.assertEqual(transition.state['abandoned_seat'], 'seat-0')

    def test_the_rules_state_is_never_aliased_into_the_view(self):
        state = self._start()
        view = self.definition.view(state, 'seat-0')
        before = copy.deepcopy(state)
        view['owners']['3'] = 'seat-0'
        view['players'][0]['cash'] = 1
        view['last_roll'] = [6, 6]
        self.assertEqual(state, before)
