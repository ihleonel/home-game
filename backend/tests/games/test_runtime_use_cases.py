"""Use-case tests for the framework-free match runtime.

The runtime is driven only through the ports and the registry, so the fake
cases prove the loop executes any game without importing ``duelo``, and the
final case proves the same loop drives the real definition.
"""

import json

from django.test import SimpleTestCase

from modules.games.duelo.game import DueloDefinition
from modules.games.registry import GameRegistry
from modules.games.runtime.application.ports import MatchHeader, SeatRecord
from modules.games.runtime.application.start_match import start_match
from modules.games.runtime.application.submit_action import submit_action
from modules.games.runtime.domain.errors import (
    IllegalAction,
    MatchNotFound,
    MatchNotPlayable,
    NotASeat,
    NotYourTurn,
    StaleVersion,
    UnknownGame,
    WrongSeatCount,
)
from tests.games.support import (
    CallLog,
    FakeDefinition,
    FakeNoOptionDefinition,
    FakeProjector,
    FakeStore,
)


def _seat_tuples(indexes):
    return tuple(
        (index, f'participant-{index}', f'badge-{index}') for index in indexes
    )


class StartMatchTests(SimpleTestCase):
    def setUp(self):
        self.definition = FakeDefinition()
        self.registry = GameRegistry((self.definition,))
        self.store = FakeStore()
        self.projector = FakeProjector()

    def _start(self, **overrides):
        kwargs = {
            'room_id': 7,
            'game_id': 'fake-game',
            'seats': ((0, 'p0', 'red'), (1, 'p1', 'blue')),
            'store': self.store,
            'registry': self.registry,
            'projector': self.projector,
        }
        kwargs.update(overrides)
        return start_match(**kwargs)

    def test_unknown_game_is_rejected(self):
        with self.assertRaises(UnknownGame):
            self._start(game_id='nope')

    def test_too_few_seats_is_rejected(self):
        with self.assertRaises(WrongSeatCount):
            self._start(seats=_seat_tuples((0,)))

    def test_too_many_seats_is_rejected(self):
        with self.assertRaises(WrongSeatCount):
            self._start(seats=_seat_tuples((0, 1, 2)))

    def test_duplicate_seat_index_is_a_programming_error(self):
        with self.assertRaises(ValueError):
            self._start(seats=((0, 'p0', 'red'), (0, 'p1', 'blue')))

    def test_duplicate_participant_ref_is_a_programming_error(self):
        # Two seats sharing one participant_ref leave one seat unreachable:
        # seat_for returns the first match and the other seat is silently lost.
        with self.assertRaises(ValueError):
            self._start(seats=((0, 'p0', 'red'), (1, 'p0', 'blue')))

    def test_happy_path_creates_a_version_zero_record(self):
        record = self._start()

        self.assertEqual(record.version, 0)
        self.assertEqual(record.status, 'in_progress')
        self.assertIsNone(record.winner_seat)
        self.assertEqual(
            record.seats,
            (
                SeatRecord(index=0, seat_id='seat-0', participant_ref='p0', badge='red'),
                SeatRecord(index=1, seat_id='seat-1', participant_ref='p1', badge='blue'),
            ),
        )
        self.assertEqual(self.store.records[record.match_ref], record)

    def test_happy_path_publishes_a_state_free_header_and_views(self):
        record = self._start()

        self.assertEqual(len(self.projector.publishes), 1)
        published = self.projector.publishes[0]
        self.assertEqual(published['event'], 'match_started')
        header = published['header']
        self.assertIsInstance(header, MatchHeader)
        self.assertEqual(header.match_ref, record.match_ref)
        self.assertEqual(header.room_id, 7)
        self.assertEqual(header.game_id, 'fake-game')
        self.assertEqual(header.version, 0)
        self.assertEqual(header.status, 'in_progress')
        self.assertIsNone(header.winner_seat)
        self.assertEqual(header.seats, record.seats)
        # The raw state, and the record that carries it, must not be reachable
        # from what the projector received.
        self.assertFalse(hasattr(header, 'state'))
        self.assertNotIn('record', published)
        self.assertNotIn('state', published)
        self.assertEqual(set(published['views']), {'seat-0', 'seat-1', None})
        self.assertEqual(published['facts'], ())


class SubmitActionTests(SimpleTestCase):
    def setUp(self):
        self.definition = FakeDefinition()
        self.registry = GameRegistry((self.definition,))
        self.log = CallLog()
        self.store = FakeStore(self.log)
        self.projector = FakeProjector(self.log)
        self.record = start_match(
            room_id=7,
            game_id='fake-game',
            seats=((0, 'p0', 'red'), (1, 'p1', 'blue')),
            store=self.store,
            registry=self.registry,
            projector=self.projector,
        )
        self.projector.publishes.clear()

    def _submit(self, **overrides):
        kwargs = {
            'match_ref': self.record.match_ref,
            'participant_ref': 'p0',
            'action_name': 'bid',
            'action_value': 'high',
            'expected_version': self.record.version,
            'store': self.store,
            'registry': self.registry,
            'projector': self.projector,
        }
        kwargs.update(overrides)
        return submit_action(**kwargs)

    def _finish(self):
        first = self._submit(participant_ref='p0', action_value='high')
        return self._submit(
            participant_ref='p1',
            action_value='low',
            expected_version=first.version,
        )

    def test_two_seats_finish_the_match_and_append_two_actions(self):
        first = self._submit(participant_ref='p0', action_value='high')

        self.assertEqual(first.version, 1)
        self.assertEqual(first.status, 'in_progress')
        self.assertIsNone(first.winner_seat)

        second = self._submit(
            participant_ref='p1',
            action_value='low',
            expected_version=first.version,
        )

        self.assertEqual(second.version, 2)
        self.assertEqual(second.status, 'finished')
        self.assertEqual(second.winner_seat, 'seat-0')
        self.assertEqual(len(self.store.actions), 2)
        for appended in self.store.actions:
            self.assertIsInstance(appended, dict)
            for fact in appended['facts']:
                self.assertIsInstance(fact, dict)
        self.assertEqual(
            self.store.actions[1]['facts'],
            ({'name': 'bid_recorded', 'seat': 'seat-1', 'detail': {'value': 'low'}},),
        )
        self.assertEqual(
            [publish['event'] for publish in self.projector.publishes],
            ['match_updated', 'match_finished'],
        )

    def test_appended_action_records_the_acting_seat(self):
        # Two seats act in turn; the audit row must carry the acting seat id
        # directly so the store never has to scrape it back out of ``facts``.
        self._finish()

        self.assertEqual(
            [appended['seat_id'] for appended in self.store.actions],
            ['seat-0', 'seat-1'],
        )

    def test_append_action_is_not_handed_an_event(self):
        # ``MatchAction`` has no event column and the event name is a
        # projection concern, so the store must not receive one.
        self._submit(participant_ref='p0', action_value='high')

        self.assertEqual(self.store.actions[0]['extra_keywords'], ())

    def test_missing_match_is_rejected_first(self):
        with self.assertRaises(MatchNotFound):
            self._submit(match_ref='missing')

    def test_persisted_match_of_an_unknown_game_is_rejected(self):
        with self.assertRaises(UnknownGame):
            self._submit(registry=GameRegistry(()))

    def test_action_on_a_finished_match_is_rejected(self):
        finished = self._finish()

        with self.assertRaises(MatchNotPlayable):
            self._submit(
                participant_ref='p0',
                action_value='high',
                expected_version=finished.version,
            )

    def test_participant_without_a_seat_is_rejected(self):
        with self.assertRaises(NotASeat):
            self._submit(participant_ref='stranger')

    def test_stale_version_is_rejected(self):
        with self.assertRaises(StaleVersion):
            self._submit(expected_version=99)

    def test_seat_out_of_turn_is_rejected(self):
        first = self._submit(participant_ref='p0', action_value='high')

        with self.assertRaises(NotYourTurn):
            self._submit(
                participant_ref='p0',
                action_value='low',
                expected_version=first.version,
            )

    def test_action_name_that_is_not_offered_is_rejected(self):
        with self.assertRaises(IllegalAction):
            self._submit(action_name='fold')

    def test_value_outside_the_spec_options_is_rejected_without_applying(self):
        # FRG-02 proved an unvalidated value can silently produce a wrong
        # winner, so the reject must be observed on the rules recorder, not
        # only as an exception.
        with self.assertRaises(IllegalAction):
            self._submit(action_value='medium')

        self.assertEqual(self.definition.apply_calls, [])

    def test_value_for_a_spec_without_options_is_rejected_without_applying(self):
        definition = FakeNoOptionDefinition()
        registry = GameRegistry((definition,))
        store = FakeStore()
        projector = FakeProjector()
        record = start_match(
            room_id=9,
            game_id='fake-no-option',
            seats=((0, 'p0', 'red'), (1, 'p1', 'blue')),
            store=store,
            registry=registry,
            projector=projector,
        )

        with self.assertRaises(IllegalAction):
            submit_action(
                match_ref=record.match_ref,
                participant_ref='p0',
                action_name='pass',
                action_value='anything',
                expected_version=record.version,
                store=store,
                registry=registry,
                projector=projector,
            )

        self.assertEqual(definition.apply_calls, [])

    def test_successful_action_runs_in_one_unit_of_work(self):
        before = self.store.uow_entries

        self._submit()

        self.assertEqual(self.store.uow_entries, before + 1)
        inside = [name for name, depth in self.store.calls if depth == 1]
        self.assertIn('save', inside)
        self.assertIn('append_action', inside)

    def test_failing_save_rolls_back_to_the_pre_action_record(self):
        before = self.store.records[self.record.match_ref]
        self.store.fail_save = True

        with self.assertRaises(RuntimeError):
            self._submit()

        after = self.store.records[self.record.match_ref]
        self.assertEqual(after, before)
        self.assertEqual(after.version, 0)
        self.assertEqual(after.state, before.state)
        self.assertEqual(self.store.actions, [])

    def test_successful_action_reads_inside_the_unit_of_work(self):
        # The read-validate-write sequence must be one transaction, so the
        # load has to happen after the unit of work was entered; otherwise two
        # simultaneous actors both read version N and one action is lost.
        self.store.calls.clear()

        self._submit()

        names = [name for name, _ in self.store.calls]
        self.assertIn('load', names)
        self.assertIn('unit_of_work', names)
        self.assertLess(names.index('unit_of_work'), names.index('load'))
        self.assertEqual(
            [depth for name, depth in self.store.calls if name == 'load'], [1]
        )

    def test_rejected_action_reads_inside_the_unit_of_work(self):
        self.store.calls.clear()

        with self.assertRaises(StaleVersion):
            self._submit(expected_version=99)

        names = [name for name, _ in self.store.calls]
        self.assertIn('load', names)
        self.assertIn('unit_of_work', names)
        self.assertLess(names.index('unit_of_work'), names.index('load'))
        self.assertEqual(
            [depth for name, depth in self.store.calls if name == 'load'], [1]
        )

    def test_published_event_happens_only_after_the_transaction_commits(self):
        """A committed transition publishes strictly after ``uow_exit``.

        The property pinned here is that an event is published only for a
        transition that committed. A publish moved inside the unit of work
        would run before the commit, at depth 1, and emit a phantom event for
        a transition that a later rollback could undo.
        """
        self.store.calls.clear()

        self._submit()

        names = [name for name, _ in self.store.calls]
        self.assertIn('uow_exit', names)
        self.assertIn('publish:match_updated', names)
        exit_index = names.index('uow_exit')
        publish_index = names.index('publish:match_updated')
        self.assertLess(exit_index, publish_index)
        # The store depth must be back to 0 when the publish is recorded: a
        # publish at depth 1 happened before the transaction closed.
        self.assertEqual(self.store.calls[exit_index][1], 0)
        self.assertEqual(self.store.calls[publish_index][1], 0)

    def test_rejected_action_publishes_no_event(self):
        """A rejected action can never produce an event.

        The property pinned here is that an event is published only for a
        transition that committed. If the publish ran inside the transaction,
        or above the gates, a rejected (rolled-back) action would still emit a
        phantom event even though nothing persisted.
        """
        self.store.calls.clear()

        with self.assertRaises(StaleVersion):
            self._submit(expected_version=99)

        publishes = [
            name for name, _ in self.store.calls if name.startswith('publish:')
        ]
        self.assertEqual(publishes, [])

    def test_apply_receives_the_rng_passed_to_submit_action(self):
        sentinel = object()

        self._submit(rng=sentinel)

        self.assertIs(self.definition.apply_calls[-1][3], sentinel)


class ApplicationPackageTests(SimpleTestCase):
    def test_seat_views_is_imported_from_the_views_module(self):
        from modules.games.runtime.application.views import seat_views

        definition = FakeDefinition()
        registry = GameRegistry((definition,))
        store = FakeStore()
        projector = FakeProjector()
        record = start_match(
            room_id=5,
            game_id='fake-game',
            seats=((0, 'p0', 'red'), (1, 'p1', 'blue')),
            store=store,
            registry=registry,
            projector=projector,
        )

        self.assertEqual(
            set(seat_views(definition, record)), {'seat-0', 'seat-1', None}
        )

    def test_application_package_exposes_no_callables(self):
        import importlib

        application = importlib.import_module(
            'modules.games.runtime.application'
        )

        # Read the namespace itself: the package must hold no logic, only its
        # docstring, so it must expose no non-dunder callables.
        exposed = [
            name
            for name, value in vars(application).items()
            if callable(value) and not name.startswith('__')
        ]
        self.assertEqual(exposed, [])


class RealDueloRuntimeTests(SimpleTestCase):
    def test_duelo_runs_to_a_finished_two_zero_through_the_runtime(self):
        definition = DueloDefinition()
        registry = GameRegistry((definition,))
        store = FakeStore()
        projector = FakeProjector()

        record = start_match(
            room_id=3,
            game_id='duelo',
            seats=((0, 'p0', 'guante-rojo'), (1, 'p1', 'guante-azul')),
            store=store,
            registry=registry,
            projector=projector,
        )
        self.assertEqual(store.records[record.match_ref], record)

        record = self._submit(store, registry, projector, record, 'p0', 'rock')

        # The opponent must not learn the pending pick before the reveal.
        hidden = projector.publishes[-1]['views']['seat-1']
        self.assertNotIn('rock', json.dumps(hidden))

        record = self._submit(store, registry, projector, record, 'p1', 'scissors')
        record = self._submit(store, registry, projector, record, 'p0', 'paper')
        record = self._submit(store, registry, projector, record, 'p1', 'rock')

        self.assertEqual(record.status, 'finished')
        self.assertEqual(record.winner_seat, 'seat-0')
        self.assertTrue(definition.is_finished(record.state))
        self.assertEqual(projector.publishes[-1]['event'], 'match_finished')
        self.assertEqual(
            tuple(fact['name'] for fact in store.actions[-1]['facts']),
            ('pick_recorded', 'round_resolved', 'match_finished'),
        )

    def _submit(self, store, registry, projector, record, participant_ref, value):
        return submit_action(
            match_ref=record.match_ref,
            participant_ref=participant_ref,
            action_name='pick',
            action_value=value,
            expected_version=record.version,
            store=store,
            registry=registry,
            projector=projector,
        )
