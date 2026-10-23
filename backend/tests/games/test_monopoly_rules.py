"""Pure-rule tests for the ``monopoly`` rules engine (S5-S12).

``SimpleTestCase`` only provides the runner so the rules can be exercised
without the database. The dice are scripted, one die face per value, so every
transition is deterministic. Each test asserts the full observable effect of
the rule it covers: the resulting state, the legal actions, the emitted facts
and, where the rule ends the match, the resolved outcome.
"""

import copy
import json

from django.test import SimpleTestCase

from modules.games.contracts import Action, Outcome
from modules.games.monopoly import board, cards, deeds, rules


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

    def _open(self, seats=('seat-0', 'seat-1'), first='seat-0', decks=None):
        return rules.initial_state(seats, first, decks)

    def _top_card(self, state, deck, card_id):
        """Put ``card_id`` on top of ``deck`` so the next draw turns it up."""
        state = copy.deepcopy(state)
        state['decks'][deck] = [card_id] + [
            candidate for candidate in state['decks'][deck] if candidate != card_id
        ]
        return state

    def _land_on_card(self, state, seat, deck):
        """Please ``seat`` on a card space of ``deck`` without crossing GO."""
        index = 7 if deck == cards.CHANCE else 17
        return self._roll(self._place(state, seat, index - 3), seat, 1, 2)

    def _roll(self, state, seat, *faces):
        return rules.apply_action(state, seat, Action(name='roll'), ScriptedRng(*faces))

    def _act(self, state, seat, name):
        return rules.apply_action(state, seat, Action(name=name), None)

    def _confirm(self, state, seat='seat-0', *faces):
        """Confirm the pending card, with the dice its effect may still need."""
        return rules.apply_action(
            state, seat, Action(name='confirm_card'), ScriptedRng(*faces)
        )

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

    def _options(self, state, seat, name):
        """The options of the first action of ``name`` the seat is offered."""
        for spec in rules.legal_actions(state, seat):
            if spec.name == name:
                return spec.options
        return ()

    def _mortgaged(self, state, *indexes):
        """Force the mortgage state of ``indexes``, for scenes that need it."""
        state = copy.deepcopy(state)
        mortgaged = dict(state.get('mortgaged') or {})
        for index in indexes:
            mortgaged[str(index)] = True
        state['mortgaged'] = mortgaged
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
                        'jail_cards': [],
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

    def test_the_phase_constants_are_a_two_sided_contract(self):
        """The frontend parser mirrors this list, so a new phase costs two edits.

        ``view.ts`` recognizes a payload only when its ``phase`` is one of these
        names. Adding a phase here without adding it there makes every view
        during that phase unrecognizable, which is exactly what the auction did
        before ``awaiting_bid`` reached the parser: the whole match screen,
        auction included, fell back to the "vista de partida no disponible"
        notice. Pinning the set turns that into a deliberate change.
        """
        phases = {
            name: getattr(rules, name)
            for name in dir(rules)
            if name.startswith('PHASE_')
        }
        self.assertEqual(
            phases,
            {
                'PHASE_AWAITING_ROLL': 'awaiting_roll',
                'PHASE_AWAITING_DECISION': 'awaiting_decision',
                'PHASE_MANAGING': 'managing',
                'PHASE_AWAITING_BID': 'awaiting_bid',
                'PHASE_RAISING_CASH': 'raising_cash',
            },
        )


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
        # Free Parking and the seat's own property: neither landing asks for a
        # decision, so the roll is the only thing under test.
        state = self._give(self._place(self._open(), 'seat-0', 18), 23, 'seat-0')
        first = self._roll(state, 'seat-0', 1, 1)
        self.assertEqual(first.state['players']['seat-0']['position'], 20)
        self.assertEqual(first.state['doubles_count'], 1)
        self.assertEqual(first.state['turn'], 'seat-0')
        self.assertEqual(first.state['phase'], rules.PHASE_AWAITING_ROLL)
        self.assertEqual(self._names(first.state, 'seat-0'), ('roll', 'propose'))
        second = self._roll(first.state, 'seat-0', 1, 2)
        self.assertEqual(second.state['players']['seat-0']['position'], 23)
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

    def test_each_card_space_draws_from_its_own_deck(self):
        """Increment 2 repeals the increment-1 stop: a card space now draws."""
        for start, faces, deck in (
            (0, (1, 1), cards.COMMUNITY_CHEST),
            (4, (1, 2), cards.CHANCE),
        ):
            with self.subTest(deck=deck):
                state = self._place(self._open(), 'seat-0', start)
                transition = self._roll(state, 'seat-0', *faces)

                self.assertEqual(transition.state['last_card']['deck'], deck)
                self.assertIn(
                    'card_drawn', [fact[0] for fact in self._facts(transition)]
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
        self.assertEqual(self._names(stopped, 'seat-0'), ('end_turn', 'propose'))
        ended = self._act(stopped, 'seat-0', 'end_turn')
        self.assertEqual(ended.state['turn'], 'seat-1')
        self.assertEqual(ended.state['phase'], rules.PHASE_AWAITING_ROLL)
        self.assertIsNone(ended.state['last_roll'])
        self.assertEqual(ended.state['doubles_count'], 0)
        self.assertIsNone(ended.state['pending'])
        self.assertEqual(self._facts(ended), (('turn_ended', 'seat-0', {}),))

    def test_an_idle_seat_is_offered_the_trade_action_only(self):
        # Every solvent seat is active while the match runs: seat-1 may initiate
        # a trade out of turn, but the roll still belongs to seat-0.
        state = self._open()
        self.assertEqual(self._names(state, 'seat-1'), ('propose',))
        self.assertEqual(self._names(state, 'seat-0'), ('roll', 'propose'))

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
        for jail_turns, expected in (
            (0, ('roll', 'pay_jail_fine', 'propose')),
            (1, ('roll', 'pay_jail_fine', 'propose')),
            (2, ('roll', 'propose')),
        ):
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
        self.assertEqual(self._names(poor, 'seat-0'), ('roll', 'propose'))
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
        self.assertEqual(declined.state['phase'], rules.PHASE_AWAITING_BID)
        unsold = self._act(
            self._act(declined.state, 'seat-0', 'pass').state, 'seat-1', 'pass'
        ).state
        self.assertEqual(unsold['phase'], rules.PHASE_MANAGING)
        ended = self._act(unsold, 'seat-0', 'end_turn')
        self.assertEqual(ended.state['turn'], 'seat-1')

    def test_a_jailed_seat_keeps_collecting_rent(self):
        state = self._jailed(first='seat-1')
        state = self._give(state, 3, 'seat-0')
        transition = self._roll(state, 'seat-1', 1, 2)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1504)
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1496)

    def test_an_unaffordable_fine_opens_the_debt_window(self):
        state = self._jailed(jail_turns=2)
        state = self._cash(state, 'seat-0', 10)
        state = self._give(state, 3, 'seat-0')
        transition = self._roll(state, 'seat-0', 2, 3)
        self.assertEqual(transition.state['phase'], rules.PHASE_RAISING_CASH)
        self.assertIs(transition.state['players']['seat-0']['in_jail'], True)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 10)
        self.assertEqual(transition.state['debt']['creditor'], None)
        self.assertEqual(transition.state['debt']['amount'], rules.JAIL_FINE)
        self.assertIn(
            ('debt_incurred', 'seat-0', {'amount': rules.JAIL_FINE, 'creditor': None}),
            self._facts(transition),
        )
        self.assertNotIn(
            'bankrupt', [fact[0] for fact in self._facts(transition)]
        )


class MonopolyPurchaseTests(MonopolyRulesTestCase):
    def test_landing_on_an_unowned_property_offers_buy_and_decline(self):
        transition = self._roll(self._open(), 'seat-0', 1, 2)
        self.assertEqual(transition.state['phase'], rules.PHASE_AWAITING_DECISION)
        self.assertEqual(transition.state['pending'], {'kind': 'purchase', 'space': 3})
        self.assertEqual(
            self._names(transition.state, 'seat-0'),
            ('buy', 'decline', 'propose'),
        )
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

    def test_declining_opens_an_auction_instead_of_freeing_the_space(self):
        state = self._roll(self._open(), 'seat-0', 1, 2).state

        transition = self._act(state, 'seat-0', 'decline')

        self.assertEqual(transition.state['owners'], {})
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1500)
        self.assertEqual(transition.state['players']['seat-0']['properties'], [])
        self.assertEqual(transition.state['phase'], rules.PHASE_AWAITING_BID)
        self.assertEqual(
            transition.state['auction'],
            {'space': 3, 'high_bid': 0, 'high_bidder': None, 'passed': []},
        )
        self.assertEqual(
            self._facts(transition),
            (
                ('purchase_declined', 'seat-0', {'space': 3}),
                ('auction_opened', 'seat-0', {'space': 3}),
            ),
        )

    def test_buy_is_not_offered_without_the_cash(self):
        state = self._roll(self._cash(self._open(), 'seat-0', 10), 'seat-0', 1, 2).state
        self.assertEqual(self._names(state, 'seat-0'), ('decline', 'propose'))
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
        self.assertEqual(self._names(bought.state, 'seat-0'), ('roll', 'propose'))

    def test_declining_a_double_landing_grants_the_extra_roll_after_the_auction(self):
        state = self._place(self._open(), 'seat-0', 4)
        rolled = self._roll(state, 'seat-0', 1, 1)
        declined = self._act(rolled.state, 'seat-0', 'decline')
        self.assertIs(declined.state['extra_roll'], True)
        self.assertEqual(declined.state['phase'], rules.PHASE_AWAITING_BID)

        unsold = self._act(
            self._act(declined.state, 'seat-0', 'pass').state, 'seat-1', 'pass'
        ).state

        self.assertEqual(unsold['phase'], rules.PHASE_AWAITING_ROLL)
        self.assertEqual(unsold['turn'], 'seat-0')


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
            ('pay_income_tax_fixed', 'pay_income_tax_percent', 'propose'),
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


class MonopolyBuildingTests(MonopolyRulesTestCase):
    """House and hotel building, the bank stock and the level rent (S2-S7)."""

    def _own_group(self, state, indexes, seat='seat-0'):
        for index in indexes:
            state = self._give(state, index, seat)
        return state

    def _buildings(self, state, levels):
        state = copy.deepcopy(state)
        buildings = dict(state.get('buildings') or {})
        for index, level in levels.items():
            if level == 0:
                buildings.pop(str(index), None)
            else:
                buildings[str(index)] = level
        state['buildings'] = buildings
        return state

    def _bank(self, state, houses, hotels):
        state = copy.deepcopy(state)
        state['bank'] = {'houses': houses, 'hotels': hotels}
        return state

    def _managing(self, state, seat='seat-0'):
        state = copy.deepcopy(state)
        state['phase'] = rules.PHASE_MANAGING
        state['turn'] = seat
        return state

    def _rolling(self, state, seat='seat-1'):
        state = copy.deepcopy(state)
        state['phase'] = rules.PHASE_AWAITING_ROLL
        state['turn'] = seat
        return state

    def _scene(self, levels=None, cash=1500, houses=None, hotels=None):
        """A managing seat holding complete brown, with a consistent bank stock."""
        levels = dict(levels or {})
        state = self._managing(self._own_group(self._open(), (1, 3)))
        state = self._cash(state, 'seat-0', cash)
        state = self._buildings(state, levels)
        on_board_houses = sum(
            level for level in levels.values() if level < deeds.HOTEL_LEVEL
        )
        on_board_hotels = sum(
            1 for level in levels.values() if level == deeds.HOTEL_LEVEL
        )
        return self._bank(
            state,
            rules.STARTING_HOUSES - on_board_houses if houses is None else houses,
            rules.STARTING_HOTELS - on_board_hotels if hotels is None else hotels,
        )

    def _assert_bank_invariants(self, state):
        """The two S2 invariants: no house and no hotel is created or lost."""
        levels = tuple((state.get('buildings') or {}).values())
        houses = sum(level for level in levels if level < deeds.HOTEL_LEVEL)
        hotels = sum(1 for level in levels if level == deeds.HOTEL_LEVEL)
        self.assertEqual(state['bank']['houses'] + houses, rules.STARTING_HOUSES)
        self.assertEqual(state['bank']['hotels'] + hotels, rules.STARTING_HOTELS)

    def test_build_and_sell_are_only_offered_in_the_managing_phase(self):
        state = self._own_group(self._open(), (1, 3))
        self.assertEqual(self._names(state, 'seat-0'), ('roll', 'propose'))
        with self.assertRaises(ValueError):
            rules.apply_action(state, 'seat-0', Action(name='build', value='1'), None)
        with self.assertRaises(ValueError):
            rules.apply_action(state, 'seat-0', Action(name='sell', value='1'), None)

        pending = self._roll(self._open(), 'seat-0', 1, 2).state
        self.assertEqual(self._names(pending, 'seat-0'), ('buy', 'decline', 'propose'))
        with self.assertRaises(ValueError):
            rules.apply_action(pending, 'seat-0', Action(name='build', value='1'), None)
        with self.assertRaises(ValueError):
            rules.apply_action(pending, 'seat-0', Action(name='sell', value='1'), None)

    def test_a_build_needs_the_whole_colour_group(self):
        state = self._managing(self._give(self._open(), 3, 'seat-0'))
        self.assertEqual(self._names(state, 'seat-0'), ('mortgage', 'end_turn', 'propose'))
        with self.assertRaises(ValueError):
            rules.apply_action(state, 'seat-0', Action(name='build', value='3'), None)

    def test_build_is_even_so_only_the_group_minimum_is_offered(self):
        state = self._scene(levels={1: 1})
        self.assertEqual(self._options(state, 'seat-0', 'build'), ('3',))
        with self.assertRaises(ValueError):
            rules.apply_action(state, 'seat-0', Action(name='build', value='1'), None)

    def test_a_house_costs_the_printed_price_and_takes_a_house_from_the_bank(self):
        state = self._scene()

        transition = rules.apply_action(
            state, 'seat-0', Action(name='build', value='1'), None
        )

        self.assertEqual(transition.state['players']['seat-0']['cash'], 1450)
        self.assertEqual(transition.state['buildings'], {'1': 1})
        self.assertEqual(transition.state['bank'], {'houses': 31, 'hotels': 12})
        self.assertEqual(
            self._facts(transition),
            (('building_bought', 'seat-0', {'space': 1, 'level': 1, 'price': 50}),),
        )
        self._assert_bank_invariants(transition.state)

    def test_a_house_cannot_be_built_without_a_house_in_the_bank(self):
        state = self._scene(houses=0)
        self.assertEqual(self._names(state, 'seat-0'), ('mortgage', 'end_turn', 'propose'))
        with self.assertRaises(ValueError):
            rules.apply_action(state, 'seat-0', Action(name='build', value='1'), None)

    def test_a_hotel_needs_every_property_of_the_group_at_four_houses(self):
        state = self._scene(levels={1: 4, 3: 3})
        # The street at four is not the group minimum until its sibling catches
        # up, which is exactly the printed "four houses on each property" rule.
        self.assertEqual(self._options(state, 'seat-0', 'build'), ('3',))
        with self.assertRaises(ValueError):
            rules.apply_action(state, 'seat-0', Action(name='build', value='1'), None)

    def test_a_hotel_cannot_be_built_without_a_hotel_in_the_bank(self):
        state = self._scene(levels={1: 4, 3: 4}, hotels=0)
        self.assertEqual(self._options(state, 'seat-0', 'build'), ())
        with self.assertRaises(ValueError):
            rules.apply_action(state, 'seat-0', Action(name='build', value='1'), None)

    def test_a_hotel_returns_its_four_houses_to_the_bank(self):
        state = self._scene(levels={1: 4, 3: 4})

        transition = rules.apply_action(
            state, 'seat-0', Action(name='build', value='1'), None
        )

        self.assertEqual(transition.state['players']['seat-0']['cash'], 1450)
        self.assertEqual(transition.state['buildings'], {'1': 5, '3': 4})
        self.assertEqual(transition.state['bank'], {'houses': 28, 'hotels': 11})
        self.assertEqual(
            self._facts(transition),
            (('building_bought', 'seat-0', {'space': 1, 'level': 5, 'price': 50}),),
        )
        self._assert_bank_invariants(transition.state)

    def test_a_build_is_not_offered_without_the_cash(self):
        state = self._scene(cash=49)
        self.assertEqual(self._names(state, 'seat-0'), ('mortgage', 'end_turn', 'propose'))
        with self.assertRaises(ValueError):
            rules.apply_action(state, 'seat-0', Action(name='build', value='1'), None)

    def test_build_is_never_offered_to_another_seat(self):
        state = self._scene()
        # The other seat is active to negotiate, but build stays with the turn.
        self.assertEqual(self._names(state, 'seat-1'), ('propose',))
        with self.assertRaises(ValueError):
            rules.apply_action(state, 'seat-1', Action(name='build', value='1'), None)

    def test_build_options_are_own_group_indexes_in_board_order(self):
        state = self._managing(self._own_group(self._open(), (6, 8, 9)))
        self.assertEqual(self._options(state, 'seat-0', 'build'), ('6', '8', '9'))

    def test_a_build_outside_the_offered_options_is_rejected(self):
        state = self._scene()
        for value in ('2', '5', '40', 'x'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    rules.apply_action(
                        state, 'seat-0', Action(name='build', value=value), None
                    )

    def test_sell_only_offers_the_group_maximum(self):
        state = self._scene(levels={1: 2, 3: 1})
        self.assertEqual(self._options(state, 'seat-0', 'sell'), ('1',))
        with self.assertRaises(ValueError):
            rules.apply_action(state, 'seat-0', Action(name='sell', value='3'), None)

    def test_selling_a_house_pays_half_the_cost_and_returns_the_house(self):
        state = self._scene(levels={1: 1})

        transition = rules.apply_action(
            state, 'seat-0', Action(name='sell', value='1'), None
        )

        self.assertEqual(transition.state['players']['seat-0']['cash'], 1525)
        self.assertEqual(transition.state['buildings'], {})
        self.assertEqual(transition.state['bank'], {'houses': 32, 'hotels': 12})
        self.assertEqual(
            self._facts(transition),
            (('building_sold', 'seat-0', {'space': 1, 'level': 0, 'price': 25}),),
        )
        self._assert_bank_invariants(transition.state)

    def test_sell_is_not_offered_for_an_unbuilt_property(self):
        state = self._scene()
        self.assertEqual(self._options(state, 'seat-0', 'sell'), ())
        with self.assertRaises(ValueError):
            rules.apply_action(state, 'seat-0', Action(name='sell', value='1'), None)

    def test_sell_is_never_offered_to_another_seat(self):
        state = self._scene(levels={1: 1})
        self.assertEqual(self._names(state, 'seat-1'), ('propose',))
        with self.assertRaises(ValueError):
            rules.apply_action(state, 'seat-1', Action(name='sell', value='1'), None)

    def test_selling_a_hotel_returns_the_hotel_and_leaves_four_houses(self):
        state = self._scene(levels={1: 5, 3: 5})

        transition = rules.apply_action(
            state, 'seat-0', Action(name='sell', value='1'), None
        )

        self.assertEqual(transition.state['players']['seat-0']['cash'], 1525)
        self.assertEqual(transition.state['buildings'], {'1': 4, '3': 5})
        self.assertEqual(transition.state['bank'], {'houses': 28, 'hotels': 11})
        self.assertEqual(
            self._facts(transition),
            (('building_sold', 'seat-0', {'space': 1, 'level': 4, 'price': 25}),),
        )
        self._assert_bank_invariants(transition.state)

    def test_selling_a_hotel_needs_four_houses_in_the_bank(self):
        state = self._scene(levels={1: 5, 3: 5}, houses=3)
        self.assertEqual(self._options(state, 'seat-0', 'sell'), ())
        with self.assertRaises(ValueError):
            rules.apply_action(state, 'seat-0', Action(name='sell', value='1'), None)

    def test_sell_options_are_own_group_indexes_in_board_order(self):
        state = self._managing(self._own_group(self._open(), (6, 8, 9)))
        state = self._buildings(state, {6: 1, 8: 1, 9: 1})
        state = self._bank(state, 29, 12)
        self.assertEqual(self._options(state, 'seat-0', 'sell'), ('6', '8', '9'))

    def test_a_sell_outside_the_offered_options_is_rejected(self):
        state = self._scene(levels={1: 2, 3: 1})
        for value in ('3', '39', 'x'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    rules.apply_action(
                        state, 'seat-0', Action(name='sell', value=value), None
                    )

    def test_the_bank_stock_is_conserved_through_a_full_build_and_sell_cycle(self):
        state = self._scene()

        for value in ('1', '3') * 5:
            state = rules.apply_action(
                state, 'seat-0', Action(name='build', value=value), None
            ).state
            self._assert_bank_invariants(state)
        self.assertEqual(state['buildings'], {'1': 5, '3': 5})
        self.assertEqual(state['bank'], {'houses': 32, 'hotels': 10})

        for value in ('1', '3') * 5:
            state = rules.apply_action(
                state, 'seat-0', Action(name='sell', value=value), None
            ).state
            self._assert_bank_invariants(state)
        self.assertEqual(state['buildings'], {})
        self.assertEqual(state['bank'], {'houses': 32, 'hotels': 12})
        self.assertEqual(state['players']['seat-0']['cash'], 1250)

    def test_a_street_charges_the_rent_of_its_development_level(self):
        state = self._rolling(self._scene(levels={1: 0, 3: 1}))
        state = self._place(state, 'seat-1', 0)

        transition = self._roll(state, 'seat-1', 1, 2)

        self.assertEqual(transition.state['players']['seat-0']['cash'], 1520)
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1480)
        self.assertIn(
            (
                'rent_paid',
                'seat-1',
                {'from': 'seat-1', 'to': 'seat-0', 'space': 3, 'amount': 20},
            ),
            self._facts(transition),
        )

    def test_an_unimproved_lot_still_charges_the_set_rent_beside_houses(self):
        """The set rent belongs to the level-0 street, never to the group (S6)."""
        state = self._rolling(self._scene(levels={1: 0, 3: 1}))
        state = self._place(state, 'seat-1', 38)

        transition = self._roll(state, 'seat-1', 1, 2)

        # Mediterranean at level 0 charges its doubled rent even though its
        # sibling holds a house; the landing also crossed GO.
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1504)
        self.assertIn(
            (
                'rent_paid',
                'seat-1',
                {'from': 'seat-1', 'to': 'seat-0', 'space': 1, 'amount': 4},
            ),
            self._facts(transition),
        )

    def test_a_hotel_charges_the_hotel_rent(self):
        state = self._rolling(self._scene(levels={1: 0, 3: 5}))
        state = self._place(state, 'seat-1', 0)

        transition = self._roll(state, 'seat-1', 1, 2)

        self.assertEqual(transition.state['players']['seat-0']['cash'], 1950)
        self.assertIn(
            (
                'rent_paid',
                'seat-1',
                {'from': 'seat-1', 'to': 'seat-0', 'space': 3, 'amount': 450},
            ),
            self._facts(transition),
        )

    def test_total_worth_counts_the_buildings_a_hotel_as_five_houses(self):
        state = self._scene(levels={1: 1, 3: 5})
        self.assertEqual(
            rules.total_worth(state, 'seat-0'), 1500 + 60 + 60 + 50 + 250
        )

    def test_bankruptcy_to_a_player_returns_the_buildings_and_pays_half(self):
        state = self._rolling(self._scene(levels={1: 1, 3: 2}), 'seat-0')
        state = self._cash(state, 'seat-0', 10)
        state = self._give(state, 39, 'seat-1')
        state = self._place(state, 'seat-0', 36)

        opened = self._roll(state, 'seat-0', 1, 2)
        self.assertEqual(opened.state['phase'], rules.PHASE_RAISING_CASH)
        transition = self._act(opened.state, 'seat-0', 'declare_bankruptcy')

        debtor = transition.state['players']['seat-0']
        self.assertIs(debtor['eliminated'], True)
        self.assertEqual(debtor['cash'], 0)
        self.assertEqual(transition.state['buildings'], {})
        self.assertEqual(transition.state['bank'], {'houses': 32, 'hotels': 12})
        # Everything the debtor had, plus half of the 50 + 100 it had built.
        self.assertEqual(
            transition.state['players']['seat-1']['cash'], 1500 + 10 + 75
        )
        self.assertEqual(
            sorted(transition.state['players']['seat-1']['properties']), [1, 3, 39]
        )
        self.assertEqual(
            transition.state['owners'],
            {'1': 'seat-1', '3': 'seat-1', '39': 'seat-1'},
        )
        self._assert_bank_invariants(transition.state)

    def test_bankruptcy_to_the_bank_returns_the_buildings_without_payment(self):
        state = self._rolling(self._scene(levels={1: 1, 3: 2}), 'seat-0')
        state = self._cash(state, 'seat-0', 10)
        state = self._place(state, 'seat-0', 33)

        opened = self._roll(state, 'seat-0', 2, 3)
        self.assertEqual(opened.state['phase'], rules.PHASE_RAISING_CASH)
        transition = self._act(opened.state, 'seat-0', 'declare_bankruptcy')

        self.assertIs(transition.state['players']['seat-0']['eliminated'], True)
        self.assertEqual(transition.state['buildings'], {})
        self.assertEqual(transition.state['bank'], {'houses': 32, 'hotels': 12})
        self.assertEqual(transition.state['owners'], {})
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1500)
        self._assert_bank_invariants(transition.state)

    def test_abandon_returns_the_buildings_to_the_bank(self):
        state = rules.initial_state(('seat-0', 'seat-1', 'seat-2'), 'seat-0')
        state = self._own_group(state, (1, 3), seat='seat-1')
        state = self._buildings(state, {1: 2, 3: 5})
        state = self._bank(state, 30, 11)

        transition = rules.abandon(state, 'seat-1')

        self.assertEqual(transition.state['buildings'], {})
        self.assertEqual(transition.state['bank'], {'houses': 32, 'hotels': 12})
        self.assertEqual(transition.state['owners'], {})
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1500)
        self._assert_bank_invariants(transition.state)

    def test_a_repairs_card_charges_per_house_and_per_hotel(self):
        state = self._rolling(self._scene(levels={1: 2, 3: 5}), 'seat-0')
        state = self._place(state, 'seat-0', 4)
        state = self._top_card(state, cards.CHANCE, 'chance-12')

        transition = self._confirm(self._roll(state, 'seat-0', 1, 2).state)

        self.assertEqual(
            transition.state['players']['seat-0']['cash'], 1500 - (25 * 2 + 100)
        )
        self.assertIn(
            ('card_paid', 'seat-0', {'amount': 150, 'to': None}),
            self._facts(transition),
        )

    def test_the_community_chest_repairs_card_uses_its_own_rates(self):
        state = self._rolling(self._scene(levels={1: 1, 3: 5}), 'seat-0')
        state = self._place(state, 'seat-0', 14)
        state = self._top_card(state, cards.COMMUNITY_CHEST, 'community_chest-14')

        transition = self._confirm(self._roll(state, 'seat-0', 1, 2).state)

        self.assertEqual(
            transition.state['players']['seat-0']['cash'], 1500 - (40 + 115)
        )
        self.assertIn(
            ('card_paid', 'seat-0', {'amount': 155, 'to': None}),
            self._facts(transition),
        )


class MonopolyBankruptcyTests(MonopolyRulesTestCase):
    def _boardwalk_rent_scene(self, seats=('seat-0', 'seat-1')):
        """``seat-0`` lands on ``seat-1``'s Boardwalk holding only $10."""
        state = rules.initial_state(seats, 'seat-0')
        state = self._place(state, 'seat-0', 36)
        state = self._cash(state, 'seat-0', 10)
        state = self._give(state, 3, 'seat-0')
        return self._give(state, 39, 'seat-1')

    def test_an_unaffordable_rent_transfers_everything_to_the_creditor(self):
        opened = self._roll(self._boardwalk_rent_scene(), 'seat-0', 1, 2)
        self.assertEqual(opened.state['phase'], rules.PHASE_RAISING_CASH)
        transition = self._act(opened.state, 'seat-0', 'declare_bankruptcy')
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
        opened = self._roll(state, 'seat-0', 2, 3)
        transition = self._act(opened.state, 'seat-0', 'declare_bankruptcy')
        self.assertIs(transition.state['players']['seat-0']['eliminated'], True)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 0)
        self.assertEqual(transition.state['owners'], {})
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1500)
        self.assertIn(('bankrupt', 'seat-0', {'creditor': None}), self._facts(transition))

    def test_a_mortgaged_property_returned_to_the_bank_is_unmortgaged(self):
        # The bank cannot hold a mortgage: a property it takes back has no owner
        # to owe it, and whoever lands on it next buys a clean lot. The map is
        # an invariant of ownership, never a property the space carries alone.
        state = self._place(self._open(), 'seat-0', 33)
        state = self._cash(state, 'seat-0', 10)
        state = self._mortgaged(self._give(state, 3, 'seat-0'), 3)
        opened = self._roll(state, 'seat-0', 2, 3)
        transition = self._act(opened.state, 'seat-0', 'declare_bankruptcy')

        self.assertEqual(transition.state['owners'], {})
        self.assertEqual(transition.state['mortgaged'], {})

    def test_an_eliminated_seat_never_acts_again(self):
        scene = self._boardwalk_rent_scene(('seat-0', 'seat-1', 'seat-2'))
        opened = self._roll(scene, 'seat-0', 1, 2)
        transition = self._act(opened.state, 'seat-0', 'declare_bankruptcy')
        self.assertEqual(self._names(transition.state, 'seat-0'), ())
        self.assertEqual(transition.state['turn'], 'seat-1')
        self.assertEqual(self._names(transition.state, 'seat-1'), ('roll', 'propose'))


class MonopolyFinishTests(MonopolyRulesTestCase):
    def test_a_two_seat_match_ends_with_the_last_solvent_seat(self):
        state = self._place(self._open(), 'seat-0', 36)
        state = self._cash(state, 'seat-0', 10)
        state = self._give(state, 39, 'seat-1')
        opened = self._roll(state, 'seat-0', 1, 2)
        self.assertEqual(opened.state['phase'], rules.PHASE_RAISING_CASH)
        transition = self._act(opened.state, 'seat-0', 'declare_bankruptcy')
        self.assertIs(rules.is_finished(transition.state), True)
        self.assertEqual(
            rules.outcome(transition.state),
            Outcome(winner_seat='seat-1', reason='last_solvent'),
        )
        self.assertIn(
            ('match_finished', None, {'winner': 'seat-1'}), self._facts(transition)
        )
        self.assertIsNone(transition.state['turn'])
        self.assertIsNone(transition.state['debt'])
        self.assertEqual(self._names(transition.state, 'seat-1'), ())

    def test_a_three_seat_match_keeps_playing_after_one_elimination(self):
        state = rules.initial_state(('seat-0', 'seat-1', 'seat-2'), 'seat-0')
        state = self._place(state, 'seat-0', 36)
        state = self._cash(state, 'seat-0', 10)
        state = self._give(state, 39, 'seat-1')
        opened = self._roll(state, 'seat-0', 1, 2)
        transition = self._act(opened.state, 'seat-0', 'declare_bankruptcy')
        self.assertIs(rules.is_finished(transition.state), False)
        self.assertIsNone(rules.outcome(transition.state))
        self.assertEqual(transition.state['turn'], 'seat-1')
        self.assertEqual(transition.state['phase'], rules.PHASE_AWAITING_ROLL)
        self.assertIsNone(transition.state['debt'])
        self.assertEqual(self._names(transition.state, 'seat-1'), ('roll', 'propose'))

    def test_a_running_match_has_no_outcome(self):
        self.assertIsNone(rules.outcome(self._open()))
        self.assertIs(rules.is_finished(self._open()), False)

    def test_a_running_transition_never_announces_a_finish(self):
        state = self._place(self._open(), 'seat-0', 15)
        transition = self._roll(state, 'seat-0', 2, 3)
        self.assertNotIn(
            'match_finished', [fact[0] for fact in self._facts(transition)]
        )


class MonopolyAuctionTests(MonopolyRulesTestCase):
    """Bidding for a declined property (S1 to S6 of ``monopoly-auction.md``)."""

    def _auction(self, seats=('seat-0', 'seat-1'), start=0, faces=(1, 2)):
        """Decline Baltic (3) and leave the match in the bidding phase."""
        state = self._place(self._open(seats), 'seat-0', start)
        rolled = self._roll(state, 'seat-0', *faces)
        return self._act(rolled.state, 'seat-0', 'decline').state

    def _pass(self, state, seat):
        return self._act(state, seat, 'pass').state

    def _bid(self, state, seat, amount):
        return rules.apply_action(state, seat, Action(name='bid', value=str(amount)), None)

    def test_every_solvent_seat_may_bid_and_the_decliner_too(self):
        state = self._auction()

        self.assertEqual(rules.active_seats(state), ('seat-0', 'seat-1'))
        self.assertEqual(self._names(state, 'seat-0'), ('bid', 'pass', 'propose'))
        self.assertEqual(self._names(state, 'seat-1'), ('bid', 'pass', 'propose'))

    def test_the_bid_ladder_offers_absolute_amounts_over_the_current_bid(self):
        state = self._auction()
        self.assertEqual(
            rules.legal_actions(state, 'seat-0')[0].options, ('1', '10', '50', '100')
        )

        raised = self._bid(state, 'seat-0', 10).state

        self.assertEqual(raised['auction']['high_bid'], 10)
        self.assertEqual(raised['auction']['high_bidder'], 'seat-0')
        self.assertEqual(
            rules.legal_actions(raised, 'seat-0')[0].options,
            ('11', '20', '60', '110'),
        )

    def test_the_ladder_stops_at_the_bidders_cash(self):
        state = self._cash(self._auction(), 'seat-1', 60)
        self.assertEqual(
            rules.legal_actions(state, 'seat-1')[0].options, ('1', '10', '50')
        )

        poorer = self._cash(state, 'seat-1', 5)
        self.assertEqual(rules.legal_actions(poorer, 'seat-1')[0].options, ('1',))

    def test_a_seat_that_cannot_outbid_anyone_can_only_pass(self):
        state = self._cash(self._bid(self._auction(), 'seat-0', 100).state, 'seat-1', 50)

        self.assertEqual(self._names(state, 'seat-1'), ('pass', 'propose'))

    def test_the_high_bidder_may_raise_but_never_pass(self):
        state = self._bid(self._auction(), 'seat-0', 10).state

        self.assertEqual(self._names(state, 'seat-0'), ('bid', 'propose'))
        self.assertEqual(self._names(state, 'seat-1'), ('bid', 'pass', 'propose'))
        with self.assertRaises(ValueError):
            self._act(state, 'seat-0', 'pass')

    def test_a_bid_clears_the_passed_list(self):
        passed = self._pass(self._auction(), 'seat-1')
        self.assertEqual(passed['auction']['passed'], ['seat-1'])

        raised = self._bid(passed, 'seat-0', 10).state

        self.assertEqual(raised['auction']['passed'], [])
        self.assertEqual(self._names(raised, 'seat-1'), ('bid', 'pass', 'propose'))

    def test_the_last_standing_high_bidder_wins_and_pays_the_bank(self):
        state = self._bid(self._auction(), 'seat-0', 100).state

        won = self._pass(state, 'seat-1')

        self.assertIsNone(won['auction'])
        self.assertEqual(won['owners'], {'3': 'seat-0'})
        self.assertEqual(won['players']['seat-0']['properties'], [3])
        self.assertEqual(won['players']['seat-0']['cash'], 1400)
        self.assertEqual(won['phase'], rules.PHASE_MANAGING)
        self.assertEqual(won['turn'], 'seat-0')

    def test_the_winning_bid_is_announced(self):
        state = self._bid(self._auction(), 'seat-0', 100).state

        transition = self._act(state, 'seat-1', 'pass')

        self.assertIn(
            ('auction_won', 'seat-0', {'space': 3, 'amount': 100}),
            self._facts(transition),
        )

    def test_a_deserted_auction_leaves_the_property_with_the_bank(self):
        state = self._pass(self._pass(self._auction(), 'seat-0'), 'seat-1')

        self.assertIsNone(state['auction'])
        self.assertEqual(state['owners'], {})
        self.assertEqual(state['players']['seat-0']['cash'], 1500)
        self.assertEqual(state['phase'], rules.PHASE_MANAGING)
        self.assertEqual(state['turn'], 'seat-0')

    def test_a_deserted_auction_is_announced(self):
        transition = self._act(
            self._pass(self._auction(), 'seat-0'), 'seat-1', 'pass'
        )

        self.assertIn(
            ('auction_unsold', 'seat-0', {'space': 3}), self._facts(transition)
        )

    def test_an_auction_outlives_the_extra_roll_of_a_double(self):
        state = self._place(self._open(), 'seat-0', 4)
        declined = self._act(
            self._roll(state, 'seat-0', 1, 1).state, 'seat-0', 'decline'
        ).state
        self.assertIs(declined['extra_roll'], True)
        self.assertEqual(declined['auction']['space'], 6)

        won = self._bid(self._bid(declined, 'seat-0', 50).state, 'seat-1', 100).state
        resolved = self._pass(won, 'seat-0')

        self.assertIsNone(resolved['auction'])
        self.assertEqual(resolved['owners'], {'6': 'seat-1'})
        self.assertEqual(resolved['players']['seat-1']['cash'], 1400)
        # The decliner kept the dice: the extra roll is what comes next.
        self.assertEqual(resolved['phase'], rules.PHASE_AWAITING_ROLL)
        self.assertEqual(resolved['turn'], 'seat-0')

    def test_a_bid_outside_the_ladder_is_rejected(self):
        state = self._auction()
        with self.assertRaises(ValueError):
            self._bid(state, 'seat-0', 7)
        with self.assertRaises(ValueError):
            self._bid(state, 'seat-0', 0)

    def test_a_seat_that_already_passed_cannot_bid_or_pass_again(self):
        state = self._pass(self._auction(), 'seat-1')

        # A passed bidder keeps its trade action, but may not bid again.
        self.assertEqual(self._names(state, 'seat-1'), ('propose',))
        with self.assertRaises(ValueError):
            self._bid(state, 'seat-1', 10)
        with self.assertRaises(ValueError):
            self._pass(state, 'seat-1')

    def test_no_auction_action_is_accepted_outside_the_bidding_phase(self):
        state = self._open()
        self.assertEqual(self._names(state, 'seat-0'), ('roll', 'propose'))
        with self.assertRaises(ValueError):
            self._act(state, 'seat-0', 'pass')
        with self.assertRaises(ValueError):
            self._bid(state, 'seat-0', 10)

    def test_an_expelled_bidder_leaves_the_auction_and_can_end_it(self):
        """A seat that disconnects mid-auction stops being a bidder (S6)."""
        state = self._auction(('seat-0', 'seat-1', 'seat-2'))
        state = self._bid(state, 'seat-2', 50).state
        state = self._pass(state, 'seat-1')

        # seat-0 is the parked turn seat and an eligible bidder too, and with it
        # gone the only bidder left is the one holding the high bid.
        resolved = rules.abandon(state, 'seat-0').state

        self.assertIsNone(resolved['auction'])
        self.assertEqual(resolved['owners'], {'3': 'seat-2'})
        self.assertEqual(resolved['players']['seat-2']['cash'], 1450)
        self.assertEqual(self._names(resolved, 'seat-0'), ())


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

    def test_abandoning_the_creditor_of_an_open_debt_owes_the_bank(self):
        # The recipient leaves the match, so the money the debt carries leaves
        # with it: the debtor owes the bank, never an eliminated seat.
        state = rules.initial_state(('seat-0', 'seat-1', 'seat-2'), 'seat-0')
        state = self._place(state, 'seat-0', 36)
        state = self._cash(state, 'seat-0', 10)
        state = self._give(state, 39, 'seat-1')
        opened = self._roll(state, 'seat-0', 1, 2)
        self.assertEqual(opened.state['debt']['creditor'], 'seat-1')

        transition = rules.abandon(opened.state, 'seat-1')

        self.assertIs(rules.is_finished(transition.state), False)
        self.assertEqual(transition.state['debt']['amount'], 50)
        self.assertIsNone(transition.state['debt']['creditor'])

    def test_abandon_that_ends_the_match_leaves_no_open_debt(self):
        # A finished match publishes no window nobody can act on any more.
        state = self._place(self._open(), 'seat-0', 36)
        state = self._cash(state, 'seat-0', 10)
        state = self._give(state, 39, 'seat-1')
        opened = self._roll(state, 'seat-0', 1, 2)
        self.assertEqual(opened.state['phase'], rules.PHASE_RAISING_CASH)

        transition = rules.abandon(opened.state, 'seat-1')

        self.assertIs(rules.is_finished(transition.state), True)
        self.assertIsNone(transition.state['debt'])

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


class _ReversingRng:
    """``RandomSource`` whose shuffle reverses, so a shuffle is observable."""

    def shuffle(self, items):
        return list(reversed(list(items)))

    def roll(self, sides):
        return 1


class _SeatIdsRng:
    """``RandomSource`` that answers every shuffle with seat ids, not decks.

    It is the shape the two test doubles of this suite had, and the reason the
    backend suite was flaky: the decks were stored as seat ids and the match
    only failed when a roll landed on a card space.
    """

    def shuffle(self, items):
        return ['seat-0', 'seat-1']

    def roll(self, sides):
        return 1


class MonopolyDeckTests(MonopolyRulesTestCase):
    """How a deck is shuffled, drawn from and recycled (S1, S3)."""

    def test_a_fresh_state_holds_both_decks_in_printed_order(self):
        state = self._open()
        self.assertEqual(state['decks'][cards.CHANCE], list(cards.deck_ids(cards.CHANCE)))
        self.assertEqual(
            state['decks'][cards.COMMUNITY_CHEST],
            list(cards.deck_ids(cards.COMMUNITY_CHEST)),
        )
        self.assertIsNone(state['last_card'])

    def test_fresh_decks_are_shuffled_by_the_random_source(self):
        decks = rules.fresh_decks(_ReversingRng())

        self.assertEqual(
            decks[cards.CHANCE], list(reversed(cards.deck_ids(cards.CHANCE)))
        )
        self.assertEqual(
            decks[cards.COMMUNITY_CHEST],
            list(reversed(cards.deck_ids(cards.COMMUNITY_CHEST))),
        )

    def test_fresh_decks_reject_a_source_that_does_not_shuffle_the_deck(self):
        # A source that returns something else would store it as the deck and
        # fail much later, on a card space, so it has to fail here instead.
        with self.assertRaises(ValueError):
            rules.fresh_decks(_SeatIdsRng())

    def test_a_drawn_card_goes_to_the_bottom_of_its_own_deck(self):
        state = self._top_card(
            self._place(self._open(), 'seat-0', 4), cards.CHANCE, 'chance-02'
        )
        before = list(state['decks'][cards.CHANCE])
        untouched = list(state['decks'][cards.COMMUNITY_CHEST])

        drawn = self._roll(state, 'seat-0', 1, 2).state

        self.assertEqual(len(drawn['decks'][cards.CHANCE]), 16)
        self.assertEqual(drawn['decks'][cards.CHANCE][-1], 'chance-02')
        self.assertEqual(drawn['decks'][cards.CHANCE][0], before[1])
        # The other deck is not touched by a draw from this one.
        self.assertEqual(drawn['decks'][cards.COMMUNITY_CHEST], untouched)

    def test_the_draw_is_announced_with_the_card_copy_and_kept_in_the_view_state(self):
        state = self._top_card(
            self._place(self._open(), 'seat-0', 4), cards.CHANCE, 'chance-13'
        )

        transition = self._roll(state, 'seat-0', 1, 2)

        self.assertEqual(transition.state['last_card'], {'deck': cards.CHANCE, 'id': 'chance-13'})
        self.assertIn(
            (
                'card_drawn',
                'seat-0',
                {
                    'deck': cards.CHANCE,
                    'id': 'chance-13',
                    'title': cards.card_for('chance-13').title,
                },
            ),
            self._facts(transition),
        )

    def test_the_jail_card_leaves_the_deck_and_is_held_by_the_seat(self):
        state = self._top_card(
            self._place(self._open(), 'seat-0', 4), cards.CHANCE, 'chance-09'
        )

        transition = self._confirm(self._roll(state, 'seat-0', 1, 2).state)

        self.assertEqual(len(transition.state['decks'][cards.CHANCE]), 15)
        self.assertNotIn('chance-09', transition.state['decks'][cards.CHANCE])
        self.assertEqual(transition.state['players']['seat-0']['jail_cards'], ['chance-09'])
        self.assertIn(
            ('jail_card_obtained', 'seat-0', {'deck': cards.CHANCE}),
            self._facts(transition),
        )


def _public_card(pending):
    """The part of a card decision the view may publish (S4 of the increment)."""
    return {key: pending[key] for key in ('kind', 'deck', 'id')}


class MonopolyCardConfirmationTests(MonopolyRulesTestCase):
    """The card waits for its seat to read it (S1 to S3 of ``monopoly-card-modal.md``)."""

    def test_landing_on_a_card_space_turns_the_card_up_and_stops(self):
        state = self._top_card(
            self._place(self._open(), 'seat-0', 4), cards.CHANCE, 'chance-13'
        )

        transition = self._roll(state, 'seat-0', 1, 2)

        # The card is drawn and announced, and nothing it orders has happened.
        self.assertEqual(
            _public_card(transition.state['pending']),
            {'kind': 'card', 'deck': cards.CHANCE, 'id': 'chance-13'},
        )
        self.assertEqual(transition.state['phase'], rules.PHASE_AWAITING_DECISION)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1500)
        self.assertNotIn('card_paid', [fact[0] for fact in self._facts(transition)])
        self.assertEqual(
            [fact[0] for fact in self._facts(transition)],
            ['roll_recorded', 'moved', 'card_drawn'],
        )

    def test_the_card_decision_offers_the_confirm_and_nothing_else(self):
        state = self._top_card(
            self._place(self._open(), 'seat-0', 4), cards.CHANCE, 'chance-13'
        )
        opened = self._roll(state, 'seat-0', 1, 2).state

        specs = rules.legal_actions(opened, 'seat-0')
        self.assertIn('confirm_card', [spec.name for spec in specs])
        self.assertEqual(
            [spec.prompt for spec in specs if spec.name == 'confirm_card'],
            ['Aceptá la carta.'],
        )
        # The turn's own actions are gone until the card is answered.
        for blocked in ('roll', 'end_turn', 'buy', 'decline'):
            with self.subTest(action=blocked):
                self.assertNotIn(blocked, [spec.name for spec in specs])

    def test_only_the_seat_on_turn_may_confirm_the_card(self):
        state = self._top_card(
            self._place(self._open(), 'seat-0', 4), cards.CHANCE, 'chance-13'
        )
        opened = self._roll(state, 'seat-0', 1, 2).state

        self.assertNotIn('confirm_card', self._names(opened, 'seat-1'))
        with self.assertRaises(ValueError):
            self._confirm(opened, 'seat-1')

    def test_confirming_applies_the_effect_and_clears_the_card(self):
        state = self._top_card(
            self._place(self._open(), 'seat-0', 4), cards.CHANCE, 'chance-13'
        )
        opened = self._roll(state, 'seat-0', 1, 2).state

        transition = self._confirm(opened)

        self.assertEqual(transition.state['players']['seat-0']['cash'], 1485)
        self.assertIsNone(transition.state['pending'])
        self.assertEqual(transition.state['phase'], rules.PHASE_MANAGING)
        self.assertIn(
            ('card_paid', 'seat-0', {'amount': 15, 'to': None}),
            self._facts(transition),
        )
        self.assertNotIn('confirm_card', self._names(transition.state, 'seat-0'))

    def test_a_card_cannot_be_confirmed_twice(self):
        state = self._top_card(
            self._place(self._open(), 'seat-0', 4), cards.CHANCE, 'chance-08'
        )
        opened = self._roll(state, 'seat-0', 1, 2).state
        applied = self._confirm(opened).state

        with self.assertRaises(ValueError):
            self._confirm(applied)

    def test_a_card_on_a_doubles_keeps_the_extra_turn_for_after_the_accept(self):
        state = self._top_card(
            self._place(self._open(), 'seat-0', 3), cards.CHANCE, 'chance-08'
        )

        opened = self._roll(state, 'seat-0', 2, 2)
        # While the card is pending the roll owns neither a new throw nor the turn.
        self.assertEqual(opened.state['phase'], rules.PHASE_AWAITING_DECISION)
        self.assertEqual(opened.state['turn'], 'seat-0')

        applied = self._confirm(opened.state)

        self.assertEqual(applied.state['players']['seat-0']['cash'], 1550)
        self.assertEqual(applied.state['phase'], rules.PHASE_AWAITING_ROLL)
        self.assertEqual(applied.state['turn'], 'seat-0')
        self.assertIn('roll', self._names(applied.state, 'seat-0'))

    def test_a_card_that_advances_opens_its_purchase_after_the_accept(self):
        state = self._top_card(
            self._place(self._open(), 'seat-0', 2), cards.CHANCE, 'chance-04'
        )
        opened = self._roll(state, 'seat-0', 2, 3).state
        self.assertEqual(
            _public_card(opened['pending']),
            {'kind': 'card', 'deck': cards.CHANCE, 'id': 'chance-04'},
        )

        applied = self._confirm(opened)

        self.assertEqual(applied.state['players']['seat-0']['position'], 11)
        # St. Charles Place is unowned, so the card leaves the seat deciding.
        self.assertEqual(applied.state['pending'], {'kind': 'purchase', 'space': 11})
        self.assertEqual(applied.state['phase'], rules.PHASE_AWAITING_DECISION)

    def test_the_card_chain_opens_the_second_card_and_pays_nothing_yet(self):
        """Going back three from Chance 36 lands on Community Chest 33 (S3)."""
        state = self._place(self._open(), 'seat-0', 33)
        state = self._top_card(state, cards.CHANCE, 'chance-10')
        state = self._top_card(state, cards.COMMUNITY_CHEST, 'community_chest-02')

        # 33 + 3 = 36, a Chance space, which goes back three to 33.
        opened = self._roll(state, 'seat-0', 1, 2)
        self.assertEqual(opened.state['pending']['id'], 'chance-10')
        # The card record keeps what the effect needs and never publishes it.
        self.assertEqual(opened.state['pending']['faces'], [1, 2])
        self.assertIs(opened.state['pending']['extra'], False)

        chained = self._confirm(opened.state)
        self.assertEqual(chained.state['players']['seat-0']['position'], 33)
        self.assertEqual(chained.state['players']['seat-0']['cash'], 1500)
        self.assertEqual(
            _public_card(chained.state['pending']),
            {'kind': 'card', 'deck': cards.COMMUNITY_CHEST, 'id': 'community_chest-02'},
        )
        self.assertEqual(
            [fact[2]['id'] for fact in self._facts(opened) if fact[0] == 'card_drawn'],
            ['chance-10'],
        )
        self.assertEqual(
            [fact[2]['id'] for fact in self._facts(chained) if fact[0] == 'card_drawn'],
            ['community_chest-02'],
        )

        applied = self._confirm(chained.state)
        self.assertEqual(applied.state['players']['seat-0']['cash'], 1700)
        self.assertIsNone(applied.state['pending'])

    def test_confirming_a_charge_the_cash_cannot_cover_opens_the_debt_window(self):
        state = self._place(self._open(), 'seat-0', 14)
        state = self._cash(state, 'seat-0', 10)
        state = self._give(state, 39, 'seat-0')
        state = self._top_card(state, cards.COMMUNITY_CHEST, 'community_chest-11')
        opened = self._roll(state, 'seat-0', 1, 2).state
        self.assertEqual(opened['phase'], rules.PHASE_AWAITING_DECISION)

        charged = self._confirm(opened)

        self.assertEqual(charged.state['phase'], rules.PHASE_RAISING_CASH)
        self.assertEqual(charged.state['debt']['amount'], 100)
        self.assertIn(
            ('debt_incurred', 'seat-0', {'amount': 100, 'creditor': None}),
            self._facts(charged),
        )
        # The window raised its cash and the debt resumes the step the card
        # interrupted, which is the same continuation a printed charge stores.
        raised = rules.apply_action(
            charged.state, 'seat-0', Action(name='mortgage', value='39'), None
        ).state
        paid = rules.apply_action(raised, 'seat-0', Action(name='pay_debt'), None)
        self.assertEqual(paid.state['players']['seat-0']['cash'], 110)
        self.assertEqual(paid.state['phase'], rules.PHASE_MANAGING)
        self.assertIsNone(paid.state['debt'])

    def test_confirming_the_jail_card_puts_it_in_hand_and_ends_the_turn(self):
        state = self._top_card(
            self._place(self._open(), 'seat-0', 4), cards.CHANCE, 'chance-11'
        )
        opened = self._roll(state, 'seat-0', 1, 2).state

        applied = self._confirm(opened)

        player = applied.state['players']['seat-0']
        self.assertEqual(player['position'], board.JAIL_INDEX)
        self.assertIs(player['in_jail'], True)
        self.assertEqual(applied.state['turn'], 'seat-1')
        self.assertIn(
            ('sent_to_jail', 'seat-0', {'reason': 'go_to_jail'}), self._facts(applied)
        )


class MonopolyCardMoneyTests(MonopolyRulesTestCase):
    """The money and player-to-player effects of a drawn card (S10, S11)."""

    def _draw(self, card_id, deck=cards.CHANCE, seat='seat-0', start=4, **setup):
        """Roll onto the card space and accept the card it turns up (S2)."""
        state = self._place(self._open(**setup), seat, start)
        state = self._top_card(state, deck, card_id)
        return self._confirm(self._roll(state, seat, 1, 2).state, seat)

    def test_a_card_can_collect_from_the_bank(self):
        transition = self._draw('community_chest-02', deck=cards.COMMUNITY_CHEST, start=14)

        self.assertEqual(transition.state['players']['seat-0']['cash'], 1700)
        self.assertIn(
            ('card_collected', 'seat-0', {'amount': 200, 'from': None}),
            self._facts(transition),
        )

    def test_a_card_can_pay_the_bank(self):
        transition = self._draw('chance-13')

        self.assertEqual(transition.state['players']['seat-0']['cash'], 1485)
        self.assertIn(
            ('card_paid', 'seat-0', {'amount': 15, 'to': None}),
            self._facts(transition),
        )

    def test_a_birthday_collects_from_every_other_player_in_seat_order(self):
        state = self._open(('seat-0', 'seat-1', 'seat-2'))
        state = self._place(state, 'seat-0', 14)
        state = self._top_card(state, cards.COMMUNITY_CHEST, 'community_chest-09')

        transition = self._confirm(self._roll(state, 'seat-0', 1, 2).state)

        self.assertEqual(transition.state['players']['seat-0']['cash'], 1520)
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1490)
        self.assertEqual(transition.state['players']['seat-2']['cash'], 1490)
        self.assertEqual(
            [fact for fact in self._facts(transition) if fact[0] == 'card_collected'],
            [
                ('card_collected', 'seat-0', {'amount': 10, 'from': 'seat-1'}),
                ('card_collected', 'seat-0', {'amount': 10, 'from': 'seat-2'}),
            ],
        )

    def test_chairman_of_the_board_pays_every_other_player(self):
        state = self._open(('seat-0', 'seat-1', 'seat-2'))
        state = self._place(state, 'seat-0', 4)
        state = self._top_card(state, cards.CHANCE, 'chance-15')

        transition = self._confirm(self._roll(state, 'seat-0', 1, 2).state)

        self.assertEqual(transition.state['players']['seat-0']['cash'], 1400)
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1550)
        self.assertEqual(transition.state['players']['seat-2']['cash'], 1550)

    def test_repairs_cost_nothing_while_nothing_is_built(self):
        transition = self._draw('chance-12')

        self.assertEqual(transition.state['players']['seat-0']['cash'], 1500)
        self.assertIn(
            ('card_paid', 'seat-0', {'amount': 0, 'to': None}),
            self._facts(transition),
        )

    def test_an_unaffordable_card_payment_opens_the_debt_window(self):
        state = self._cash(self._place(self._open(), 'seat-0', 14), 'seat-0', 10)
        state = self._top_card(state, cards.COMMUNITY_CHEST, 'community_chest-11')

        opened = self._confirm(self._roll(state, 'seat-0', 1, 2).state)
        self.assertEqual(opened.state['phase'], rules.PHASE_RAISING_CASH)
        self.assertIn(
            ('debt_incurred', 'seat-0', {'amount': 100, 'creditor': None}),
            self._facts(opened),
        )
        transition = self._act(opened.state, 'seat-0', 'declare_bankruptcy')
        self.assertIs(transition.state['players']['seat-0']['eliminated'], True)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 0)
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1500)
        self.assertIs(rules.is_finished(transition.state), True)
        self.assertIn(('bankrupt', 'seat-0', {'creditor': None}), self._facts(transition))

    def test_an_unaffordable_group_payment_makes_the_first_creditor_the_owner(self):
        """The printed rules do not cover several creditors at once (S10).

        The shares are paid in seat order and the first one that cannot be
        afforded opens the debt: that player is the creditor, and declaring
        bankruptcy hands it everything.
        """
        state = self._open(('seat-0', 'seat-1', 'seat-2'))
        state = self._place(state, 'seat-0', 4)
        state = self._cash(state, 'seat-0', 40)
        state = self._give(state, 6, 'seat-0')
        state = self._top_card(state, cards.CHANCE, 'chance-15')

        opened = self._confirm(self._roll(state, 'seat-0', 1, 2).state)
        self.assertEqual(opened.state['phase'], rules.PHASE_RAISING_CASH)
        self.assertEqual(opened.state['debt']['creditor'], 'seat-1')
        self.assertEqual(opened.state['debt']['amount'], 50)
        transition = self._act(opened.state, 'seat-0', 'declare_bankruptcy')

        debtor = transition.state['players']['seat-0']
        self.assertIs(debtor['eliminated'], True)
        self.assertEqual(debtor['cash'], 0)
        # The first share in seat order is the one that could not be paid.
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1540)
        self.assertEqual(transition.state['players']['seat-1']['properties'], [6])
        # The later share is never collected from a seat that already left.
        self.assertEqual(transition.state['players']['seat-2']['cash'], 1500)
        self.assertIn(
            ('bankrupt', 'seat-0', {'creditor': 'seat-1'}), self._facts(transition)
        )


    def test_a_group_share_owed_to_an_expelled_creditor_leaves_the_game(self):
        # The window opened on seat-2 with seat-3 still to be paid, and seat-3
        # then left the match. A share can never be paid to a seat that is out:
        # it leaves the game through the bank, the same rule a single expelled
        # creditor already follows in ``abandon``.
        state = rules.initial_state(('seat-0', 'seat-1', 'seat-2', 'seat-3'), 'seat-0')
        state = self._cash(state, 'seat-0', 60)
        state = self._top_card(state, cards.CHANCE, 'chance-15')
        opened = self._confirm(self._land_on_card(state, 'seat-0', cards.CHANCE).state)
        self.assertEqual(opened.state['debt']['creditor'], 'seat-2')
        self.assertEqual(opened.state['debt']['resume']['remaining'], ['seat-3'])

        state = self._cash(opened.state, 'seat-0', 150)
        state = rules.abandon(state, 'seat-3').state
        transition = self._act(state, 'seat-0', 'pay_debt')

        self.assertEqual(transition.state['players']['seat-3']['cash'], 0)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 50)
        self.assertIn(
            ('card_paid', 'seat-0', {'amount': 50, 'to': None}),
            self._facts(transition),
        )


class MonopolyCardMovementTests(MonopolyRulesTestCase):
    """The movement effects of a drawn card (S4 to S8)."""

    def _draw_from(self, card_id, deck=cards.CHANCE, start=4, seat='seat-0', **setup):
        state = self._place(self._open(**setup), seat, start)
        state = self._top_card(state, deck, card_id)
        return state

    def test_advance_crosses_go_and_collects_the_salary(self):
        # From Caja de comunidad 33 the token reaches Suerte 36, and Reading
        # Railroad at 5 is nine spaces forward: the lap crosses GO.
        state = self._draw_from('chance-14', start=33)

        transition = self._confirm(self._roll(state, 'seat-0', 1, 2).state)

        self.assertEqual(transition.state['players']['seat-0']['position'], 5)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1700)
        self.assertEqual(transition.state['phase'], rules.PHASE_AWAITING_DECISION)
        self.assertEqual(transition.state['pending'], {'kind': 'purchase', 'space': 5})

    def test_advance_inside_the_lap_pays_no_salary_and_opens_the_purchase(self):
        state = self._draw_from('chance-03', start=19)

        transition = self._confirm(self._roll(state, 'seat-0', 1, 2).state)

        self.assertEqual(transition.state['players']['seat-0']['position'], 24)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1500)
        self.assertEqual(transition.state['pending'], {'kind': 'purchase', 'space': 24})

    def test_advance_to_go_collects_the_salary(self):
        state = self._draw_from('chance-02', start=19)

        transition = self._confirm(self._roll(state, 'seat-0', 1, 2).state)

        self.assertEqual(transition.state['players']['seat-0']['position'], 0)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1700)
        self.assertEqual(transition.state['phase'], rules.PHASE_MANAGING)

    def test_advance_pays_the_rent_of_the_space_it_reaches(self):
        state = self._give(self._draw_from('chance-01', start=19), 39, 'seat-1')

        transition = self._confirm(self._roll(state, 'seat-0', 1, 2).state)

        self.assertEqual(transition.state['players']['seat-0']['position'], 39)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1450)
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1550)

    def test_the_nearest_railroad_doubles_the_rent(self):
        # Two railroads held is a $50 rent normally; the card doubles it.
        state = self._give(self._give(self._draw_from('chance-05'), 15, 'seat-1'), 25, 'seat-1')

        transition = self._confirm(self._roll(state, 'seat-0', 1, 2).state)

        self.assertEqual(transition.state['players']['seat-0']['position'], 15)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1400)
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1600)

    def test_the_nearest_utility_throws_again_and_pays_ten_times(self):
        # The landing throw is 1+2 and the card throws 3+4 on its own.
        state = self._give(self._draw_from('chance-07'), 12, 'seat-1')

        drawn = self._roll(state, 'seat-0', 1, 2).state
        transition = self._confirm(drawn, 'seat-0', 3, 4)

        self.assertEqual(transition.state['players']['seat-0']['position'], 12)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1430)
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1570)
        self.assertEqual(transition.state['last_roll'], [3, 4])
        self.assertIn(('card_roll', 'seat-0', {'dice': [3, 4]}), self._facts(transition))

    def test_the_nearest_utility_opens_the_purchase_when_it_is_unowned(self):
        state = self._draw_from('chance-07')

        transition = self._confirm(self._roll(state, 'seat-0', 1, 2).state)

        self.assertEqual(transition.state['players']['seat-0']['position'], 12)
        self.assertEqual(transition.state['pending'], {'kind': 'purchase', 'space': 12})

    def test_going_back_three_resolves_the_space_it_reaches(self):
        state = self._give(self._draw_from('chance-10', start=19), 19, 'seat-1')

        transition = self._confirm(self._roll(state, 'seat-0', 1, 2).state)

        self.assertEqual(transition.state['players']['seat-0']['position'], 19)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1484)
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1516)

    def test_going_back_three_can_draw_from_the_other_deck(self):
        """The only chain of draws, and it terminates (S7)."""
        state = self._draw_from('chance-10', start=33)
        state = self._top_card(state, cards.COMMUNITY_CHEST, 'community_chest-02')

        drawn = self._roll(state, 'seat-0', 1, 2)
        self.assertEqual(
            [fact[2]['id'] for fact in self._facts(drawn) if fact[0] == 'card_drawn'],
            ['chance-10'],
        )

        # Accepting the first card walks back onto the other deck, which turns
        # its own card up and waits for its own accept.
        chained = self._confirm(drawn.state)
        self.assertEqual(chained.state['players']['seat-0']['position'], 33)
        self.assertEqual(chained.state['players']['seat-0']['cash'], 1500)
        self.assertEqual(
            [fact[2]['id'] for fact in self._facts(chained) if fact[0] == 'card_drawn'],
            ['community_chest-02'],
        )

        applied = self._confirm(chained.state)
        self.assertEqual(applied.state['players']['seat-0']['cash'], 1700)

    def test_going_to_jail_from_a_card_ends_the_turn_without_the_salary(self):
        state = self._draw_from('chance-11')

        transition = self._confirm(self._roll(state, 'seat-0', 1, 2).state)

        player = transition.state['players']['seat-0']
        self.assertEqual(player['position'], board.JAIL_INDEX)
        self.assertIs(player['in_jail'], True)
        self.assertEqual(player['cash'], 1500)
        self.assertEqual(transition.state['turn'], 'seat-1')
        self.assertIn(
            ('sent_to_jail', 'seat-0', {'reason': 'go_to_jail'}), self._facts(transition)
        )


class MonopolyJailCardTests(MonopolyRulesTestCase):
    """Holding and using the Get Out of Jail Free card (S9)."""

    def _jailed_with_card(self, jail_turns=0):
        state = self._open()
        return self._player(
            state,
            'seat-0',
            in_jail=True,
            jail_turns=jail_turns,
            position=board.JAIL_INDEX,
            jail_cards=['chance-09'],
        )

    def test_using_the_card_releases_the_seat_and_returns_it_to_its_deck(self):
        state = self._jailed_with_card()
        state = copy.deepcopy(state)
        state['decks'][cards.CHANCE] = [
            card_id for card_id in state['decks'][cards.CHANCE] if card_id != 'chance-09'
        ]

        self.assertIn('use_jail_card', self._names(state, 'seat-0'))
        transition = self._act(state, 'seat-0', 'use_jail_card')

        player = transition.state['players']['seat-0']
        self.assertIs(player['in_jail'], False)
        self.assertEqual(player['jail_turns'], 0)
        self.assertEqual(player['jail_cards'], [])
        self.assertEqual(transition.state['phase'], rules.PHASE_AWAITING_ROLL)
        self.assertEqual(transition.state['turn'], 'seat-0')
        self.assertEqual(transition.state['decks'][cards.CHANCE][-1], 'chance-09')
        self.assertEqual(len(transition.state['decks'][cards.CHANCE]), 16)
        self.assertIn(
            ('jail_card_used', 'seat-0', {'deck': cards.CHANCE}), self._facts(transition)
        )

    def test_the_card_is_offered_at_every_jail_turn_before_rolling(self):
        for jail_turns in (0, 1, 2):
            with self.subTest(jail_turns=jail_turns):
                state = self._jailed_with_card(jail_turns=jail_turns)
                self.assertIn('use_jail_card', self._names(state, 'seat-0'))

    def test_the_card_is_not_offered_without_one_or_outside_jail(self):
        held_but_free = self._player(
            self._open(), 'seat-0', jail_cards=['chance-09']
        )
        jailed_without = self._player(
            self._open(),
            'seat-0',
            in_jail=True,
            position=board.JAIL_INDEX,
            jail_cards=[],
        )

        self.assertNotIn('use_jail_card', self._names(held_but_free, 'seat-0'))
        self.assertNotIn('use_jail_card', self._names(jailed_without, 'seat-0'))
        with self.assertRaises(ValueError):
            self._act(held_but_free, 'seat-0', 'use_jail_card')
        with self.assertRaises(ValueError):
            self._act(jailed_without, 'seat-0', 'use_jail_card')


class MonopolyMortgageTests(MonopolyRulesTestCase):
    """Mortgages and the mortgaged state (S2 to S6, S10 of
    ``monopoly-mortgage.md``)."""

    def _own(self, state, *indexes, seat='seat-0'):
        for index in indexes:
            state = self._give(state, index, seat)
        return state

    def _managing(self, state, seat='seat-0'):
        state = copy.deepcopy(state)
        state['phase'] = rules.PHASE_MANAGING
        state['turn'] = seat
        return state

    def _rolling(self, state, seat='seat-1'):
        state = copy.deepcopy(state)
        state['phase'] = rules.PHASE_AWAITING_ROLL
        state['turn'] = seat
        return state

    def _buildings(self, state, levels):
        state = copy.deepcopy(state)
        buildings = dict(state.get('buildings') or {})
        for index, level in levels.items():
            if level == 0:
                buildings.pop(str(index), None)
            else:
                buildings[str(index)] = level
        state['buildings'] = buildings
        return state

    def _rejected(self, state, seat, name, value=None):
        """Apply an action the rules must reject and return the untouched state."""
        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            rules.apply_action(state, seat, Action(name=name, value=value), None)
        self.assertEqual(state, before)

    def test_initial_state_carries_the_mortgaged_map_and_a_null_debt(self):
        state = self._open()
        self.assertEqual(state['mortgaged'], {})
        self.assertIsNone(state['debt'])

    def test_a_match_saved_before_the_increment_reads_as_unmortgaged(self):
        state = self._managing(self._own(self._open(), 1, 3))
        del state['mortgaged']
        self.assertEqual(self._options(state, 'seat-0', 'mortgage'), ('1', '3'))
        transition = rules.apply_action(
            state, 'seat-0', Action(name='mortgage', value='1'), None
        )
        self.assertEqual(transition.state['mortgaged'], {'1': True})

    def test_mortgage_is_offered_in_managing_for_owned_spaces(self):
        state = self._managing(self._own(self._open(), 1, 3, 5, 12))
        self.assertEqual(
            self._options(state, 'seat-0', 'mortgage'), ('1', '3', '5', '12')
        )

    def test_mortgaging_pays_the_printed_value_and_keeps_the_owner(self):
        state = self._managing(self._own(self._open(), 37, seat='seat-0'))

        transition = rules.apply_action(
            state, 'seat-0', Action(name='mortgage', value='37'), None
        )

        self.assertEqual(transition.state['players']['seat-0']['cash'], 1500 + 175)
        self.assertEqual(transition.state['owners'], {'37': 'seat-0'})
        self.assertEqual(transition.state['players']['seat-0']['properties'], [37])
        self.assertEqual(transition.state['mortgaged'], {'37': True})
        self.assertEqual(
            self._facts(transition),
            (('property_mortgaged', 'seat-0', {'space': 37, 'amount': 175}),),
        )

    def test_mortgage_of_a_railroad_and_a_utility_pays_their_values(self):
        state = self._managing(self._own(self._open(), 5, 12))
        railroad = rules.apply_action(
            state, 'seat-0', Action(name='mortgage', value='5'), None
        )
        utility = rules.apply_action(
            state, 'seat-0', Action(name='mortgage', value='12'), None
        )
        self.assertEqual(railroad.state['players']['seat-0']['cash'], 1600)
        self.assertEqual(utility.state['players']['seat-0']['cash'], 1575)

    def test_a_mortgaged_space_cannot_be_mortgaged_again(self):
        state = self._managing(self._mortgaged(self._own(self._open(), 1, 3), 1))
        self.assertEqual(self._options(state, 'seat-0', 'mortgage'), ('3',))
        self._rejected(state, 'seat-0', 'mortgage', '1')

    def test_mortgage_is_blocked_by_a_building_anywhere_in_the_group(self):
        state = self._managing(self._buildings(self._own(self._open(), 1, 3), {3: 1}))
        self.assertEqual(self._options(state, 'seat-0', 'mortgage'), ())
        self._rejected(state, 'seat-0', 'mortgage', '1')
        self._rejected(state, 'seat-0', 'mortgage', '3')

    def test_mortgage_is_not_offered_for_a_space_owned_by_another_seat(self):
        state = self._managing(self._own(self._open(), 1, seat='seat-1'))
        self.assertEqual(self._names(state, 'seat-0'), ('end_turn', 'propose'))
        self._rejected(state, 'seat-0', 'mortgage', '1')

    def test_mortgage_is_rejected_in_awaiting_roll(self):
        state = self._rolling(self._own(self._open(), 1, 3))
        self.assertNotIn('mortgage', self._names(state, 'seat-0'))
        self._rejected(state, 'seat-0', 'mortgage', '1')

    def test_mortgage_options_are_board_indexes_and_reject_the_rest(self):
        state = self._managing(self._own(self._open(), 1, 3))
        for value in ('2', '39', 'x'):
            with self.subTest(value=value):
                self._rejected(state, 'seat-0', 'mortgage', value)

    def test_unmortgage_costs_the_mortgage_plus_ten_percent_rounded_up(self):
        state = self._managing(self._mortgaged(self._own(self._open(), 37), 37))
        state = self._cash(state, 'seat-0', 300)
        self.assertEqual(self._options(state, 'seat-0', 'unmortgage'), ('37',))

        transition = rules.apply_action(
            state, 'seat-0', Action(name='unmortgage', value='37'), None
        )

        self.assertEqual(transition.state['players']['seat-0']['cash'], 300 - 193)
        self.assertEqual(transition.state['mortgaged'], {})
        self.assertEqual(transition.state['owners'], {'37': 'seat-0'})
        self.assertEqual(
            self._facts(transition),
            (
                (
                    'property_unmortgaged',
                    'seat-0',
                    {'space': 37, 'mortgage': 175, 'interest': 18, 'amount': 193},
                ),
                (
                    'interest_paid',
                    'seat-0',
                    {'space': 37, 'amount': 18, 'reason': 'unmortgage'},
                ),
            ),
        )

    def test_unmortgage_is_offered_exactly_when_the_cash_covers_the_cost(self):
        short = self._cash(
            self._managing(self._mortgaged(self._own(self._open(), 37), 37)),
            'seat-0',
            192,
        )
        exact = self._cash(short, 'seat-0', 193)
        self.assertEqual(self._options(short, 'seat-0', 'unmortgage'), ())
        self._rejected(short, 'seat-0', 'unmortgage', '37')
        self.assertEqual(self._options(exact, 'seat-0', 'unmortgage'), ('37',))

    def test_unmortgage_is_not_offered_in_awaiting_roll(self):
        state = self._rolling(self._mortgaged(self._own(self._open(), 1), 1))
        self.assertNotIn('unmortgage', self._names(state, 'seat-0'))
        self._rejected(state, 'seat-0', 'unmortgage', '1')

    def test_a_mortgaged_street_charges_no_rent(self):
        state = self._own(self._open(first='seat-1'), 3)
        state = self._rolling(self._mortgaged(state, 3))
        state = self._place(state, 'seat-1', 0)

        transition = self._roll(state, 'seat-1', 1, 2)

        self.assertEqual(transition.state['players']['seat-0']['cash'], 1500)
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1500)
        self.assertNotIn('rent_paid', [fact[0] for fact in self._facts(transition)])

    def test_a_mortgaged_sibling_does_not_stop_the_set_rent(self):
        state = self._own(self._open(first='seat-1'), 1, 3)
        state = self._rolling(self._mortgaged(state, 1))
        state = self._place(state, 'seat-1', 0)

        transition = self._roll(state, 'seat-1', 1, 2)

        self.assertEqual(transition.state['players']['seat-0']['cash'], 1508)
        self.assertIn(
            (
                'rent_paid',
                'seat-1',
                {'from': 'seat-1', 'to': 'seat-0', 'space': 3, 'amount': 8},
            ),
            self._facts(transition),
        )

    def test_a_mortgaged_railroad_charges_no_rent_but_counts_for_the_rest(self):
        lone = self._rolling(self._mortgaged(self._own(self._open(first='seat-1'), 5), 5))
        lone = self._place(lone, 'seat-1', 2)
        charged = self._own(self._open(first='seat-1'), 5, 15)
        charged = self._rolling(self._mortgaged(charged, 15))
        charged = self._place(charged, 'seat-1', 2)

        no_rent = self._roll(lone, 'seat-1', 1, 2)
        doubled = self._roll(charged, 'seat-1', 1, 2)

        self.assertEqual(no_rent.state['players']['seat-0']['cash'], 1500)
        self.assertNotIn('rent_paid', [fact[0] for fact in self._facts(no_rent)])
        self.assertEqual(doubled.state['players']['seat-0']['cash'], 1550)

    def test_a_mortgaged_utility_charges_no_rent_but_counts_for_the_rest(self):
        lone = self._rolling(self._mortgaged(self._own(self._open(first='seat-1'), 12), 12))
        lone = self._place(lone, 'seat-1', 7)
        charged = self._own(self._open(first='seat-1'), 12, 28)
        charged = self._rolling(self._mortgaged(charged, 28))
        charged = self._place(charged, 'seat-1', 7)

        no_rent = self._roll(lone, 'seat-1', 2, 3)
        doubled = self._roll(charged, 'seat-1', 2, 3)

        self.assertEqual(no_rent.state['players']['seat-0']['cash'], 1500)
        self.assertNotIn('rent_paid', [fact[0] for fact in self._facts(no_rent)])
        self.assertEqual(doubled.state['players']['seat-0']['cash'], 1550)

    def test_a_card_destination_that_is_mortgaged_charges_no_rent(self):
        state = self._own(self._open(), 39, seat='seat-1')
        state = self._mortgaged(state, 39)
        state = self._place(state, 'seat-0', 36)
        state = self._top_card(state, cards.CHANCE, 'chance-01')

        transition = self._roll(state, 'seat-0', 1, 2)

        self.assertEqual(transition.state['players']['seat-0']['position'], 39)
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1500)
        self.assertNotIn('rent_paid', [fact[0] for fact in self._facts(transition)])

    def test_a_nearest_utility_card_to_a_mortgaged_utility_charges_nothing(self):
        state = self._own(self._open(), 12, seat='seat-1')
        state = self._mortgaged(state, 12)
        state = self._place(state, 'seat-0', 4)
        state = self._top_card(state, cards.CHANCE, 'chance-07')

        transition = self._confirm(self._roll(state, 'seat-0', 1, 2).state)

        self.assertEqual(transition.state['players']['seat-0']['position'], 12)
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1500)
        names = [fact[0] for fact in self._facts(transition)]
        self.assertNotIn('rent_paid', names)
        self.assertNotIn('card_roll', names)

    def test_a_group_with_a_mortgaged_street_cannot_be_built(self):
        state = self._managing(self._mortgaged(self._own(self._open(), 1, 3), 3))
        self.assertEqual(self._options(state, 'seat-0', 'build'), ())
        self._rejected(state, 'seat-0', 'build', '1')
        self._rejected(state, 'seat-0', 'build', '3')

    def test_mortgaging_keeps_the_printed_worth_of_the_property(self):
        state = self._managing(self._own(self._open(), 37))
        mortgaged = rules.apply_action(
            state, 'seat-0', Action(name='mortgage', value='37'), None
        ).state
        # Park Place keeps its $350 printed price in the seat's worth.
        self.assertEqual(
            rules.total_worth(mortgaged, 'seat-0'), 1500 + 175 + 350
        )


class MonopolyRaisingCashTests(MonopolyRulesTestCase):
    """The raising-cash window, the debt record and its continuations
    (S7, S8 and S10 of ``monopoly-mortgage.md``)."""

    def _apply(self, state, seat, name, value=None):
        return rules.apply_action(state, seat, Action(name=name, value=value), None)

    def _rejected(self, state, seat, name, value=None):
        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            rules.apply_action(state, seat, Action(name=name, value=value), None)
        self.assertEqual(state, before)

    def _rent_scene(self, cash=10, start=36, seats=('seat-0', 'seat-1')):
        state = self._open(seats, first='seat-0')
        state = self._place(state, 'seat-0', start)
        state = self._cash(state, 'seat-0', cash)
        return self._give(state, 39, 'seat-1')

    def _open_rent_debt(self, cash=10, start=36):
        opened = self._roll(self._rent_scene(cash=cash, start=start), 'seat-0', 1, 2)
        self.assertEqual(opened.state['phase'], rules.PHASE_RAISING_CASH)
        return opened

    def _window_scene(self):
        """A debt opened by Boardwalk's rent on a seat holding brown with a house."""
        state = self._open(first='seat-0')
        state = self._give(state, 1, 'seat-0')
        state = self._give(state, 3, 'seat-0')
        state = copy.deepcopy(state)
        state['buildings'] = {'3': 1}
        state['bank'] = {'houses': 31, 'hotels': 12}
        state = self._place(state, 'seat-0', 36)
        state = self._cash(state, 'seat-0', 10)
        state = self._give(state, 39, 'seat-1')
        opened = self._roll(state, 'seat-0', 1, 2)
        self.assertEqual(opened.state['phase'], rules.PHASE_RAISING_CASH)
        return opened.state

    def test_an_unaffordable_rent_opens_the_window_with_the_creditor(self):
        transition = self._open_rent_debt()
        state = transition.state
        self.assertEqual(state['debt']['seat'], 'seat-0')
        self.assertEqual(state['debt']['creditor'], 'seat-1')
        self.assertEqual(state['debt']['amount'], 50)
        self.assertEqual(state['turn'], 'seat-0')
        self.assertEqual(state['players']['seat-0']['cash'], 10)
        names = [fact[0] for fact in self._facts(transition)]
        self.assertIn('debt_incurred', names)
        self.assertNotIn('rent_paid', names)
        self.assertNotIn('bankrupt', names)
        self.assertIn(
            ('debt_incurred', 'seat-0', {'amount': 50, 'creditor': 'seat-1'}),
            self._facts(transition),
        )

    def test_the_window_hides_build_unmortgage_and_end_turn(self):
        state = self._window_scene()
        self.assertEqual(
            self._names(state, 'seat-0'),
            ('sell', 'declare_bankruptcy'),
        )
        for name in ('build', 'unmortgage', 'end_turn', 'roll'):
            with self.subTest(name=name):
                self.assertNotIn(name, self._names(state, 'seat-0'))
                self._rejected(state, 'seat-0', name)

    def test_pay_debt_is_offered_only_when_the_cash_reaches_the_amount(self):
        state = self._open_rent_debt().state
        short = self._cash(state, 'seat-0', 49)
        exact = self._cash(state, 'seat-0', 50)
        self.assertNotIn('pay_debt', self._names(short, 'seat-0'))
        self._rejected(short, 'seat-0', 'pay_debt')
        self.assertIn('pay_debt', self._names(exact, 'seat-0'))

    def test_paying_a_rent_debt_pays_the_creditor_and_returns_to_managing(self):
        state = self._cash(self._open_rent_debt().state, 'seat-0', 60)
        transition = self._apply(state, 'seat-0', 'pay_debt')
        self.assertEqual(transition.state['players']['seat-0']['cash'], 10)
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1550)
        self.assertEqual(transition.state['phase'], rules.PHASE_MANAGING)
        self.assertIsNone(transition.state['debt'])
        self.assertIn(
            (
                'rent_paid',
                'seat-0',
                {'from': 'seat-0', 'to': 'seat-1', 'space': 39, 'amount': 50},
            ),
            self._facts(transition),
        )

    def test_a_rent_debt_from_a_double_resumes_with_the_extra_roll(self):
        state = self._open(first='seat-0')
        state = self._place(state, 'seat-0', 37)
        state = self._cash(state, 'seat-0', 10)
        state = self._give(state, 39, 'seat-1')
        opened = self._roll(state, 'seat-0', 1, 1)
        self.assertEqual(opened.state['phase'], rules.PHASE_RAISING_CASH)

        state = self._cash(opened.state, 'seat-0', 50)
        transition = self._apply(state, 'seat-0', 'pay_debt')

        self.assertEqual(transition.state['phase'], rules.PHASE_AWAITING_ROLL)
        self.assertEqual(transition.state['turn'], 'seat-0')

    def test_a_luxury_tax_debt_emits_its_tax_fact_on_payment(self):
        state = self._open(first='seat-0')
        state = self._place(state, 'seat-0', 33)
        state = self._cash(state, 'seat-0', 10)
        opened = self._roll(state, 'seat-0', 2, 3)
        self.assertEqual(opened.state['phase'], rules.PHASE_RAISING_CASH)
        self.assertEqual(opened.state['debt']['creditor'], None)
        self.assertEqual(opened.state['debt']['amount'], rules.LUXURY_TAX)

        paid = self._cash(opened.state, 'seat-0', rules.LUXURY_TAX)
        transition = self._apply(paid, 'seat-0', 'pay_debt')

        self.assertEqual(transition.state['phase'], rules.PHASE_MANAGING)
        self.assertIn(
            (
                'tax_paid',
                'seat-0',
                {'space': 38, 'amount': 75, 'option': 'fixed'},
            ),
            self._facts(transition),
        )

    def test_an_unaffordable_income_tax_keeps_the_chosen_option(self):
        state = self._open(first='seat-0')
        state = self._place(state, 'seat-0', 2)
        state = self._cash(state, 'seat-0', 10)
        state = self._give(state, 39, 'seat-0')
        rolled = self._roll(state, 'seat-0', 1, 1)
        self.assertEqual(rolled.state['pending'], {'kind': 'income_tax', 'space': 4})

        opened = self._apply(rolled.state, 'seat-0', 'pay_income_tax_percent')

        self.assertEqual(opened.state['phase'], rules.PHASE_RAISING_CASH)
        self.assertEqual(opened.state['debt']['amount'], 41)
        self.assertEqual(opened.state['debt']['creditor'], None)
        self.assertEqual(opened.state['pending'], {'kind': 'income_tax', 'space': 4})
        self.assertNotIn(
            'pay_income_tax_fixed', self._names(opened.state, 'seat-0')
        )

        paid = self._cash(opened.state, 'seat-0', 41)
        transition = self._apply(paid, 'seat-0', 'pay_debt')

        self.assertEqual(transition.state['phase'], rules.PHASE_AWAITING_ROLL)
        self.assertEqual(transition.state['pending'], None)
        self.assertIn(
            ('tax_paid', 'seat-0', {'space': 4, 'amount': 41, 'option': 'percent'}),
            self._facts(transition),
        )

    def test_an_unaffordable_third_jail_roll_pays_and_moves_with_the_throw(self):
        state = rules.initial_state(('seat-0', 'seat-1'), 'seat-0')
        state = self._player(
            state,
            'seat-0',
            in_jail=True,
            jail_turns=2,
            position=board.JAIL_INDEX,
            cash=10,
        )
        opened = self._roll(state, 'seat-0', 4, 6)
        self.assertEqual(opened.state['phase'], rules.PHASE_RAISING_CASH)
        self.assertEqual(opened.state['debt']['amount'], rules.JAIL_FINE)
        self.assertEqual(opened.state['debt']['creditor'], None)
        self.assertIs(opened.state['players']['seat-0']['in_jail'], True)

        paid = self._cash(opened.state, 'seat-0', rules.JAIL_FINE)
        transition = self._apply(paid, 'seat-0', 'pay_debt')

        player = transition.state['players']['seat-0']
        self.assertIs(player['in_jail'], False)
        self.assertEqual(player['position'], 20)
        self.assertEqual(transition.state['phase'], rules.PHASE_MANAGING)
        self.assertEqual(transition.state['turn'], 'seat-0')
        self.assertIn(
            ('left_jail', 'seat-0', {'method': 'fine'}), self._facts(transition)
        )
        self.assertIn(
            ('moved', 'seat-0', {'from': 10, 'to': 20, 'passed_go': False}),
            self._facts(transition),
        )

    def test_a_group_payment_pays_the_shares_in_order_and_reopens_if_needed(self):
        state = self._open(('seat-0', 'seat-1', 'seat-2', 'seat-3'))
        state = self._place(state, 'seat-0', 4)
        state = self._cash(state, 'seat-0', 70)
        state = self._top_card(state, cards.CHANCE, 'chance-15')

        opened = self._confirm(self._roll(state, 'seat-0', 1, 2).state)
        self.assertEqual(opened.state['phase'], rules.PHASE_RAISING_CASH)
        self.assertEqual(opened.state['debt']['creditor'], 'seat-2')
        self.assertEqual(opened.state['debt']['amount'], 50)
        self.assertEqual(opened.state['players']['seat-0']['cash'], 20)
        self.assertEqual(opened.state['players']['seat-1']['cash'], 1550)
        self.assertIn(
            ('card_paid', 'seat-0', {'amount': 50, 'to': 'seat-1'}),
            self._facts(opened),
        )

        raised = self._cash(opened.state, 'seat-0', 50)
        paid_one = self._apply(raised, 'seat-0', 'pay_debt')

        # The next share cannot be paid either: a fresh debt for seat-3.
        self.assertEqual(paid_one.state['phase'], rules.PHASE_RAISING_CASH)
        self.assertEqual(paid_one.state['debt']['creditor'], 'seat-3')
        self.assertEqual(paid_one.state['players']['seat-2']['cash'], 1550)
        self.assertEqual(paid_one.state['players']['seat-0']['cash'], 0)
        self.assertIn(
            ('card_paid', 'seat-0', {'amount': 50, 'to': 'seat-2'}),
            self._facts(paid_one),
        )

        raised = self._cash(paid_one.state, 'seat-0', 50)
        done = self._apply(raised, 'seat-0', 'pay_debt')

        self.assertEqual(done.state['phase'], rules.PHASE_MANAGING)
        self.assertIsNone(done.state['debt'])
        self.assertEqual(done.state['players']['seat-3']['cash'], 1550)
        self.assertIn(
            ('card_paid', 'seat-0', {'amount': 50, 'to': 'seat-3'}),
            self._facts(done),
        )

    def test_selling_and_mortgaging_raise_cash_inside_the_window(self):
        state = self._window_scene()
        self.assertEqual(self._options(state, 'seat-0', 'sell'), ('3',))

        sold = self._apply(state, 'seat-0', 'sell', '3')
        self.assertEqual(sold.state['players']['seat-0']['cash'], 35)
        self.assertEqual(sold.state['buildings'], {})
        self.assertEqual(sold.state['phase'], rules.PHASE_RAISING_CASH)
        self.assertEqual(self._options(sold.state, 'seat-0', 'mortgage'), ('1', '3'))

        mortgaged = self._apply(sold.state, 'seat-0', 'mortgage', '3')
        self.assertEqual(mortgaged.state['players']['seat-0']['cash'], 65)
        self.assertEqual(mortgaged.state['mortgaged'], {'3': True})
        self.assertEqual(mortgaged.state['phase'], rules.PHASE_RAISING_CASH)

    def test_declaring_bankruptcy_pays_the_stored_creditor(self):
        state = self._open_rent_debt().state
        transition = self._apply(state, 'seat-0', 'declare_bankruptcy')
        self.assertIs(transition.state['players']['seat-0']['eliminated'], True)
        self.assertIsNone(transition.state['debt'])
        self.assertIn(
            ('bankrupt', 'seat-0', {'creditor': 'seat-1'}), self._facts(transition)
        )

    def test_the_debt_state_is_json_serializable(self):
        """The runtime persists the state as jsonb, so no tuple may leak into it."""
        state = self._open_rent_debt().state
        self.assertEqual(json.loads(json.dumps(state)), state)


class MonopolySettlementInterestTests(MonopolyRulesTestCase):
    """The 10 % interest when a player receives mortgaged property (S9, S10)."""

    def _declare(self, state, seat='seat-0'):
        opened = self._roll(state, seat, 1, 2)
        self.assertEqual(opened.state['phase'], rules.PHASE_RAISING_CASH)
        return self._act(opened.state, seat, 'declare_bankruptcy')

    def _rent_scene(self, seats=('seat-0', 'seat-1', 'seat-2')):
        state = self._open(seats)
        state = self._place(state, 'seat-0', 36)
        state = self._cash(state, 'seat-0', 10)
        return self._give(state, 39, 'seat-1')

    def test_a_player_creditor_pays_the_interest_of_each_mortgaged_property(self):
        state = self._give(self._rent_scene(), 37, 'seat-0')
        state = self._mortgaged(state, 37)

        transition = self._declare(state)

        # 1500 + the debtor's 10 cash, minus Park Place's 18 interest.
        self.assertEqual(
            transition.state['players']['seat-1']['cash'], 1500 + 10 - 18
        )
        self.assertEqual(transition.state['owners']['37'], 'seat-1')
        self.assertEqual(
            sorted(transition.state['players']['seat-1']['properties']), [37, 39]
        )
        self.assertEqual(transition.state['mortgaged'], {'37': True})
        self.assertIn(
            (
                'interest_paid',
                'seat-1',
                {'space': 37, 'amount': 18, 'reason': 'settlement'},
            ),
            self._facts(transition),
        )

    def test_the_settlement_interest_rounds_up_per_property(self):
        state = self._give(self._rent_scene(), 1, 'seat-0')
        state = self._give(state, 37, 'seat-0')
        state = self._mortgaged(state, 1, 37)

        transition = self._declare(state)

        # Mediterranean 30 -> 3, Park Place 175 -> 18.
        self.assertEqual(
            transition.state['players']['seat-1']['cash'], 1500 + 10 - 21
        )
        facts = self._facts(transition)
        self.assertIn(
            ('interest_paid', 'seat-1', {'space': 1, 'amount': 3, 'reason': 'settlement'}),
            facts,
        )
        self.assertIn(
            (
                'interest_paid',
                'seat-1',
                {'space': 37, 'amount': 18, 'reason': 'settlement'},
            ),
            facts,
        )

    def test_a_settlement_without_mortgaged_properties_charges_nothing(self):
        state = self._give(self._rent_scene(), 3, 'seat-0')

        transition = self._declare(state)

        self.assertEqual(transition.state['players']['seat-1']['cash'], 1510)
        self.assertNotIn(
            'interest_paid', [fact[0] for fact in self._facts(transition)]
        )

    def test_a_bank_creditor_charges_no_settlement_interest(self):
        state = self._open(('seat-0', 'seat-1'))
        state = self._place(state, 'seat-0', 33)
        state = self._cash(state, 'seat-0', 10)
        state = self._give(state, 37, 'seat-0')
        state = self._mortgaged(state, 37)
        opened = self._roll(state, 'seat-0', 2, 3)
        self.assertEqual(opened.state['phase'], rules.PHASE_RAISING_CASH)

        transition = self._act(opened.state, 'seat-0', 'declare_bankruptcy')

        self.assertEqual(transition.state['players']['seat-1']['cash'], 1500)
        self.assertNotIn(
            'interest_paid', [fact[0] for fact in self._facts(transition)]
        )
        self.assertEqual(transition.state['owners'], {})

    def test_a_creditor_that_cannot_pay_the_interest_falls_to_the_bank(self):
        state = self._rent_scene()
        state = self._cash(state, 'seat-0', 5)
        state = self._cash(state, 'seat-1', 10)
        state = self._give(state, 34, 'seat-0')
        state = self._give(state, 37, 'seat-0')
        state = self._mortgaged(state, 34, 37)

        transition = self._declare(state)

        # seat-1 receives 5 cash and owes 16 + 18 = 34 of interest: bankruptcy.
        self.assertIs(transition.state['players']['seat-1']['eliminated'], True)
        self.assertEqual(transition.state['players']['seat-1']['cash'], 0)
        self.assertEqual(transition.state['owners'], {})
        facts = self._facts(transition)
        self.assertIn(('bankrupt', 'seat-0', {'creditor': 'seat-1'}), facts)
        self.assertIn(('bankrupt', 'seat-1', {'creditor': None}), facts)
        # It never paid the interest, so no interest_paid may be announced.
        self.assertNotIn('interest_paid', [fact[0] for fact in facts])
        self.assertIs(rules.is_finished(transition.state), True)
        self.assertEqual(rules.outcome(transition.state).winner_seat, 'seat-2')

    def test_the_cascade_returns_to_the_bank_the_properties_it_could_not_hold(self):
        state = self._rent_scene()
        state = self._cash(state, 'seat-0', 5)
        state = self._cash(state, 'seat-1', 10)
        state = self._give(state, 37, 'seat-0')
        state = self._mortgaged(state, 37)  # 18 interest > 15 cash

        transition = self._declare(state)

        self.assertIs(transition.state['players']['seat-1']['eliminated'], True)
        self.assertEqual(transition.state['owners'], {})
        self.assertIn(
            ('bankrupt', 'seat-1', {'creditor': None}), self._facts(transition)
        )


class MonopolyTradeTests(MonopolyRulesTestCase):
    """Offers between two seats: state, grammar, legality and the four actions
    (S2 to S5 and S8 of ``monopoly-trade.md``)."""

    def _managing(self, state, seat='seat-0'):
        state = copy.deepcopy(state)
        state['phase'] = rules.PHASE_MANAGING
        state['turn'] = seat
        return state

    def _rolling(self, state, seat='seat-0'):
        state = copy.deepcopy(state)
        state['phase'] = rules.PHASE_AWAITING_ROLL
        state['turn'] = seat
        return state

    def _value(self, to, give=(), cash=0, want=(), want_cash=0):
        give_list = ','.join(str(index) for index in give)
        want_list = ','.join(str(index) for index in want)
        return (
            f'to={to};give={give_list};cash={cash}'
            f'|want={want_list};cash={want_cash}'
        )

    def _propose(self, state, value, seat='seat-0'):
        return rules.apply_action(
            state, seat, Action(name='propose', value=value), None
        )

    def _apply(self, state, seat, name, value):
        return rules.apply_action(
            state, seat, Action(name=name, value=value), None
        )

    def _rejected(self, state, seat, name, value=None):
        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            rules.apply_action(
                state, seat, Action(name=name, value=value), None
            )
        self.assertEqual(state, before)

    def _scene(self):
        """seat-0 owns brown 1 and 3; seat-1 owns light-blue 6 and 8."""
        state = self._open()
        state = self._give(state, 1, 'seat-0')
        state = self._give(state, 3, 'seat-0')
        state = self._give(state, 6, 'seat-1')
        state = self._give(state, 8, 'seat-1')
        return self._managing(state)

    def _proposed(self, offer):
        state = self._scene()
        return self._propose(state, offer).state

    # --- S2: the state keys ---------------------------------------------

    def test_initial_state_carries_an_empty_offer_map_and_a_zero_sequence(self):
        state = self._open()
        self.assertEqual(state['offers'], {})
        self.assertEqual(state['offer_seq'], 0)

    def test_a_state_saved_before_the_increment_reads_without_offers(self):
        state = self._scene()
        del state['offers']
        del state['offer_seq']

        transition = self._propose(
            state, self._value('seat-1', give=(1,), want=(6,))
        )

        self.assertEqual(transition.state['offer_seq'], 1)
        self.assertIn('1', transition.state['offers'])

    # --- S3: the grammar -------------------------------------------------

    def test_a_proposal_stores_board_ordered_terms_and_the_first_id(self):
        state = self._scene()

        transition = self._propose(
            state, 'to=seat-1;give=3,1;cash=50|want=8,6;cash=25'
        )

        offer = {
            'id': '1',
            'proposer': 'seat-0',
            'receiver': 'seat-1',
            'give': {'properties': [1, 3], 'cash': 50},
            'want': {'properties': [6, 8], 'cash': 25},
        }
        self.assertEqual(transition.state['offers'], {'1': offer})
        self.assertEqual(transition.state['offer_seq'], 1)
        self.assertEqual(
            self._facts(transition),
            (
                (
                    'offer_proposed',
                    'seat-0',
                    {
                        'offer': '1',
                        'proposer': 'seat-0',
                        'receiver': 'seat-1',
                        'give': {'properties': [1, 3], 'cash': 50},
                        'want': {'properties': [6, 8], 'cash': 25},
                    },
                ),
            ),
        )

    def test_each_new_proposal_gets_the_next_id(self):
        state = self._scene()
        first = self._propose(
            state, self._value('seat-1', give=(1,), want=(6,))
        ).state
        second = self._propose(
            first, self._value('seat-1', give=(3,), want=(8,))
        ).state

        self.assertEqual(sorted(second['offers']), ['1', '2'])
        self.assertEqual(second['offer_seq'], 2)
        self.assertEqual(second['offers']['2']['id'], '2')

    def test_the_propose_prompt_publishes_the_grammar_as_freeform(self):
        spec = next(
            spec
            for spec in rules.legal_actions(self._scene(), 'seat-0')
            if spec.name == 'propose'
        )

        self.assertIs(spec.freeform, True)
        self.assertIn(
            'to=<seat>;give=<idx,idx>;cash=<int>|want=<idx,idx>;cash=<int>',
            spec.prompt,
        )

    def test_a_malformed_composed_value_is_rejected(self):
        state = self._scene()
        malformed = (
            '',
            'to=seat-1;give=1;cash=0|want=6',
            'to=seat-1;give=1;cash=0',
            'to=seat-1;give=1;cash=|want=6;cash=0',
            'to=seat-1;give=1,;cash=0|want=6;cash=0',
            'to=seat-1;give=1;cash=-1|want=6;cash=0',
            'to=seat-1;give=1;cash=1.5|want=6;cash=0',
            'to=seat-1;give=40;cash=0|want=6;cash=0',
            'to=seat-1;give=1;cash=0|want=6;cash=0;extra=1',
            'to=seat-1;give=1;cash=0|want=6,6;cash=0',
            'to=seat-1;give=1;cash=0|want=6;cash=0|extra',
            'to=;give=1;cash=0|want=6;cash=0',
            'to=seat-1;give=1 ;cash=0|want=6;cash=0',
        )
        for value in malformed:
            with self.subTest(value=value):
                self._rejected(state, 'seat-0', 'propose', value)

    def test_the_receiver_must_be_another_solvent_seat(self):
        state = self._scene()
        self._rejected(
            state, 'seat-0', 'propose', self._value('seat-9', give=(1,))
        )
        self._rejected(
            state, 'seat-0', 'propose', self._value('seat-0', give=(1,))
        )
        eliminated = copy.deepcopy(state)
        eliminated['players']['seat-1']['eliminated'] = True
        self._rejected(
            eliminated, 'seat-0', 'propose', self._value('seat-1', give=(1,))
        )

    # --- S4: the terms ----------------------------------------------------

    def test_an_empty_offer_is_rejected(self):
        state = self._scene()
        self._rejected(
            state, 'seat-0', 'propose', self._value('seat-1')
        )

    def test_an_index_the_proposer_or_receiver_does_not_own_is_rejected(self):
        state = self._scene()
        self._rejected(
            state, 'seat-0', 'propose', self._value('seat-1', give=(6,))
        )
        self._rejected(
            state, 'seat-0', 'propose', self._value('seat-1', want=(1,))
        )

    def test_a_duplicated_or_doubled_index_is_rejected(self):
        state = self._scene()
        self._rejected(
            state, 'seat-0', 'propose', self._value('seat-1', give=(1, 1))
        )
        state_with_double = self._scene()
        state_with_double = self._give(state_with_double, 1, 'seat-1')
        self._rejected(
            state_with_double,
            'seat-0',
            'propose',
            self._value('seat-1', give=(1,), want=(1,)),
        )

    def test_a_group_with_buildings_blocks_the_offer_on_either_side(self):
        state = copy.deepcopy(self._scene())
        state['buildings'] = {'1': 1}
        self._rejected(
            state, 'seat-0', 'propose', self._value('seat-1', give=(3,))
        )
        receiver_built = copy.deepcopy(self._scene())
        receiver_built['buildings'] = {'6': 1}
        self._rejected(
            receiver_built,
            'seat-0',
            'propose',
            self._value('seat-1', want=(8,)),
        )

    def test_the_cash_each_side_pays_must_be_covered(self):
        state = self._scene()
        self._rejected(
            state, 'seat-0', 'propose', self._value('seat-1', give=(1,), cash=1501)
        )
        self._rejected(
            state, 'seat-0', 'propose', self._value('seat-1', want=(6,), want_cash=1501)
        )

    def test_a_side_that_cannot_sustain_a_mortgaged_property_cannot_receive_it(self):
        state = self._mortgaged(self._scene(), 1)
        broke = self._cash(state, 'seat-1', 2)  # interest on 1 is 3
        self._rejected(
            broke, 'seat-0', 'propose', self._value('seat-1', give=(1,))
        )
        funded = self._cash(state, 'seat-1', 3)
        transition = self._propose(
            funded, self._value('seat-1', give=(1,), cash=3)
        )
        self.assertIn('1', transition.state['offers'])

    # --- S5: the four actions and the seat set ---------------------------

    def test_active_seats_is_every_solvent_seat(self):
        state = self._open(('seat-0', 'seat-1', 'seat-2'))

        self.assertEqual(rules.active_seats(state), ('seat-0', 'seat-1', 'seat-2'))

    def test_legal_actions_appends_the_trade_actions_to_the_phase(self):
        state = self._proposed(self._value('seat-1', give=(1,), want=(6,)))

        proposer = self._names(state, 'seat-0')
        receiver = self._names(state, 'seat-1')

        self.assertEqual(
            proposer,
            ('build', 'mortgage', 'end_turn', 'propose', 'withdraw'),
        )
        self.assertEqual(receiver, ('propose', 'accept', 'reject'))

    def test_the_seat_on_turn_keeps_its_phase_actions_while_negotiating(self):
        state = self._rolling(
            self._proposed(self._value('seat-1', give=(1,), want=(6,)))
        )

        self.assertEqual(
            self._names(state, 'seat-0'), ('roll', 'propose', 'withdraw')
        )

    def test_accept_and_reject_are_offered_for_each_received_offer_in_id_order(self):
        state = self._scene()
        state = self._propose(
            state, self._value('seat-1', give=(1,), want=(6,))
        ).state
        state = self._propose(
            state, self._value('seat-1', give=(3,), want=(8,))
        ).state

        self.assertEqual(self._options(state, 'seat-1', 'accept'), ('1', '2'))
        self.assertEqual(self._options(state, 'seat-1', 'reject'), ('1', '2'))
        self.assertEqual(self._options(state, 'seat-0', 'withdraw'), ('1', '2'))

    def test_accept_is_offered_only_for_offers_that_are_still_valid(self):
        state = self._scene()
        state = self._propose(
            state, self._value('seat-1', give=(1,), want=(6,))
        ).state
        state = self._propose(
            state, self._value('seat-1', give=(1,), want=(8,))
        ).state
        accepted = self._apply(state, 'seat-1', 'accept', '1').state

        self.assertEqual(self._options(accepted, 'seat-1', 'accept'), ())
        self.assertEqual(self._options(accepted, 'seat-1', 'reject'), ('2',))
        self.assertEqual(self._options(accepted, 'seat-0', 'withdraw'), ('2',))

    def test_a_rejected_offer_disappears(self):
        state = self._proposed(self._value('seat-1', give=(1,), want=(6,)))

        transition = self._apply(state, 'seat-1', 'reject', '1')

        self.assertEqual(transition.state['offers'], {})
        self.assertEqual(
            self._facts(transition),
            (('offer_rejected', 'seat-1', {'offer': '1'}),),
        )

    def test_a_withdrawn_offer_disappears(self):
        state = self._proposed(self._value('seat-1', give=(1,), want=(6,)))

        transition = self._apply(state, 'seat-0', 'withdraw', '1')

        self.assertEqual(transition.state['offers'], {})
        self.assertEqual(
            self._facts(transition),
            (('offer_withdrawn', 'seat-0', {'offer': '1'}),),
        )

    def test_the_four_actions_are_accepted_outside_the_turn_phases(self):
        # The receiver is never on turn, yet may reject; the proposer is on
        # turn in awaiting_roll, a phase that used to reject any trade action.
        state = self._rolling(
            self._proposed(self._value('seat-1', give=(1,), want=(6,)))
        )

        withdrawn = self._apply(state, 'seat-0', 'withdraw', '1')
        self.assertEqual(withdrawn.state['offers'], {})

    def test_rejecting_an_unknown_offer_is_rejected(self):
        state = self._proposed(self._value('seat-1', give=(1,), want=(6,)))
        self._rejected(state, 'seat-1', 'reject', '9')
        self._rejected(state, 'seat-0', 'withdraw', '9')

    def test_only_the_receiver_accepts_and_only_the_proposer_withdraws(self):
        state = self._proposed(self._value('seat-1', give=(1,), want=(6,)))
        self._rejected(state, 'seat-0', 'accept', '1')
        self._rejected(state, 'seat-1', 'withdraw', '1')

    # --- S8: several offers ----------------------------------------------

    def test_a_proposer_can_hold_several_open_offers_at_once(self):
        state = self._scene()
        state = self._propose(
            state, self._value('seat-1', give=(1,), want=(6,))
        ).state
        state = self._propose(
            state, self._value('seat-1', give=(3,), want=(8,))
        ).state

        self.assertEqual(len(state['offers']), 2)
        self.assertEqual(self._options(state, 'seat-1', 'accept'), ('1', '2'))

    # --- S6: the transfer -------------------------------------------------

    def test_accept_swaps_properties_and_cash_between_the_two_seats(self):
        state = self._propose(
            self._scene(),
            self._value('seat-1', give=(1,), cash=100, want=(6,), want_cash=50),
        ).state

        transition = self._apply(state, 'seat-1', 'accept', '1')

        self.assertEqual(
            transition.state['players']['seat-0']['cash'], 1500 - 100 + 50
        )
        self.assertEqual(
            transition.state['players']['seat-1']['cash'], 1500 - 50 + 100
        )
        self.assertEqual(
            sorted(transition.state['players']['seat-0']['properties']), [3, 6]
        )
        self.assertEqual(
            sorted(transition.state['players']['seat-1']['properties']), [1, 8]
        )
        self.assertEqual(transition.state['owners']['1'], 'seat-1')
        self.assertEqual(transition.state['owners']['6'], 'seat-0')
        self.assertEqual(transition.state['offers'], {})
        self.assertEqual(transition.state['offer_seq'], 1)

    def test_accept_announces_the_offer_and_the_settlement(self):
        state = self._propose(
            self._scene(), self._value('seat-1', give=(1,), want=(6,))
        ).state

        transition = self._apply(state, 'seat-1', 'accept', '1')

        self.assertEqual(
            self._facts(transition),
            (
                ('offer_accepted', 'seat-1', {'offer': '1'}),
                (
                    'trade_settled',
                    'seat-1',
                    {'offer': '1', 'proposer': 'seat-0', 'receiver': 'seat-1'},
                ),
            ),
        )

    def test_accept_charges_each_side_the_interest_of_what_it_receives(self):
        state = self._mortgaged(self._scene(), 1, 6)
        state = self._propose(
            state, self._value('seat-1', give=(1,), want=(6,))
        ).state

        transition = self._apply(state, 'seat-1', 'accept', '1')

        # seat-0 receives Oriental (mortgage 50 -> 5); seat-1 receives
        # Mediterranean (mortgage 30 -> 3).
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1500 - 5)
        self.assertEqual(transition.state['players']['seat-1']['cash'], 1500 - 3)
        facts = self._facts(transition)
        self.assertEqual(
            facts[0],
            ('interest_paid', 'seat-0', {'space': 6, 'amount': 5, 'reason': 'trade'}),
        )
        self.assertEqual(
            facts[1],
            ('interest_paid', 'seat-1', {'space': 1, 'amount': 3, 'reason': 'trade'}),
        )
        self.assertEqual(
            facts[2],
            ('offer_accepted', 'seat-1', {'offer': '1'}),
        )

    def test_trade_interest_rounds_up_per_property(self):
        state = self._give(self._scene(), 37, 'seat-1')
        state = self._mortgaged(state, 37)
        state = self._propose(
            state, self._value('seat-1', want=(37,))
        ).state

        transition = self._apply(state, 'seat-1', 'accept', '1')

        # Park Place prints 175: a tenth is 17.5, rounded up to 18.
        self.assertEqual(transition.state['players']['seat-0']['cash'], 1500 - 18)
        self.assertIn(
            ('interest_paid', 'seat-0', {'space': 37, 'amount': 18, 'reason': 'trade'}),
            self._facts(transition),
        )

    def test_a_mortgaged_property_transfers_still_mortgaged(self):
        state = self._mortgaged(self._scene(), 1, 6)
        state = self._propose(
            state, self._value('seat-1', give=(1,), want=(6,))
        ).state

        transition = self._apply(state, 'seat-1', 'accept', '1')

        self.assertEqual(transition.state['mortgaged'], {'1': True, '6': True})
        self.assertEqual(transition.state['owners']['1'], 'seat-1')
        self.assertEqual(transition.state['owners']['6'], 'seat-0')

    def test_accepting_a_stale_offer_is_rejected_without_touching_the_state(self):
        state = self._propose(
            self._scene(), self._value('seat-1', give=(1,), want=(6,))
        ).state
        stale = copy.deepcopy(state)
        stale['owners']['1'] = 'seat-1'
        stale['players']['seat-0']['properties'].remove(1)
        stale['players']['seat-1']['properties'].append(1)
        before = copy.deepcopy(stale)

        with self.assertRaises(ValueError):
            self._apply(stale, 'seat-1', 'accept', '1')

        self.assertEqual(stale, before)
        self.assertIn('1', stale['offers'])

    def test_a_second_accept_of_the_same_property_is_rejected(self):
        state = self._scene()
        state = self._propose(
            state, self._value('seat-1', give=(1,), want=(6,))
        ).state
        state = self._propose(
            state, self._value('seat-1', give=(1,), want=(8,))
        ).state
        first = self._apply(state, 'seat-1', 'accept', '1').state
        self.assertEqual(sorted(first['offers']), ['2'])
        before = copy.deepcopy(first)

        with self.assertRaises(ValueError):
            self._apply(first, 'seat-1', 'accept', '2')

        self.assertEqual(first, before)

    # --- S7: the life of an offer -----------------------------------------

    def test_eliminating_a_seat_drops_every_offer_that_names_it(self):
        state = self._open(('seat-0', 'seat-1', 'seat-2'))
        state = self._give(state, 1, 'seat-0')
        state = self._give(state, 3, 'seat-0')
        state = self._give(state, 6, 'seat-1')
        state = self._give(state, 8, 'seat-1')
        state = self._give(state, 11, 'seat-2')
        state = self._give(state, 13, 'seat-2')
        state = self._managing(state)
        state = self._propose(
            state, self._value('seat-1', give=(1,), want=(6,))
        ).state
        state = self._propose(
            state,
            self._value('seat-2', give=(8,), want=(11,)),
            seat='seat-1',
        ).state
        self.assertEqual(sorted(state['offers']), ['1', '2'])

        result = rules.abandon(state, 'seat-0')

        # Offer 2, between seat-1 and seat-2, survives the expulsion.
        self.assertEqual(sorted(result.state['offers']), ['2'])

    def test_finishing_the_match_clears_the_offers(self):
        state = self._propose(
            self._scene(), self._value('seat-1', give=(1,), want=(6,))
        ).state

        final = rules.abandon(state, 'seat-1')

        self.assertIs(rules.is_finished(final.state), True)
        self.assertEqual(final.state['offers'], {})

    def test_a_seat_with_an_open_debt_receives_no_trade_action(self):
        state = self._open(('seat-0', 'seat-1', 'seat-2'))
        state = self._give(state, 1, 'seat-0')
        state = self._give(state, 3, 'seat-0')
        state = self._give(state, 6, 'seat-1')
        state = self._give(state, 8, 'seat-1')
        state = self._give(state, 11, 'seat-2')
        state = self._give(state, 13, 'seat-2')
        state = self._managing(state)
        state = self._propose(
            state, self._value('seat-1', give=(1,), want=(6,))
        ).state
        state = self._propose(
            state,
            self._value('seat-2', give=(8,), want=(11,)),
            seat='seat-1',
        ).state
        state = copy.deepcopy(state)
        state['phase'] = rules.PHASE_RAISING_CASH
        state['turn'] = 'seat-0'
        state['debt'] = {
            'seat': 'seat-0',
            'creditor': 'seat-1',
            'amount': 50,
            'resume': {'kind': 'settle_step', 'extra': False},
            'fact': None,
        }

        names = self._names(state, 'seat-0')
        for name in ('propose', 'accept', 'reject', 'withdraw'):
            with self.subTest(name=name):
                self.assertNotIn(name, names)
        self._rejected(
            state, 'seat-0', 'propose', self._value('seat-1', give=(1,))
        )
        # The other seats keep negotiating while the debt is open.
        self.assertIn('withdraw', self._names(state, 'seat-1'))
        self.assertIn('accept', self._names(state, 'seat-2'))

    # --- D1: an off-turn solvent seat negotiates (follow-up) ----------------

    def test_an_off_turn_seat_is_offered_only_the_trade_actions(self):
        managing = self._scene()  # turn is seat-0
        self.assertEqual(self._names(managing, 'seat-1'), ('propose',))
        for name in ('roll', 'buy', 'end_turn', 'build'):
            with self.subTest(name=name):
                self.assertNotIn(name, self._names(managing, 'seat-1'))

        rolling = self._rolling(self._scene())  # turn is seat-0
        self.assertEqual(self._names(rolling, 'seat-1'), ('propose',))

    def test_an_off_turn_seat_may_propose_and_the_offer_settles(self):
        proposed = self._propose(
            self._scene(),
            self._value('seat-0', give=(6,), want=(1,)),
            seat='seat-1',
        )

        self.assertEqual(proposed.state['offers']['1']['proposer'], 'seat-1')
        self.assertEqual(
            self._facts(proposed),
            (
                (
                    'offer_proposed',
                    'seat-1',
                    {
                        'offer': '1',
                        'proposer': 'seat-1',
                        'receiver': 'seat-0',
                        'give': {'properties': [6], 'cash': 0},
                        'want': {'properties': [1], 'cash': 0},
                    },
                ),
            ),
        )

        accepted = self._apply(proposed.state, 'seat-0', 'accept', '1')

        self.assertEqual(accepted.state['owners']['6'], 'seat-0')
        self.assertEqual(accepted.state['owners']['1'], 'seat-1')
        self.assertEqual(
            sorted(accepted.state['players']['seat-0']['properties']), [3, 6]
        )
        self.assertEqual(
            sorted(accepted.state['players']['seat-1']['properties']), [1, 8]
        )
        self.assertEqual(accepted.state['offers'], {})

    def test_an_off_turn_seat_cannot_take_the_phase_actions(self):
        managing = self._scene()  # turn is seat-0
        self._rejected(managing, 'seat-1', 'end_turn')
        self._rejected(managing, 'seat-1', 'build', '6')

        rolling = self._rolling(self._scene())  # turn is seat-0
        self._rejected(rolling, 'seat-1', 'roll')

    def test_a_seat_that_does_not_hold_the_pending_purchase_cannot_buy(self):
        pending = self._roll(self._open(), 'seat-0', 1, 2).state

        self.assertEqual(self._names(pending, 'seat-1'), ('propose',))
        self._rejected(pending, 'seat-1', 'buy')
        self._rejected(pending, 'seat-1', 'decline')
