"""Datastore tests for the Django ``MatchStore`` adapter.

These tests pin the semantics the runtime already assumes against the
in-memory fake, but now against real Postgres: the version compare-and-swap,
the immutable action row, transactional rollback of both writes, and — the
one that could not be proven with a fake — that ``load`` actually takes a row
lock so two simultaneous actions cannot both pass the version gate.
"""

import uuid
from dataclasses import replace

from django.db import IntegrityError, connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from modules.games.contracts import Action
from modules.games.models import Match, MatchAction
from modules.games.runtime.application.ports import SeatRecord
from modules.games.runtime.domain.errors import StaleVersion
from modules.games.runtime.infrastructure.django_store import DjangoMatchStore
from modules.rooms.models import Participant, Room


class MatchStoreTestCase(TestCase):
    """Shared fixtures: one room with two participants and a fresh store."""

    def setUp(self):
        self.store = DjangoMatchStore()
        self.room = Room.objects.create(game_id='duelo')
        self.first = Participant.objects.create(
            room=self.room,
            session_id=uuid.uuid4(),
            display_name='Guest One',
            game_marker='blue-token',
        )
        self.second = Participant.objects.create(
            room=self.room,
            session_id=uuid.uuid4(),
            display_name='Guest Two',
            game_marker='red-token',
        )

    def seats(self, indexes=(0, 1)):
        occupants = {0: self.first, 1: self.second}
        badges = {0: 'blue-token', 1: 'red-token'}
        return tuple(
            SeatRecord(
                index=index,
                seat_id=f'seat-{index}',
                participant_ref=str(occupants[index].public_id),
                badge=badges[index],
            )
            for index in indexes
        )

    def create_record(self, *, seats=None, state=None):
        with self.store.unit_of_work():
            return self.store.create(
                room_id=self.room.id,
                game_id='duelo',
                state=state if state is not None else {'round': 1},
                seats=seats if seats is not None else self.seats(),
            )

    def stored(self, match_ref):
        return Match.objects.get(public_id=match_ref)


class CreateLoadRoundTripTests(MatchStoreTestCase):
    def test_create_then_load_round_trips_every_field(self):
        state = {'round': 3, 'nested': {'picks': ['rock', 'paper']}}
        created = self.create_record(
            seats=self.seats(indexes=(1, 0)),
            state=state,
        )

        with self.store.unit_of_work():
            loaded = self.store.load(created.match_ref)

        expected_seats = (
            SeatRecord(
                index=0,
                seat_id='seat-0',
                participant_ref=str(self.first.public_id),
                badge='blue-token',
            ),
            SeatRecord(
                index=1,
                seat_id='seat-1',
                participant_ref=str(self.second.public_id),
                badge='red-token',
            ),
        )
        self.assertEqual(loaded, created)
        self.assertEqual(loaded.match_ref, created.match_ref)
        self.assertEqual(loaded.room_id, self.room.id)
        self.assertEqual(loaded.game_id, 'duelo')
        self.assertEqual(loaded.version, 0)
        self.assertEqual(loaded.status, 'in_progress')
        self.assertIsNone(loaded.winner_seat)
        self.assertEqual(loaded.state, state)
        self.assertEqual(loaded.seats, expected_seats)

    def test_seats_are_ordered_by_index_not_by_creation_order(self):
        # The runtime owns seat ordering through MatchSeat.index, so a record
        # reconstructed from the database must not trust the database's
        # natural row order.
        created = self.create_record(seats=self.seats(indexes=(1, 0)))

        with self.store.unit_of_work():
            loaded = self.store.load(created.match_ref)

        self.assertEqual([seat.index for seat in loaded.seats], [0, 1])
        self.assertEqual([seat.seat_id for seat in loaded.seats], ['seat-0', 'seat-1'])


class SaveCompareAndSwapTests(MatchStoreTestCase):
    def test_save_with_the_correct_previous_version_persists_the_next_snapshot(self):
        created = self.create_record()
        next_record = replace(
            created,
            version=1,
            state={'round': 2},
            status='in_progress',
            winner_seat=None,
        )

        with self.store.unit_of_work():
            self.store.save(next_record)

        loaded = self.stored(created.match_ref)
        self.assertEqual(loaded.version, 1)
        self.assertEqual(loaded.state, {'round': 2})
        self.assertEqual(loaded.status, 'in_progress')
        self.assertEqual(loaded.winner_seat, '')
        self.assertIsNone(loaded.finished_at)

    def test_finishing_save_sets_finished_at(self):
        created = self.create_record()
        finished = replace(
            created,
            version=1,
            state={'round': 2, 'winner': 'seat-0'},
            status='finished',
            winner_seat='seat-0',
        )

        with self.store.unit_of_work():
            self.store.save(finished)

        loaded = self.stored(created.match_ref)
        self.assertEqual(loaded.version, 1)
        self.assertEqual(loaded.status, 'finished')
        self.assertEqual(loaded.winner_seat, 'seat-0')
        self.assertIsNotNone(loaded.finished_at)

    def test_save_with_a_stale_previous_version_leaves_the_row_unchanged(self):
        created = self.create_record()
        committed = replace(created, version=1, state={'round': 2})
        with self.store.unit_of_work():
            self.store.save(committed)

        # Same previous version as ``committed`` (0), but the row is now at 1.
        stale = replace(created, version=1, state={'round': 99})
        with self.assertRaises(StaleVersion) as raised:
            with self.store.unit_of_work():
                self.store.save(stale)

        self.assertEqual(raised.exception.match_ref, created.match_ref)
        self.assertEqual(raised.exception.expected_version, 0)
        self.assertEqual(raised.exception.actual_version, 1)

        loaded = self.stored(created.match_ref)
        self.assertEqual(loaded.version, 1)
        self.assertEqual(loaded.state, {'round': 2})

    def test_a_second_save_at_the_same_previous_version_also_raises(self):
        created = self.create_record()
        next_record = replace(created, version=1, state={'round': 2})
        with self.store.unit_of_work():
            self.store.save(next_record)

        # A blind write would be idempotent here; the compare-and-swap is not.
        with self.assertRaises(StaleVersion):
            with self.store.unit_of_work():
                self.store.save(next_record)


class AppendActionTests(MatchStoreTestCase):
    def test_append_action_writes_the_expected_audit_row(self):
        created = self.create_record()
        next_record = replace(created, version=1, state={'round': 2})
        facts = [
            {'name': 'pick_recorded', 'seat': 'seat-0', 'detail': {'value': 'rock'}}
        ]

        with self.store.unit_of_work():
            self.store.save(next_record)
            self.store.append_action(
                record=next_record,
                seat_id='seat-0',
                action=Action(name='pick', value='rock'),
                facts=facts,
            )

        row = MatchAction.objects.get(match__public_id=created.match_ref)
        self.assertEqual(row.sequence, 1)
        self.assertEqual(row.version, 1)
        self.assertEqual(row.seat_id, 'seat-0')
        self.assertEqual(row.action_name, 'pick')
        self.assertEqual(row.action_value, 'rock')
        self.assertEqual(row.facts, facts)

    def test_append_action_rejects_a_duplicate_sequence(self):
        created = self.create_record()
        next_record = replace(created, version=1, state={'round': 2})
        with self.store.unit_of_work():
            self.store.save(next_record)
            self.store.append_action(
                record=next_record,
                seat_id='seat-0',
                action=Action(name='pick', value='rock'),
                facts=[],
            )

        with self.assertRaises(IntegrityError):
            with self.store.unit_of_work():
                self.store.append_action(
                    record=next_record,
                    seat_id='seat-1',
                    action=Action(name='pick', value='paper'),
                    facts=[],
                )


class UnitOfWorkRollbackTests(MatchStoreTestCase):
    def test_a_failed_unit_of_work_rolls_back_the_save_and_the_action(self):
        created = self.create_record()
        next_record = replace(created, version=1, state={'round': 2})

        class Boom(Exception):
            pass

        with self.assertRaises(Boom):
            with self.store.unit_of_work():
                self.store.save(next_record)
                self.store.append_action(
                    record=next_record,
                    seat_id='seat-0',
                    action=Action(name='pick', value='rock'),
                    facts=[],
                )
                raise Boom()

        loaded = self.stored(created.match_ref)
        self.assertEqual(loaded.version, 0)
        self.assertEqual(loaded.state, created.state)
        self.assertFalse(
            MatchAction.objects.filter(match__public_id=created.match_ref).exists()
        )


class LoadMissTests(MatchStoreTestCase):
    def test_load_returns_none_for_an_unknown_well_formed_uuid(self):
        with self.store.unit_of_work():
            self.assertIsNone(self.store.load(str(uuid.uuid4())))

    def test_load_returns_none_for_a_malformed_ref(self):
        with self.store.unit_of_work():
            self.assertIsNone(self.store.load('not-a-uuid'))


class RowLockTests(MatchStoreTestCase):
    def test_load_takes_a_row_lock(self):
        """The lock is real, not assumed.

        The property pinned here is that two simultaneous actions cannot both
        pass the version gate: ``load`` must issue ``SELECT ... FOR UPDATE`` so
        the match row is locked for the rest of the transaction. This is the
        defect FRG-04's review found — the read sat outside any serialized
        transaction, so both actors read version N and one action was silently
        lost. A fake store cannot prove this; only a captured query can.
        """
        created = self.create_record()

        with CaptureQueriesContext(connection) as context:
            with self.store.unit_of_work():
                self.store.load(created.match_ref)

        statements = [query['sql'].upper() for query in context.captured_queries]
        self.assertTrue(
            any('FOR UPDATE' in statement for statement in statements),
            context.captured_queries,
        )
