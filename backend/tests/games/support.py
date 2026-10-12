"""Shared fakes for the framework-free match runtime use-case tests."""

from contextlib import contextmanager

from modules.games.contracts import (
    ActionSpec,
    Fact,
    Outcome,
    SeatOption,
    Transition,
    seat_id,
)
from modules.games.duelo.game import DueloDefinition
from modules.games.registry import GameRegistry
from modules.games.runtime.application.ports import MatchRecord

_BID_RANK = {'low': 0, 'high': 1}


class CallLog:
    """Ordered, shared record of store and projector calls.

    Every entry is ``(name, depth)`` where ``depth`` is the store's
    unit-of-work depth at the moment of the call: ``1`` inside the
    transaction, ``0`` once it has exited. Because the store and the projector
    append to the same list through this object, a test can assert the order
    between a write and a publish, not merely that both happened.
    """

    def __init__(self):
        self.entries = []
        self.depth = 0

    def record(self, name):
        self.entries.append((name, self.depth))


class FakeStore:
    """In-memory ``MatchStore`` that records every call.

    ``unit_of_work`` counts its entries and rolls the in-memory records and
    appended actions back when the block exits with an exception, so a test can
    tell a staged change from a committed one. Every recorded call carries the
    unit-of-work depth it was made at, so a test can assert ``save`` and
    ``append_action`` ran inside the block.

    Pass the same :class:`CallLog` to a ``FakeProjector`` to observe the order
    between a write and a publish across both fakes.
    """

    def __init__(self, log=None):
        self.log = log if log is not None else CallLog()
        self.records = {}
        self.actions = []
        self.calls = self.log.entries
        self.uow_entries = 0
        self.fail_save = False
        self._sequence = 0

    def _record(self, name):
        self.log.record(name)

    @contextmanager
    def unit_of_work(self):
        self.uow_entries += 1
        self.log.depth += 1
        self._record('unit_of_work')
        snapshot = (dict(self.records), list(self.actions), self._sequence)
        try:
            yield
        except Exception:
            self.records, self.actions, self._sequence = snapshot
            raise
        finally:
            self.log.depth -= 1
            self._record('uow_exit')

    def load(self, match_ref):
        self._record('load')
        return self.records.get(match_ref)

    def create(self, *, room_id, game_id, state, seats):
        self._record('create')
        record = MatchRecord(
            match_ref=f'match-{len(self.records) + 1}',
            room_id=room_id,
            game_id=game_id,
            version=0,
            state=state,
            status='in_progress',
            winner_seat=None,
            seats=tuple(seats),
        )
        self.records[record.match_ref] = record
        return record

    def save(self, record):
        self._record('save')
        self.records[record.match_ref] = record
        if self.fail_save:
            raise RuntimeError('save failed')

    def append_action(self, *, record, seat_id, action, facts, **extra_keywords):
        # ``extra_keywords`` records the names of any keywords beyond the port's
        # contract, so a test can prove the use case does not hand the store an
        # ``event`` (or anything else) it has no column for.
        self._record('append_action')
        self._sequence += 1
        self.actions.append(
            {
                'match_ref': record.match_ref,
                'sequence': self._sequence,
                'version': record.version,
                'seat_id': seat_id,
                'action': action,
                'facts': tuple(facts),
                'extra_keywords': tuple(extra_keywords),
            }
        )


class FakeProjector:
    """``MatchProjector`` that records every publish.

    It records the state-free ``header`` the protocol hands it and never a
    match ``state``: the projector deliberately cannot reach a value a seat
    must not see before the reveal.

    When built with the same :class:`CallLog` as a ``FakeStore`` it also logs
    ``publish:<event>`` at the store's current unit-of-work depth, so a test
    can pin that a publish happens after the transaction closed.
    """

    def __init__(self, log=None):
        self.log = log if log is not None else CallLog()
        self.publishes = []

    def publish(self, *, event, header, views, facts):
        self.log.record(f'publish:{event}')
        self.publishes.append(
            {'event': event, 'header': header, 'views': views, 'facts': facts}
        )


class FakeDefinition:
    """Two-seat simultaneous-bid game, deliberately not ``duelo``.

    Both seats may act at once and the match finishes once both have bid.
    ``apply`` records its own calls so a test can prove a rejected action never
    reached the rules.
    """

    game_id = 'fake-game'
    label = 'Fake game'
    description = 'Two-seat simultaneous bid used to exercise the runtime.'
    min_seats = 2
    max_seats = 2
    seat_options = ()

    def __init__(self):
        self.apply_calls = []
        self.start_calls = []

    def start(self, seats, rng):
        self.start_calls.append((tuple(seats), rng))
        return {
            'seat_ids': tuple(seat_id(seat.index) for seat in seats),
            'bids': {},
        }

    def active_seats(self, state):
        return tuple(
            seat for seat in state['seat_ids'] if seat not in state['bids']
        )

    def legal_actions(self, state, seat):
        if seat not in state['seat_ids'] or seat in state['bids']:
            return ()
        return (ActionSpec(name='bid', options=('low', 'high'), prompt='Bid.'),)

    def apply(self, state, seat, action, rng):
        self.apply_calls.append((state, seat, action, rng))
        return Transition(
            state={**state, 'bids': {**state['bids'], seat: action.value}},
            facts=(
                Fact(name='bid_recorded', seat=seat, detail={'value': action.value}),
            ),
        )

    def view(self, state, seat):
        return {'seat': seat, 'bids': dict(state['bids'])}

    def is_finished(self, state):
        return len(state['bids']) == len(state['seat_ids'])

    def outcome(self, state):
        if not self.is_finished(state):
            return None
        ranks = {seat: _BID_RANK[value] for seat, value in state['bids'].items()}
        if len(set(ranks.values())) == 1:
            return None
        return Outcome(winner_seat=max(ranks, key=ranks.get), reason='highest_bid')


class FakeNoOptionDefinition(FakeDefinition):
    """Variant whose single action declares no options."""

    game_id = 'fake-no-option'

    def legal_actions(self, state, seat):
        if seat not in state['seat_ids'] or seat in state['bids']:
            return ()
        return (ActionSpec(name='pass'),)

    def apply(self, state, seat, action, rng):
        self.apply_calls.append((state, seat, action, rng))
        return Transition(
            state={**state, 'bids': {**state['bids'], seat: action.value}},
            facts=(Fact(name='pass_recorded', seat=seat, detail={}),),
        )


class SecondScopingGame:
    """A second game declared **only** so tests can prove per-game scoping.

    Only one real game (``duelo``) is registered in production, but the room and
    match isolation tests need two distinct registered games to show that rooms,
    memberships, active-room lookups and seat subscriptions stay scoped to a
    single ``game_id``. This definition implements only the members the room
    serializer reads, is never registered in production, and therefore ships no
    fake game.
    """

    game_id = 'scoping-test-game'
    label = 'Scoping test game'
    description = 'Second game declared in tests to prove per-game scoping.'
    min_seats = 1
    max_seats = 2
    seat_options = (
        SeatOption(id='scoping-badge-a', label='Scoping badge A'),
        SeatOption(id='scoping-badge-b', label='Scoping badge B'),
        SeatOption(id='scoping-badge-c', label='Scoping badge C'),
    )


SCOPING_GAME = SecondScopingGame()

# The id and markers used wherever a module only needs a *different* valid game.
SCOPING_GAME_ID = SCOPING_GAME.game_id
SCOPING_GAME_MARKERS = tuple(option.id for option in SCOPING_GAME.seat_options)

# Real ``duelo`` plus the test-only second game, for patching the room
# serializer's registry in tests that exercise two games through the REST API.
SCOPING_TEST_REGISTRY = GameRegistry((DueloDefinition(), SCOPING_GAME))
SCOPING_TEST_GAMES = SCOPING_TEST_REGISTRY.list_games()
