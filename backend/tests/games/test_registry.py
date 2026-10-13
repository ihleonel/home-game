"""Contract and registry tests for the games module.

These tests are deliberately Django-free: they prove the game runtime contract
can be implemented and exercised without any framework dependency, the same way
``tests.rooms.support`` proves the room application ports are implementable.
"""

from django.test import SimpleTestCase

from modules.games.contracts import (
    Action,
    ActionSpec,
    Fact,
    Outcome,
    Seat,
    SeatOption,
    Transition,
)
from modules.games.registry import GameRegistry


_BID_RANK = {'low': 0, 'high': 1}


class FakeDefinition:
    """Minimal framework-free implementation of the GameDefinition contract."""

    game_id = 'fake-game'
    label = 'Fake game'
    description = 'A minimal fake used to exercise the registry contract.'
    min_seats = 2
    max_seats = 4
    seat_options = (
        SeatOption(id='red', label='Red'),
        SeatOption(id='blue', label='Blue'),
    )

    def start(self, seats, rng):
        """Open a match with an empty bid board for the given seats."""
        return {
            'seat_ids': tuple(f'seat-{seat.index}' for seat in seats),
            'bids': {},
        }

    def active_seats(self, state):
        """Every seat that has not bid yet may act right now."""
        return tuple(
            seat_id for seat_id in state['seat_ids'] if seat_id not in state['bids']
        )

    def legal_actions(self, state, seat):
        """A single bid action with two values is always available."""
        return (ActionSpec(name='bid', options=('low', 'high'), prompt='Choose a bid.'),)

    def apply(self, state, seat, action, rng):
        """Record the seat bid and emit a fact about it."""
        return Transition(
            state={**state, 'bids': {**state['bids'], seat: action.value}},
            facts=(Fact(name='bid_placed', seat=seat, detail={'value': action.value}),),
        )

    def abandon(self, state, seat, rng):
        """Drop an abandoned seat and its bid so the match can still close."""
        if seat not in state['seat_ids']:
            raise ValueError(f'unknown seat: {seat!r}')
        return Transition(
            state={
                **state,
                'seat_ids': tuple(s for s in state['seat_ids'] if s != seat),
                'bids': {s: v for s, v in state['bids'].items() if s != seat},
            },
            facts=(Fact(name='seat_abandoned', seat=seat, detail={}),),
        )

    def view(self, state, seat):
        """The public bid board is visible to seats and spectators alike."""
        return {'seat': seat, 'bids': dict(state['bids'])}

    def is_finished(self, state):
        """The match ends once every seat has bid."""
        return len(state['bids']) == len(state['seat_ids'])

    def outcome(self, state):
        """The highest bid wins once the match is finished."""
        if not self.is_finished(state):
            return None
        winner = max(
            state['bids'], key=lambda seat_id: _BID_RANK[state['bids'][seat_id]]
        )
        return Outcome(winner_seat=winner, reason='highest bid')


class GameRegistryTests(SimpleTestCase):
    def setUp(self):
        self.definition = FakeDefinition()
        self.registry = GameRegistry((self.definition,))

    def test_list_games_returns_catalog_dto_derived_from_seat_options(self):
        """The catalog DTO keeps the frontend shape and maps seat options to markers."""
        self.assertEqual(
            self.registry.list_games(),
            (
                {
                    'id': 'fake-game',
                    'label': 'Fake game',
                    'description': 'A minimal fake used to exercise the registry contract.',
                    'markers': (
                        {'id': 'red', 'label': 'Red'},
                        {'id': 'blue', 'label': 'Blue'},
                    ),
                },
            ),
        )

    def test_get_returns_the_registered_definition_or_none(self):
        """get resolves a known id and yields None for an unknown one."""
        self.assertIs(self.registry.get('fake-game'), self.definition)
        self.assertIsNone(self.registry.get('nope'))

    def test_is_known_game_reflects_registered_ids(self):
        """is_known_game is true only for registered ids."""
        self.assertTrue(self.registry.is_known_game('fake-game'))
        self.assertFalse(self.registry.is_known_game('nope'))

    def test_contains_seat_option_checks_the_known_game_options(self):
        """Seat options are matched per game and unknown games never match."""
        self.assertTrue(self.registry.contains_seat_option('fake-game', 'red'))
        self.assertFalse(self.registry.contains_seat_option('fake-game', 'green'))
        self.assertFalse(self.registry.contains_seat_option('nope', 'red'))

    def test_duplicate_game_id_raises_value_error(self):
        """Two definitions cannot share a game_id."""
        with self.assertRaises(ValueError):
            GameRegistry((self.definition, FakeDefinition()))

    def test_fake_definition_runs_end_to_end_through_the_registry(self):
        """A registered definition drives a full minimal match trace."""
        definition = self.registry.get('fake-game')
        seats = (
            Seat(index=0, participant_ref='11111111-1111-1111-1111-111111111111'),
            Seat(index=1, participant_ref='22222222-2222-2222-2222-222222222222'),
        )

        state = definition.start(seats, rng=None)
        self.assertEqual(definition.active_seats(state), ('seat-0', 'seat-1'))
        self.assertEqual(
            definition.legal_actions(state, 'seat-0'),
            (ActionSpec(name='bid', options=('low', 'high'), prompt='Choose a bid.'),),
        )

        first = definition.apply(
            state, 'seat-0', Action(name='bid', value='high'), rng=None
        )
        self.assertEqual(
            first.facts,
            (Fact(name='bid_placed', seat='seat-0', detail={'value': 'high'}),),
        )

        second = definition.apply(
            first.state, 'seat-1', Action(name='bid', value='low'), rng=None
        )
        state = second.state

        self.assertEqual(
            definition.view(state, 'seat-0')['bids'],
            {'seat-0': 'high', 'seat-1': 'low'},
        )
        self.assertEqual(
            definition.view(state, None)['bids'],
            {'seat-0': 'high', 'seat-1': 'low'},
        )
        self.assertTrue(definition.is_finished(state))
        self.assertEqual(
            definition.outcome(state),
            Outcome(winner_seat='seat-0', reason='highest bid'),
        )
