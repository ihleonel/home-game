"""Pure-rule tests for the ``monopoly`` rules engine (S5-S12).

``SimpleTestCase`` only provides the runner so the rules can be exercised
without the database. The dice are scripted, one die face per value, so every
transition is deterministic. Each test asserts the full observable effect of
the rule it covers: the resulting state, the legal actions, the emitted facts
and, where the rule ends the match, the resolved outcome.
"""

import copy

from django.test import SimpleTestCase

from modules.games.contracts import Action, Outcome
from modules.games.monopoly import board, rules


class ScriptedRng:
    """Deterministic dice: each remaining value is the next die face.

    The rules roll one die at a time through ``RandomSource.roll``, so a script
    is the flat sequence of faces. Running out of script is an error rather
    than a silent default, so a rule that rolls more than the test expected
    fails instead of passing by accident.
    """

    def __init__(self, *faces):
        self.faces = list(faces)
        self.calls = 0

    def roll(self, sides):
        if sides != rules.DICE_SIDES:
            raise AssertionError(f'unexpected die: {sides}')
        self.calls += 1
        if not self.faces:
            raise AssertionError('the rules rolled more dice than the test scripted')
        return self.faces.pop(0)

    def shuffle(self, items):
        return list(items)


class MonopolyRulesTestCase(SimpleTestCase):
    """Shared harness: a match, scripted dice and state read/write helpers."""

    def _open(self, seats=('seat-0', 'seat-1'), first='seat-0'):
        return rules.initial_state(seats, first)

    def _roll(self, state, seat, *faces):
        return rules.apply_action(state, seat, Action(name='roll'), ScriptedRng(*faces))

    def _act(self, state, seat, name):
        return rules.apply_action(state, seat, Action(name=name), None)

    def _facts(self, transition):
        """Flatten the facts of a transition into ``(name, seat, detail)``."""
        return tuple(
            (fact.name, fact.seat, dict(fact.detail)) for fact in transition.facts
        )

    def _names(self, state, seat):
        return tuple(spec.name for spec in rules.legal_actions(state, seat))

    def _player(self, state, seat, **fields):
        state = copy.deepcopy(state)
        state['players'][seat].update(fields)
        return state

    def _place(self, state, seat, position):
        return self._player(state, seat, position=position)

    def _cash(self, state, seat, amount):
        return self._player(state, seat, cash=amount)

    def _give(self, state, index, seat):
        state = copy.deepcopy(state)
        state['owners'][str(index)] = seat
        state['players'][seat]['properties'].append(index)
        return state


class MonopolyPreparationTests(MonopolyRulesTestCase):
    def test_initial_state_is_the_documented_starting_position(self):
        state = self._open(('seat-0', 'seat-1'), first='seat-1')
        self.assertEqual(state['seats'], ['seat-0', 'seat-1'])
        self.assertEqual(state['turn'], 'seat-1')
        self.assertEqual(state['phase'], rules.PHASE_AWAITING_ROLL)
        self.assertIsNone(state['last_roll'])
        self.assertIsNone(state['pending'])
        self.assertEqual(state['doubles_count'], 0)
        self.assertIs(state['extra_roll'], False)
        self.assertEqual(state['owners'], {})
        self.assertEqual(state['bank'], {'houses': 32, 'hotels': 12})
        self.assertIs(state['ended_by_abandon'], False)
        self.assertIsNone(state['abandoned_seat'])
        self.assertIs(rules.is_finished(state), False)
        self.assertIsNone(rules.outcome(state))
        for seat in ('seat-0', 'seat-1'):
            with self.subTest(seat=seat):
                self.assertEqual(
                    state['players'][seat],
                    {
                        'cash': rules.STARTING_CASH,
                        'position': board.GO_INDEX,
                        'properties': [],
                        'in_jail': False,
                        'jail_turns': 0,
                        'eliminated': False,
                    },
                )

    def test_the_seat_count_range_is_two_to_eight(self):
        for count in (2, 8):
            seats = tuple(f'seat-{index}' for index in range(count))
            with self.subTest(count=count):
                state = rules.initial_state(seats, seats[0])
                self.assertEqual(len(state['seats']), count)

    def test_an_invalid_roster_is_rejected(self):
        for seats in ((), ('seat-0',), tuple(f'seat-{i}' for i in range(9))):
            with self.subTest(seats=seats):
                with self.assertRaises(ValueError):
                    rules.initial_state(seats, seats[0] if seats else 'seat-0')
        with self.assertRaises(ValueError):
            rules.initial_state(('seat-0', 'seat-0'), 'seat-0')
        with self.assertRaises(ValueError):
            rules.initial_state(('seat-0', 'seat-1'), 'seat-9')

    def test_two_matches_never_share_mutable_state(self):
        first = self._open()
        second = self._open()
        first['players']['seat-0']['cash'] = 1
        first['players']['seat-0']['properties'].append(3)
        first['owners']['3'] = 'seat-0'
        self.assertEqual(second['players']['seat-0']['cash'], rules.STARTING_CASH)
        self.assertEqual(second['players']['seat-0']['properties'], [])
        self.assertEqual(second['owners'], {})


class MonopolyTurnTests(MonopolyRulesTestCase):
    def test_roll_moves_the_token_and_records_the_dice(self):
        state = self._place(self._open(), 'seat-0', 15)
        transition = self._roll(state, 'seat-0', 2, 3)
        self.assertEqual(transition.state['players']['seat-0']['position'], 20)
        self.assertEqual(transition.state['last_roll'], [2, 3])
        self.assertEqual(transition.state['phase'], rules.PHASE_MANAGING)
        self.assertEqual(
            self._facts(transition),
            (
                ('roll_recorded', 'seat-0', {'dice': [2, 3], 'doubles': False}),
                ('moved', 'seat-0', {'from': 15, 'to': 20, 'passed_go': False}),
            ),
        )

    def test_landing_on_go_collects_the_salary_once(self):
        state = self._place(self._open(), 'seat-0', 37)
        transition = self._roll(state, 'seat-0', 1, 2)
        self.assertEqual(transition.state['players']['seat-0']['position'], 0)
        self.assertEqual(
            transition.state['players']['seat-0']['cash'],
            rules.STARTING_CASH + rules.GO_SALARY,
        )
        self.assertIn(
            ('moved', 'seat-0', {'from': 37, 'to': 0, 'passed_go': True}),
            self._facts(transition),
        )

    def test_passing_go_collects_the_salary_once(self):
        state = self._place(self._open(), 'seat-0', 38)
        transition = self._roll(state, 'seat-0', 2, 3)
        self.assertEqual(transition.state['players']['seat-0']['position'], 3)
        self.assertEqual(
            transition.state['players']['seat-0']['cash'],
            rules.STARTING_CASH + rules.GO_SALARY,
        )

    def test_doubles_grant_another_roll_to_the_same_seat(self):
        state = self._place(self._open(), 'seat-0', 15)
        first = self._roll(state, 'seat-0', 1, 1)
        self.assertEqual(first.state['players']['seat-0']['position'], 17)
        self.assertEqual(first.state['doubles_count'], 1)
        self.assertEqual(first.state['turn'], 'seat-0')
        self.assertEqual(first.state['phase'], rules.PHASE_AWAITING_ROLL)
        self.assertEqual(self._names(first.state, 'seat-0'), ('roll',))
        second = self._roll(first.state, 'seat-0', 1, 2)
        self.assertEqual(second.state['players']['seat-0']['position'], 20)
        self.assertEqual(second.state['doubles_count'], 1)
        self.assertEqual(second.state['phase'], rules.PHASE_MANAGING)

    def test_three_doubles_send_the_seat_to_jail_without_moving(self):
        state = self._open()
        first = self._roll(state, 'seat-0', 5, 5)
        self.assertEqual(first.state['players']['seat-0']['position'], 10)
        second = self._roll(first.state, 'seat-0', 5, 5)
        self.assertEqual(second.state['players']['seat-0']['position'], 20)
        third = self._roll(second.state, 'seat-0', 5, 5)
        player = third.state['players']['seat-0']
        self.assertEqual(player['position'], board.JAIL_INDEX)
        self.assertIs(player['in_jail'], True)
        self.assertEqual(player['jail_turns'], 0)
        self.assertEqual(third.state['doubles_count'], 0)
        self.assertEqual(third.state['turn'], 'seat-1')
        self.assertEqual(third.state['phase'], rules.PHASE_AWAITING_ROLL)
        self.assertEqual(self._facts(third)[-1], ('turn_ended', 'seat-0', {}))
        self.assertIn(
            ('sent_to_jail', 'seat-0', {'reason': 'three_doubles'}),
            self._facts(third),
        )

    def test_go_to_jail_ends_the_turn_even_on_doubles(self):
        state = self._place(self._open(), 'seat-0', 28)
        transition = self._roll(state, 'seat-0', 1, 1)
        player = transition.state['players']['seat-0']
        self.assertEqual(player['position'], board.JAIL_INDEX)
        self.assertIs(player['in_jail'], True)
        self.assertEqual(player['cash'], rules.STARTING_CASH)
        self.assertEqual(transition.state['turn'], 'seat-1')
        self.assertEqual(transition.state['phase'], rules.PHASE_AWAITING_ROLL)
        self.assertIn(
            ('sent_to_jail', 'seat-0', {'reason': 'go_to_jail'}),
            self._facts(transition),
        )

    def test_free_parking_and_just_visiting_do_nothing(self):
        cases = (
            (12, (3, 5), 'seat-0', 20),
            (5, (2, 3), 'seat-0', 10),
        )
        for start, faces, seat, expected in cases:
            with self.subTest(start=start):
                state = self._place(self._open(), seat, start)
                transition = self._roll(state, seat, *faces)
                self.assertEqual(transition.state['players'][seat]['position'], expected)
                self.assertEqual(
                    transition.state['players'][seat]['cash'], rules.STARTING_CASH
                )
                self.assertEqual(transition.state['phase'], rules.PHASE_MANAGING)

    def test_chance_and_community_chest_are_stops_without_a_consequence(self):
        for start, faces, expected in ((0, (1, 1), 2), (15, (1, 1), 17)):
            with self.subTest(start=start):
                state = self._place(self._open(), 'seat-0', start)
                transition = self._roll(state, 'seat-0', *faces)
                self.assertEqual(
                    transition.state['players']['seat-0']['position'], expected
                )
                self.assertNotIn(
                    'purchase_offered', [fact[0] for fact in self._facts(transition)]
                )

    def test_landing_on_an_own_property_does_nothing(self):
        state = self._give(self._open(), 3, 'seat-0')
        transition = self._roll(state, 'seat-0', 1, 2)
        self.assertEqual(transition.state['phase'], rules.PHASE_MANAGING)
        self.assertEqual(transition.state['players']['seat-0']['cash'], rules.STARTING_CASH)
        self.assertEqual(
            self._facts(transition),
            (
                ('roll_recorded', 'seat-0', {'dice': [1, 2], 'doubles': False}),
                ('moved', 'seat-0', {'from': 0, 'to': 3, 'passed_go': False}),
            ),
        )

    def test_end_turn_passes_the_turn_and_clears_the_turn_markers(self):
        state = self._place(self._open(), 'seat-0', 15)
        stopped = self._roll(state, 'seat-0', 2, 3).state
        self.assertEqual(self._names(stopped, 'seat-0'), ('end_turn',))
        ended = self._act(stopped, 'seat-0', 'end_turn')
        self.assertEqual(ended.state['turn'], 'seat-1')
        self.assertEqual(ended.state['phase'], rules.PHASE_AWAITING_ROLL)
        self.assertIsNone(ended.state['last_roll'])
        self.assertEqual(ended.state['doubles_count'], 0)
        self.assertIsNone(ended.state['pending'])
        self.assertEqual(self._facts(ended), (('turn_ended', 'seat-0', {}),))

    def test_legal_actions_are_empty_for_the_idle_seat(self):
        state = self._open()
        self.assertEqual(self._names(state, 'seat-1'), ())
        self.assertEqual(self._names(state, 'seat-0'), ('roll',))

    def test_an_action_out_of_turn_or_out_of_phase_is_rejected(self):
        state = self._open()
        with self.assertRaises(ValueError):
            self._roll(state, 'seat-1', 1, 2)
        with self.assertRaises(ValueError):
            self._roll(state, 'seat-9', 1, 2)
        with self.assertRaises(ValueError):
            self._act(state, 'seat-0', 'buy')
        stopped = self._roll(self._place(state, 'seat-0', 15), 'seat-0', 2, 3).state
        with self.assertRaises(ValueError):
            self._roll(stopped, 'seat-0', 1, 2)
        with self.assertRaises(ValueError):
            self._act(stopped, 'seat-0', 'buy')

    def test_rolling_without_a_random_source_fails_loudly(self):
        with self.assertRaises(ValueError):
            rules.apply_action(self._open(), 'seat-0', Action(name='roll'), None)

    def test_the_rules_never_mutate_the_state_they_receive(self):
        state = self._place(self._open(), 'seat-0', 15)
        before = copy.deepcopy(state)
        self._roll(state, 'seat-0', 2, 3)
        self.assertEqual(state, before)


class MonopolyJailTests(MonopolyRulesTestCase):
    def _jailed(self, seat='seat-0', jail_turns=0, first='seat-0'):
        state = rules.initial_state(('seat-0', 'seat-1'), first)
        return self._player(
            state,
            seat,
            in_jail=True,
            jail_turns=jail_turns,
            position=board.JAIL_INDEX,
        )

    def test_the_fine_is_offered_on_the_first_two_jail_turns_only(self):
        for jail_turns, expected in ((0, ('roll', 'pay_jail_fine')), (1, ('roll', 'pay_jail_fine')), (2, ('roll',))):
            with self.subTest(jail_turns=jail_turns):
                state = self._jailed(jail_turns=jail_turns)
                self.assertEqual(self._names(state, 'seat-0'), expected)

    def test_paying_the_fine_frees_the_seat_to_roll_a_normal_turn(self):
        paid = self._act(self._jailed(), 'seat-0', 'pay_jail_fine')
        player = paid.state['players']['seat-0']
        self.assertEqual(player['cash'], rules.STARTING_CASH - rules.JAIL_FINE)
        self.assertIs(player['in_jail'], False)
        self.assertEqual(player['jail_turns'], 0)
        self.assertEqual(paid.state['phase'], rules.PHASE_AWAITING_ROLL)
        self.assertEqual(paid.state['turn'], 'seat-0')
        self.assertEqual(self._facts(paid), (('left_jail', 'seat-0', {'method': 'fine'}),))
        rolled = self._roll(paid.state, 'seat-0', 5, 5)
        self.assertEqual(rolled.state['doubles_count'], 1)
        self.assertEqual(rolled.state['phase'], rules.PHASE_AWAITING_ROLL)

    def test_paying_the_fine_is_not_offered_without_the_cash(self):
        state = self._jailed()
        poor = self._cash(state, 'seat-0', rules.JAIL_FINE - 1)
        self.assertEqual(self._names(poor, 'seat-0'), ('roll',))
        with self.assertRaises(ValueError):
            self._act(poor, 'seat-0', 'pay_jail_fine')

    def test_a_jail_roll_without_doubles_keeps_the_seat_jailed(self):
        transition = self._roll(self._jailed(), 'seat-0', 2, 3)
        player = transition.state['players']['seat-0']
        self.assertIs(player['in_jail'], True)
        self.assertEqual(player['jail_turns'], 1)
        self.assertEqual(player['position'], board.JAIL_INDEX)
        self.assertEqual(transition.state['turn'], 'seat-1')
        self.assertEqual(transition.state['phase'], rules.PHASE_AWAITING_ROLL)
        self.assertNotIn('left_jail', [fact[0] for fact in self._facts(transition)])

    def test_a_double_releases_the_seat_and_grants_no_extra_turn(self):
        transition = self._roll(self._jailed(), 'seat-0', 5, 5)
        player = transition.state['players']['seat-0']
        self.assertIs(player['in_jail'], False)
        self.assertEqual(player['jail_turns'], 0)
        self.assertEqual(player['position'], 20)
        self.assertEqual(transition.state['doubles_count'], 0)
        self.assertEqual(transition.state['turn'], 'seat-0')
        self.assertEqual(transition.state['phase'], rules.PHASE_MANAGING)
        self.assertIn(
            ('left_jail', 'seat-0', {'method': 'doubles'}),
            self._facts(transition),
        )
        ended = self._act(transition.state, 'seat-0', 'end_turn')
        self.assertEqual(ended.state['turn'], 'seat-1')

    def test_the_third_jail_roll_without_doubles_costs_the_fine_and_moves(self):
        transition = self._roll(self._jailed(jail_turns=2), 'seat-0', 2, 3)
        player = transition.state['players']['seat-0']
        self.assertEqual(player['cash'], rules.STARTING_CASH - rules.JAIL_FINE)
        self.assertIs(player['in_jail'], False)
        self.assertEqual(player['jail_turns'], 0)
        self.assertEqual(player['position'], 15)
        self.assertIs(transition.state['extra_roll'], False)
        self.assertIn(
            ('left_jail', 'seat-0', {'method': 'fine'}),
            self._facts(transition),
        )
        declined = self._act(transition.state, 'seat-0', 'decline')
        self.assertEqual(declined.state['phase'], rules.PHASE_MANAGING)
        ended = self._act(declined.state, 'seat-0', 'end_turn')
        self.assertEqual(ended.state['turn'], 'seat-1')

    def test_a_jailed_seat_keeps_collecting_rent(self):
        state = self._jailed(first='seat-1')
        state = self._give(state, 3, 'seat-0')
        transition = self._roll(state, 'seat-1', 1, 2)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1504)
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1496)

    def test_an_unaffordable_fine_bankrupts_the_seat_to_the_bank(self):
        state = self._jailed(jail_turns=2)
        state = self._cash(state, 'seat-0', 10)
        state = self._give(state, 3, 'seat-0')
        transition = self._roll(state, 'seat-0', 2, 3)
        self.assertIs(transition.state['players']['seat-0']['eliminated'], True)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 0)
        self.assertEqual(transition.state['owners'], {})
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1500)
        self.assertIs(rules.is_finished(transition.state), True)
        self.assertIsNone(transition.state['turn'])
        self.assertIn(('bankrupt', 'seat-0', {'creditor': None}), self._facts(transition))


class MonopolyPurchaseTests(MonopolyRulesTestCase):
    def test_landing_on_an_unowned_property_offers_buy_and_decline(self):
        transition = self._roll(self._open(), 'seat-0', 1, 2)
        self.assertEqual(transition.state['phase'], rules.PHASE_AWAITING_DECISION)
        self.assertEqual(transition.state['pending'], {'kind': 'purchase', 'space': 3})
        self.assertEqual(self._names(transition.state, 'seat-0'), ('buy', 'decline'))
        self.assertIn(
            ('purchase_offered', 'seat-0', {'space': 3}), self._facts(transition)
        )

    def test_buying_pays_the_printed_price_and_records_the_owner(self):
        state = self._roll(self._open(), 'seat-0', 1, 2).state
        transition = self._act(state, 'seat-0', 'buy')
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1440)
        self.assertEqual(transition.state['players']['seat-0']['properties'], [3])
        self.assertEqual(transition.state['owners'], {'3': 'seat-0'})
        self.assertIsNone(transition.state['pending'])
        self.assertEqual(transition.state['phase'], rules.PHASE_MANAGING)
        self.assertEqual(
            self._facts(transition),
            (('property_bought', 'seat-0', {'space': 3, 'price': 60}),),
        )

    def test_declining_leaves_the_property_unowned(self):
        state = self._roll(self._open(), 'seat-0', 1, 2).state
        transition = self._act(state, 'seat-0', 'decline')
        self.assertEqual(transition.state['owners'], {})
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1500)
        self.assertEqual(transition.state['players']['seat-0']['properties'], [])
        self.assertEqual(transition.state['phase'], rules.PHASE_MANAGING)
        self.assertEqual(
            self._facts(transition),
            (('purchase_declined', 'seat-0', {'space': 3}),),
        )

    def test_buy_is_not_offered_without_the_cash(self):
        state = self._roll(self._cash(self._open(), 'seat-0', 10), 'seat-0', 1, 2).state
        self.assertEqual(self._names(state, 'seat-0'), ('decline',))
        with self.assertRaises(ValueError):
            self._act(state, 'seat-0', 'buy')

    def test_a_double_that_lands_on_a_property_still_grants_the_extra_roll(self):
        state = self._place(self._open(), 'seat-0', 4)
        rolled = self._roll(state, 'seat-0', 1, 1)
        self.assertEqual(rolled.state['players']['seat-0']['position'], 6)
        self.assertEqual(rolled.state['phase'], rules.PHASE_AWAITING_DECISION)
        self.assertIs(rolled.state['extra_roll'], True)
        bought = self._act(rolled.state, 'seat-0', 'buy')
        self.assertEqual(bought.state['phase'], rules.PHASE_AWAITING_ROLL)
        self.assertEqual(bought.state['turn'], 'seat-0')
        self.assertIs(bought.state['extra_roll'], False)
        self.assertEqual(self._names(bought.state, 'seat-0'), ('roll',))

    def test_declining_a_double_landing_also_grants_the_extra_roll(self):
        state = self._place(self._open(), 'seat-0', 4)
        rolled = self._roll(state, 'seat-0', 1, 1)
        declined = self._act(rolled.state, 'seat-0', 'decline')
        self.assertEqual(declined.state['phase'], rules.PHASE_AWAITING_ROLL)
        self.assertEqual(declined.state['turn'], 'seat-0')


class MonopolyRentTests(MonopolyRulesTestCase):
    def test_a_street_charges_its_base_rent(self):
        state = self._give(self._open(first='seat-1'), 3, 'seat-0')
        transition = self._roll(state, 'seat-1', 1, 2)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1504)
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1496)
        self.assertIn(
            (
                'rent_paid',
                'seat-1',
                {'from': 'seat-1', 'to': 'seat-0', 'space': 3, 'amount': 4},
            ),
            self._facts(transition),
        )

    def test_a_complete_group_charges_the_doubled_rent(self):
        state = self._give(
            self._give(self._open(first='seat-1'), 1, 'seat-0'), 3, 'seat-0'
        )
        transition = self._roll(state, 'seat-1', 1, 2)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1508)
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1492)

    def test_an_incomplete_group_charges_the_base_rent(self):
        state = self._give(self._open(first='seat-1'), 3, 'seat-0')
        transition = self._roll(state, 'seat-1', 1, 2)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1504)

    def test_railroad_rent_scales_with_the_number_owned(self):
        for count, rent in ((1, 25), (2, 50), (3, 100), (4, 200)):
            state = self._open(first='seat-1')
            for index in board.RAILROAD_INDEXES[:count]:
                state = self._give(state, index, 'seat-0')
            with self.subTest(count=count):
                transition = self._roll(state, 'seat-1', 2, 3)
                self.assertEqual(
                    transition.state['players']['seat-0']['cash'], 1500 + rent
                )
                self.assertEqual(
                    transition.state['players']['seat-1']['cash'], 1500 - rent
                )

    def test_utility_rent_is_four_times_the_roll_with_one_owned(self):
        state = self._give(
            self._place(self._open(first='seat-1'), 'seat-1', 7), 12, 'seat-0'
        )
        transition = self._roll(state, 'seat-1', 3, 2)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1520)
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1480)

    def test_utility_rent_is_ten_times_the_roll_with_both_owned(self):
        state = self._place(self._open(first='seat-1'), 'seat-1', 7)
        state = self._give(self._give(state, 12, 'seat-0'), 28, 'seat-0')
        transition = self._roll(state, 'seat-1', 3, 2)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1550)
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1450)

    def test_an_owner_never_pays_rent_to_itself(self):
        state = self._give(self._open(), 3, 'seat-0')
        transition = self._roll(state, 'seat-0', 1, 2)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1500)
        self.assertEqual(transition.state['phase'], rules.PHASE_MANAGING)


class MonopolyTaxTests(MonopolyRulesTestCase):
    def test_income_tax_offers_the_two_printed_options(self):
        transition = self._roll(self._open(), 'seat-0', 1, 3)
        self.assertEqual(transition.state['phase'], rules.PHASE_AWAITING_DECISION)
        self.assertEqual(transition.state['pending'], {'kind': 'income_tax', 'space': 4})
        self.assertEqual(
            self._names(transition.state, 'seat-0'),
            ('pay_income_tax_fixed', 'pay_income_tax_percent'),
        )

    def test_the_fixed_income_tax_costs_two_hundred(self):
        state = self._roll(self._open(), 'seat-0', 1, 3).state
        transition = self._act(state, 'seat-0', 'pay_income_tax_fixed')
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1300)
        self.assertEqual(transition.state['phase'], rules.PHASE_MANAGING)
        self.assertEqual(
            self._facts(transition),
            (('tax_paid', 'seat-0', {'space': 4, 'amount': 200, 'option': 'fixed'}),),
        )

    def test_the_percent_income_tax_is_ten_percent_of_total_worth(self):
        state = self._give(self._give(self._open(), 3, 'seat-0'), 5, 'seat-0')
        state = self._roll(state, 'seat-0', 1, 3).state
        self.assertEqual(rules.total_worth(state, 'seat-0'), 1760)
        transition = self._act(state, 'seat-0', 'pay_income_tax_percent')
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1324)
        self.assertEqual(
            self._facts(transition),
            (('tax_paid', 'seat-0', {'space': 4, 'amount': 176, 'option': 'percent'}),),
        )

    def test_the_percent_rounds_up_to_the_whole_dollar(self):
        state = self._cash(self._open(), 'seat-0', 1505)
        state = self._give(self._give(state, 3, 'seat-0'), 5, 'seat-0')
        state = self._roll(state, 'seat-0', 1, 3).state
        self.assertEqual(rules.total_worth(state, 'seat-0'), 1765)
        transition = self._act(state, 'seat-0', 'pay_income_tax_percent')
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1328)

    def test_luxury_tax_costs_seventy_five_without_a_decision(self):
        state = self._place(self._open(), 'seat-0', 33)
        transition = self._roll(state, 'seat-0', 2, 3)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1425)
        self.assertEqual(transition.state['phase'], rules.PHASE_MANAGING)
        self.assertIn(
            ('tax_paid', 'seat-0', {'space': 38, 'amount': 75, 'option': 'fixed'}),
            self._facts(transition),
        )

    def test_total_worth_is_cash_plus_the_printed_property_prices(self):
        state = self._give(self._give(self._open(), 3, 'seat-0'), 39, 'seat-0')
        self.assertEqual(rules.total_worth(state, 'seat-0'), 1500 + 60 + 400)
        self.assertEqual(rules.total_worth(state, 'seat-1'), 1500)


class MonopolyBankruptcyTests(MonopolyRulesTestCase):
    def _boardwalk_rent_scene(self, seats=('seat-0', 'seat-1')):
        """``seat-0`` lands on ``seat-1``'s Boardwalk holding only $10."""
        state = rules.initial_state(seats, 'seat-0')
        state = self._place(state, 'seat-0', 36)
        state = self._cash(state, 'seat-0', 10)
        state = self._give(state, 3, 'seat-0')
        return self._give(state, 39, 'seat-1')

    def test_an_unaffordable_rent_transfers_everything_to_the_creditor(self):
        transition = self._roll(self._boardwalk_rent_scene(), 'seat-0', 1, 2)
        debtor = transition.state['players']['seat-0']
        creditor = transition.state['players']['seat-1']
        self.assertIs(debtor['eliminated'], True)
        self.assertEqual(debtor['cash'], 0)
        self.assertEqual(debtor['properties'], [])
        self.assertEqual(creditor['cash'], 1510)
        self.assertEqual(sorted(creditor['properties']), [3, 39])
        self.assertEqual(
            transition.state['owners'], {'3': 'seat-1', '39': 'seat-1'}
        )
        self.assertIn(
            ('bankrupt', 'seat-0', {'creditor': 'seat-1'}), self._facts(transition)
        )

    def test_an_unaffordable_bank_debt_leaves_the_properties_unowned(self):
        state = self._place(self._open(), 'seat-0', 33)
        state = self._cash(state, 'seat-0', 10)
        state = self._give(state, 3, 'seat-0')
        transition = self._roll(state, 'seat-0', 2, 3)
        self.assertIs(transition.state['players']['seat-0']['eliminated'], True)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 0)
        self.assertEqual(transition.state['owners'], {})
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1500)
        self.assertIn(('bankrupt', 'seat-0', {'creditor': None}), self._facts(transition))

    def test_an_eliminated_seat_never_acts_again(self):
        scene = self._boardwalk_rent_scene(('seat-0', 'seat-1', 'seat-2'))
        transition = self._roll(scene, 'seat-0', 1, 2)
        self.assertEqual(self._names(transition.state, 'seat-0'), ())
        self.assertEqual(transition.state['turn'], 'seat-1')
        self.assertEqual(self._names(transition.state, 'seat-1'), ('roll',))


class MonopolyFinishTests(MonopolyRulesTestCase):
    def test_a_two_seat_match_ends_with_the_last_solvent_seat(self):
        state = self._place(self._open(), 'seat-0', 36)
        state = self._cash(state, 'seat-0', 10)
        state = self._give(state, 39, 'seat-1')
        transition = self._roll(state, 'seat-0', 1, 2)
        self.assertIs(rules.is_finished(transition.state), True)
        self.assertEqual(
            rules.outcome(transition.state),
            Outcome(winner_seat='seat-1', reason='last_solvent'),
        )
        self.assertIn(
            ('match_finished', None, {'winner': 'seat-1'}), self._facts(transition)
        )
        self.assertIsNone(transition.state['turn'])
        self.assertEqual(self._names(transition.state, 'seat-1'), ())

    def test_a_three_seat_match_keeps_playing_after_one_elimination(self):
        state = rules.initial_state(('seat-0', 'seat-1', 'seat-2'), 'seat-0')
        state = self._place(state, 'seat-0', 36)
        state = self._cash(state, 'seat-0', 10)
        state = self._give(state, 39, 'seat-1')
        transition = self._roll(state, 'seat-0', 1, 2)
        self.assertIs(rules.is_finished(transition.state), False)
        self.assertIsNone(rules.outcome(transition.state))
        self.assertEqual(transition.state['turn'], 'seat-1')
        self.assertEqual(transition.state['phase'], rules.PHASE_AWAITING_ROLL)
        self.assertEqual(self._names(transition.state, 'seat-1'), ('roll',))

    def test_a_running_match_has_no_outcome(self):
        self.assertIsNone(rules.outcome(self._open()))
        self.assertIs(rules.is_finished(self._open()), False)

    def test_a_running_transition_never_announces_a_finish(self):
        state = self._place(self._open(), 'seat-0', 15)
        transition = self._roll(state, 'seat-0', 2, 3)
        self.assertNotIn(
            'match_finished', [fact[0] for fact in self._facts(transition)]
        )


class MonopolyAbandonTests(MonopolyRulesTestCase):
    def test_abandon_frees_the_properties_and_eliminates_the_seat(self):
        state = self._give(self._open(), 3, 'seat-1')
        state = self._cash(state, 'seat-1', 200)
        transition = rules.abandon(state, 'seat-1')
        abandoned = transition.state['players']['seat-1']
        self.assertIs(abandoned['eliminated'], True)
        self.assertEqual(abandoned['cash'], 0)
        self.assertEqual(abandoned['properties'], [])
        self.assertEqual(transition.state['owners'], {})
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1500)
        self.assertIs(transition.state['ended_by_abandon'], True)
        self.assertEqual(transition.state['abandoned_seat'], 'seat-1')
        self.assertEqual(
            rules.outcome(transition.state),
            Outcome(winner_seat='seat-0', reason='win_by_abandon'),
        )
        self.assertIn(
            ('match_finished', None, {'winner': 'seat-0'}), self._facts(transition)
        )

    def test_abandon_of_a_three_seat_match_keeps_it_running(self):
        state = rules.initial_state(('seat-0', 'seat-1', 'seat-2'), 'seat-0')
        state = self._give(state, 3, 'seat-1')
        transition = rules.abandon(state, 'seat-1')
        self.assertIs(rules.is_finished(transition.state), False)
        self.assertIs(transition.state['ended_by_abandon'], False)
        self.assertEqual(transition.state['turn'], 'seat-0')
        self.assertEqual(transition.state['abandoned_seat'], 'seat-1')
        self.assertNotIn(
            'match_finished', [fact[0] for fact in self._facts(transition)]
        )

    def test_a_repeated_abandon_of_the_same_seat_is_tolerated(self):
        state = rules.initial_state(('seat-0', 'seat-1', 'seat-2'), 'seat-0')
        state = self._give(state, 3, 'seat-1')
        state = self._cash(state, 'seat-1', 200)
        once = rules.abandon(state, 'seat-1').state
        twice = rules.abandon(once, 'seat-1').state
        self.assertEqual(twice['players']['seat-1'], once['players']['seat-1'])
        self.assertEqual(twice['owners'], once['owners'])
        self.assertEqual(twice['players']['seat-0']['cash'], 1500)

    def test_abandon_of_the_seat_on_turn_passes_the_turn(self):
        state = rules.initial_state(('seat-0', 'seat-1', 'seat-2'), 'seat-0')
        transition = rules.abandon(state, 'seat-0')
        self.assertEqual(transition.state['turn'], 'seat-1')
        self.assertEqual(transition.state['phase'], rules.PHASE_AWAITING_ROLL)

    def test_abandon_is_rejected_on_a_finished_match(self):
        state = self._give(self._open(), 3, 'seat-1')
        finished = rules.abandon(state, 'seat-1').state
        with self.assertRaises(ValueError):
            rules.abandon(finished, 'seat-0')
        with self.assertRaises(ValueError):
            rules.abandon(self._open(), 'seat-9')
