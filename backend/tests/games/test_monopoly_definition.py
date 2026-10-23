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
from modules.games.monopoly import board, cards
from modules.games.monopoly.game import MonopolyDefinition


class StubRng:
    """Deterministic ``RandomSource`` that plays back a fixed sequence of dice."""

    def __init__(self, dice=()):
        self.dice = list(dice)
        self.shuffle_calls = []

    def shuffle(self, items):
        self.shuffle_calls.append(tuple(items))
        return list(items)

    def roll(self, sides):
        if not self.dice:
            raise AssertionError('the definition rolled more dice than the test gave')
        return self.dice.pop(0)


class ReversingRng(StubRng):
    """A ``RandomSource`` whose shuffle reverses, so a shuffle is observable."""

    def shuffle(self, items):
        return list(reversed(list(items)))


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
        # The printed throw-off: every seat throws, and `first` throws highest.
        dice = []
        for seat in seats:
            dice.extend([6, 6] if f'seat-{seat.index}' == first else [1, 1])
        self.rng = StubRng(dice=dice)
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
                'pinguino',
                'pato',
            ),
        )
        # A marker reserves nothing, so the catalogue only has to cover the
        # table: the two flat-token markers (`monopoly-flat-figures.md`, S2) make
        # it larger than `max_seats`, and the seat limit still comes from the
        # printed board.
        self.assertGreaterEqual(
            len(self.definition.seat_options), self.definition.max_seats
        )
        self.assertEqual(
            len({option.id for option in self.definition.seat_options}),
            len(self.definition.seat_options),
        )

    def test_start_requires_a_random_source(self):
        with self.assertRaises(ValueError):
            self.definition.start(self.seats, None)

    def test_start_draws_the_opening_seat_from_the_rng(self):
        state = self._start(first='seat-1')
        self.assertEqual(state['turn'], 'seat-1')
        # The opening seat comes from the throw and never from a draw, so the
        # only things shuffled are the two decks.
        self.assertEqual(
            self.rng.shuffle_calls,
            [
                tuple(cards.deck_ids(cards.CHANCE)),
                tuple(cards.deck_ids(cards.COMMUNITY_CHEST)),
            ],
        )

    def test_the_highest_throw_opens_the_match(self):
        rng = StubRng(dice=[1, 2, 6, 6])
        state = self.definition.start(self.seats, rng)
        self.assertEqual(state['turn'], 'seat-1')

    def test_a_tie_is_rethrown_and_the_higher_total_opens(self):
        # Both seats throw a 7, then re-throw: seat-0 gets 2 and seat-1 gets 12.
        rng = StubRng(dice=[3, 4, 3, 4, 1, 1, 6, 6])
        state = self.definition.start(self.seats, rng)
        self.assertEqual(state['turn'], 'seat-1')

    def test_start_shuffles_both_decks_with_the_random_source(self):
        rng = ReversingRng(dice=[6, 6, 1, 1])

        state = self.definition.start(self.seats, rng)

        self.assertEqual(
            state['decks'][cards.CHANCE], list(reversed(cards.deck_ids(cards.CHANCE)))
        )
        self.assertEqual(
            state['decks'][cards.COMMUNITY_CHEST],
            list(reversed(cards.deck_ids(cards.COMMUNITY_CHEST))),
        )

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
                # The roster is validated before the throw, so no dice are needed.
                with self.assertRaises(ValueError):
                    self.definition.start(seats, StubRng())

    def test_active_seats_is_every_solvent_seat(self):
        state = self._start(first='seat-1')
        # Every solvent seat is active so it can negotiate out of turn; the
        # phase's own actions stay with the seat on turn (D1).
        self.assertEqual(
            self.definition.active_seats(state), ('seat-0', 'seat-1')
        )

    def test_the_phase_actions_belong_to_the_seat_on_turn(self):
        state = self._start()
        self.assertEqual(
            tuple(
                spec.name for spec in self.definition.legal_actions(state, 'seat-0')
            ),
            ('roll', 'propose'),
        )
        # A seat that is not the phase actor still gets the trade action.
        self.assertEqual(
            tuple(
                spec.name for spec in self.definition.legal_actions(state, 'seat-1')
            ),
            ('propose',),
        )

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
                'jail_cards': 0,
                'eliminated': False,
            },
        )

    def test_the_view_publishes_the_card_counts_and_never_the_deck_order(self):
        state = self._start()
        view = self.definition.view(state, None)

        self.assertEqual(view['decks'], {'chance': 16, 'community_chest': 16})
        self.assertIsNone(view['last_card'])
        # The order is hidden information: the only list-valued fields are the
        # roster and the seat's own actions, so no card id list can leak.
        self.assertEqual(
            sorted(key for key in view if isinstance(view[key], list)),
            ['actions', 'offers', 'players'],
        )

    def test_the_opening_view_has_no_buildings_and_the_full_bank(self):
        state = self._start()

        seat_view = self.definition.view(state, 'seat-0')
        spectator_view = self.definition.view(state, None)

        self.assertEqual(seat_view['buildings'], {})
        self.assertEqual(seat_view['bank'], {'houses': 32, 'hotels': 12})
        self.assertEqual(spectator_view['buildings'], {})
        self.assertEqual(spectator_view['bank'], {'houses': 32, 'hotels': 12})

    def test_the_view_publishes_the_buildings_and_the_bank_stock(self):
        state = self._start()
        state['owners'] = {'1': 'seat-0', '3': 'seat-0'}
        state['players']['seat-0']['properties'] = [1, 3]
        state['phase'] = 'managing'

        transition = self.definition.apply(
            state, 'seat-0', Action(name='build', value='1'), None
        )

        seat_view = self.definition.view(transition.state, 'seat-0')
        spectator_view = self.definition.view(transition.state, None)

        self.assertEqual(seat_view['buildings'], {'1': 1})
        self.assertEqual(seat_view['bank'], {'houses': 31, 'hotels': 12})
        self.assertEqual(seat_view['you'], 'seat-0')
        # The buildings are physical objects on the table: the spectator sees
        # them and the bank stock too, and only loses ``you``/``actions``.
        self.assertEqual(spectator_view['buildings'], {'1': 1})
        self.assertEqual(spectator_view['bank'], {'houses': 31, 'hotels': 12})
        self.assertNotIn('you', spectator_view)
        self.assertEqual(spectator_view['actions'], [])

        round_tripped = json.loads(json.dumps(transition.state))
        self.assertEqual(round_tripped, transition.state)
        self.assertEqual(self.definition.view(round_tripped, None), spectator_view)

    def test_the_view_publishes_the_card_that_was_turned_up(self):
        state = self._start()
        state = self.definition.apply(
            state, 'seat-0', Action(name='roll'), StubRng(dice=[1, 1])
        ).state

        view = self.definition.view(state, None)

        self.assertEqual(view['last_card']['deck'], 'community_chest')
        self.assertEqual(view['last_card']['id'], 'community_chest-01')
        self.assertEqual(view['decks']['community_chest'], 16)
        self.assertIn('Avanzá', view['last_card']['title'])

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
                    'freeform': False,
                },
                {
                    'name': 'propose',
                    'prompt': self.definition.legal_actions(
                        state, 'seat-0'
                    )[1].prompt,
                    'options': [],
                    'freeform': True,
                },
            ],
        )
        idle_view = self.definition.view(state, 'seat-1')
        self.assertEqual(
            [action['name'] for action in idle_view['actions']], ['propose']
        )
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
            ['buy', 'decline', 'propose'],
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

    def test_the_opening_view_has_no_mortgages_and_no_debt(self):
        state = self._start()
        seat_view = self.definition.view(state, 'seat-0')
        spectator_view = self.definition.view(state, None)
        for view in (seat_view, spectator_view):
            self.assertEqual(view['mortgaged'], {})
            self.assertIsNone(view['debt'])

    def _trade_scene(self):
        state = self._start()
        state['owners'] = {
            '1': 'seat-0',
            '3': 'seat-0',
            '6': 'seat-1',
            '8': 'seat-1',
        }
        state['players']['seat-0']['properties'] = [1, 3]
        state['players']['seat-1']['properties'] = [6, 8]
        state['phase'] = 'managing'
        state['turn'] = 'seat-0'
        return state

    def test_the_view_publishes_the_offers_in_id_order_with_their_validity(self):
        state = self._trade_scene()
        state = self.definition.apply(
            state,
            'seat-0',
            Action(name='propose', value='to=seat-1;give=1;cash=0|want=6;cash=0'),
            None,
        ).state
        # seat-1 becomes active as the receiver of offer 1 and may propose back.
        state = self.definition.apply(
            state,
            'seat-1',
            Action(name='propose', value='to=seat-0;give=8;cash=0|want=3;cash=0'),
            None,
        ).state
        expected = [
            {
                'id': '1',
                'proposer': 'seat-0',
                'receiver': 'seat-1',
                'give': {'properties': [1], 'cash': 0},
                'want': {'properties': [6], 'cash': 0},
                'valid': True,
            },
            {
                'id': '2',
                'proposer': 'seat-1',
                'receiver': 'seat-0',
                'give': {'properties': [8], 'cash': 0},
                'want': {'properties': [3], 'cash': 0},
                'valid': True,
            },
        ]

        self.assertEqual(self.definition.view(state, 'seat-0')['offers'], expected)
        self.assertEqual(self.definition.view(state, 'seat-1')['offers'], expected)
        self.assertEqual(self.definition.view(state, None)['offers'], expected)

    def test_the_view_marks_a_stale_offer_as_not_valid(self):
        state = self._trade_scene()
        state = self.definition.apply(
            state,
            'seat-0',
            Action(name='propose', value='to=seat-1;give=1;cash=0|want=6;cash=0'),
            None,
        ).state
        stale = copy.deepcopy(state)
        stale['owners']['1'] = 'seat-1'
        stale['players']['seat-0']['properties'].remove(1)
        stale['players']['seat-1']['properties'].append(1)

        offers = self.definition.view(stale, 'seat-1')['offers']

        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]['id'], '1')
        self.assertIs(offers[0]['valid'], False)

    def test_the_view_offers_survive_a_json_round_trip(self):
        state = self._trade_scene()
        state = self.definition.apply(
            state,
            'seat-0',
            Action(name='propose', value='to=seat-1;give=1;cash=0|want=6;cash=0'),
            None,
        ).state
        before = self.definition.view(state, None)

        round_tripped = json.loads(json.dumps(state))

        self.assertEqual(self.definition.view(round_tripped, None), before)

    def test_the_view_publishes_the_mortgaged_map(self):
        state = self._start()
        state['owners'] = {'1': 'seat-0'}
        state['players']['seat-0']['properties'] = [1]
        state['phase'] = 'managing'

        mortgaged = self.definition.apply(
            state, 'seat-0', Action(name='mortgage', value='1'), None
        ).state

        self.assertEqual(
            self.definition.view(mortgaged, 'seat-0')['mortgaged'], {'1': True}
        )
        self.assertEqual(
            self.definition.view(mortgaged, None)['mortgaged'], {'1': True}
        )

    def test_the_view_publishes_only_the_public_debt_record(self):
        state = copy.deepcopy(self._start())
        state['phase'] = 'raising_cash'
        state['debt'] = {
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

        seat_view = self.definition.view(state, 'seat-0')
        spectator_view = self.definition.view(state, None)
        expected = {'seat': 'seat-0', 'creditor': 'seat-1', 'amount': 50}
        self.assertEqual(seat_view['phase'], 'raising_cash')
        self.assertEqual(seat_view['debt'], expected)
        self.assertEqual(spectator_view['debt'], expected)
        self.assertNotIn('resume', seat_view['debt'])
        self.assertNotIn('fact', seat_view['debt'])

    def test_the_view_publishes_a_bank_debt_with_a_null_creditor(self):
        state = copy.deepcopy(self._start())
        state['phase'] = 'raising_cash'
        state['debt'] = {
            'seat': 'seat-0',
            'creditor': None,
            'amount': 75,
            'resume': {'kind': 'settle_step', 'extra': False},
            'fact': None,
        }

        view = self.definition.view(state, None)

        self.assertEqual(
            view['debt'], {'seat': 'seat-0', 'creditor': None, 'amount': 75}
        )
