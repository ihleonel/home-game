from collections import deque
from datetime import datetime, timedelta
from unittest.mock import Mock, call
from uuid import uuid4

from django.test import SimpleTestCase

from modules.rooms.features.reaping.application.ports import ReapingPorts
from modules.rooms.features.reaping.application.use_cases import (
    reap_ghost_memberships,
)
from modules.rooms.features.reaping.domain.entities import (
    ReapableParticipant,
    ReapOutcome,
)
from modules.rooms.features.reaping.domain.rules import (
    is_stale,
    reap_changes,
    staleness_cutoff,
)

from .support import ports_fake

NOW = datetime(2026, 1, 1, 12, 2, 0)
CUTOFF = datetime(2026, 1, 1, 12, 1, 0)


class ReapingUseCaseTests(SimpleTestCase):
    def test_stale_participant_is_reaped_with_exact_changes_and_events(self):
        participant = _participant(disconnected_at=NOW - timedelta(seconds=90))
        ports = _ports(
            active_room_ids=(12,),
            room_ids_with_in_progress_match=set(),
            now=NOW,
            reapable_participants_for_update=(participant,),
            room_snapshot={'revision': 1},
            has_active_participants=False,
        )
        vote_cancellation = Mock()
        # A reaped participant without a pending vote must not schedule a
        # cancellation event. Leaving the default Mock return value in place
        # would publish one and consume an extra snapshot.
        vote_cancellation.participant_left.return_value = None

        outcome = reap_ghost_memberships(
            ports, vote_cancellation, grace_seconds=60
        )

        self.assertEqual(outcome, ReapOutcome(1, 1, 1))
        ports.active_room_ids.assert_called_once_with(room_id=None)
        ports.reapable_participants_for_update.assert_called_once_with(
            (12,), cutoff=CUTOFF
        )
        ports.save_reaped_changes.assert_called_once_with(
            24,
            {
                'left_at': NOW,
                'presence': 'offline',
                'disconnected_at': None,
                'is_ready': False,
            },
        )
        vote_cancellation.participant_left.assert_called_once_with(12, 24)
        ports.schedule_room_event.assert_called_once_with(
            12,
            'player_left',
            {'revision': 1},
            departed_session_id=participant.session_id,
        )
        self.assertEqual(
            ports.timeline,
            [
                'begin',
                'active_room_ids',
                'room_ids_with_in_progress_match',
                'now',
                'reapable_participants_for_update',
                'save_reaped_changes',
                'room_snapshot',
                'schedule_room_event',
                'has_active_participants',
                'delete_room',
                'commit',
            ],
        )

    def test_room_with_in_progress_match_is_skipped_entirely(self):
        ports = _ports(
            active_room_ids=(12,),
            room_ids_with_in_progress_match={12},
        )
        vote_cancellation = Mock()

        outcome = reap_ghost_memberships(
            ports, vote_cancellation, grace_seconds=60
        )

        self.assertEqual(outcome, ReapOutcome(0, 0, 0))
        self.assertEqual(
            ports.timeline,
            [
                'begin',
                'active_room_ids',
                'room_ids_with_in_progress_match',
                'commit',
            ],
        )
        ports.now.assert_not_called()
        ports.reapable_participants_for_update.assert_not_called()
        ports.save_reaped_changes.assert_not_called()
        ports.room_snapshot.assert_not_called()
        ports.has_active_participants.assert_not_called()
        ports.delete_room.assert_not_called()
        ports.schedule_room_event.assert_not_called()
        vote_cancellation.participant_left.assert_not_called()

    def test_no_candidate_rooms_returns_the_zero_outcome_without_reads(self):
        ports = _ports(active_room_ids=())
        vote_cancellation = Mock()

        outcome = reap_ghost_memberships(
            ports, vote_cancellation, grace_seconds=60
        )

        self.assertEqual(outcome, ReapOutcome(0, 0, 0))
        self.assertEqual(ports.timeline, ['begin', 'active_room_ids', 'commit'])
        ports.now.assert_not_called()
        ports.save_reaped_changes.assert_not_called()
        ports.schedule_room_event.assert_not_called()

    def test_snapshot_is_captured_before_deleting_an_emptied_room(self):
        participant = _participant()
        ports = _ports(
            active_room_ids=(12,),
            room_ids_with_in_progress_match=set(),
            now=NOW,
            reapable_participants_for_update=(participant,),
            room_snapshot={'revision': 7},
            has_active_participants=False,
        )
        vote_cancellation = Mock()
        vote_cancellation.participant_left.return_value = None

        outcome = reap_ghost_memberships(
            ports, vote_cancellation, grace_seconds=60
        )

        self.assertEqual(outcome, ReapOutcome(1, 1, 1))
        ports.has_active_participants.assert_called_once_with(12)
        ports.delete_room.assert_called_once_with(12)
        self.assertLess(
            ports.timeline.index('room_snapshot'),
            ports.timeline.index('delete_room'),
        )
        self.assertLess(
            ports.timeline.index('schedule_room_event'),
            ports.timeline.index('delete_room'),
        )

    def test_room_with_active_participants_after_reaping_is_kept(self):
        participant = _participant()
        ports = _ports(
            active_room_ids=(12,),
            room_ids_with_in_progress_match=set(),
            now=NOW,
            reapable_participants_for_update=(participant,),
            room_snapshot={'revision': 1},
            has_active_participants=True,
        )
        vote_cancellation = Mock()
        vote_cancellation.participant_left.return_value = None

        outcome = reap_ghost_memberships(
            ports, vote_cancellation, grace_seconds=60
        )

        self.assertEqual(outcome, ReapOutcome(1, 1, 0))
        ports.has_active_participants.assert_called_once_with(12)
        ports.delete_room.assert_not_called()

    def test_pending_expulsion_vote_is_cancelled_with_the_vote_payload(self):
        participant = _participant()
        ports = _ports(
            active_room_ids=(12,),
            room_ids_with_in_progress_match=set(),
            now=NOW,
            reapable_participants_for_update=(participant,),
            room_snapshot={'revision': 3},
            has_active_participants=True,
        )
        vote_cancellation = Mock()
        vote_cancellation.participant_left.return_value = {'status': 'cancelled'}

        reap_ghost_memberships(ports, vote_cancellation, grace_seconds=60)

        vote_cancellation.participant_left.assert_called_once_with(12, 24)
        self.assertEqual(
            ports.schedule_room_event.call_args_list,
            [
                call(
                    12,
                    'player_left',
                    {'revision': 3},
                    departed_session_id=participant.session_id,
                ),
                call(
                    12,
                    'expulsion_vote_cancelled',
                    {'revision': 3},
                    vote={'status': 'cancelled'},
                ),
            ],
        )

    def test_second_run_with_no_stale_participants_is_a_read_only_noop(self):
        ports = _ports(
            active_room_ids=(12,),
            room_ids_with_in_progress_match=set(),
            now=NOW,
            reapable_participants_for_update=(),
        )
        vote_cancellation = Mock()

        outcome = reap_ghost_memberships(
            ports, vote_cancellation, grace_seconds=60
        )

        self.assertEqual(outcome, ReapOutcome(0, 0, 0))
        self.assertEqual(
            ports.timeline,
            [
                'begin',
                'active_room_ids',
                'room_ids_with_in_progress_match',
                'now',
                'reapable_participants_for_update',
                'commit',
            ],
        )
        ports.save_reaped_changes.assert_not_called()
        ports.room_snapshot.assert_not_called()
        ports.has_active_participants.assert_not_called()
        ports.delete_room.assert_not_called()
        ports.schedule_room_event.assert_not_called()
        vote_cancellation.participant_left.assert_not_called()

    def test_connected_row_returned_by_the_port_is_not_reaped(self):
        # The port is trusted to return only stale rows, but reaping is
        # destructive, so the use case re-applies the domain rule and drops a
        # non-stale row instead of trusting the gateway blindly.
        participant = _participant(
            presence='online', disconnected_at=NOW - timedelta(seconds=90)
        )
        ports = _ports(
            active_room_ids=(12,),
            room_ids_with_in_progress_match=set(),
            now=NOW,
            reapable_participants_for_update=(participant,),
        )
        vote_cancellation = Mock()

        outcome = reap_ghost_memberships(
            ports, vote_cancellation, grace_seconds=60
        )

        self.assertEqual(outcome, ReapOutcome(0, 0, 0))
        ports.save_reaped_changes.assert_not_called()
        ports.room_snapshot.assert_not_called()
        ports.has_active_participants.assert_not_called()
        ports.delete_room.assert_not_called()
        ports.schedule_room_event.assert_not_called()
        vote_cancellation.participant_left.assert_not_called()

    def test_row_disconnected_inside_the_grace_window_is_not_reaped(self):
        participant = _participant(
            presence='reconnecting',
            disconnected_at=NOW - timedelta(seconds=59),
        )
        ports = _ports(
            active_room_ids=(12,),
            room_ids_with_in_progress_match=set(),
            now=NOW,
            reapable_participants_for_update=(participant,),
        )
        vote_cancellation = Mock()

        outcome = reap_ghost_memberships(
            ports, vote_cancellation, grace_seconds=60
        )

        self.assertEqual(outcome, ReapOutcome(0, 0, 0))
        ports.save_reaped_changes.assert_not_called()
        ports.schedule_room_event.assert_not_called()
        ports.delete_room.assert_not_called()
        vote_cancellation.participant_left.assert_not_called()

    def test_guard_drops_only_the_non_stale_rows_from_a_mixed_batch(self):
        stale = _participant(
            participant_id=24,
            disconnected_at=NOW - timedelta(seconds=90),
        )
        not_stale = _participant(
            participant_id=25,
            presence='inactive',
            disconnected_at=NOW - timedelta(seconds=10),
        )
        ports = _ports(
            active_room_ids=(12,),
            room_ids_with_in_progress_match=set(),
            now=NOW,
            reapable_participants_for_update=(not_stale, stale),
            room_snapshot={'revision': 1},
            has_active_participants=True,
        )
        vote_cancellation = Mock()
        vote_cancellation.participant_left.return_value = None

        outcome = reap_ghost_memberships(
            ports, vote_cancellation, grace_seconds=60
        )

        self.assertEqual(outcome, ReapOutcome(1, 1, 0))
        ports.save_reaped_changes.assert_called_once_with(
            24,
            {
                'left_at': NOW,
                'presence': 'offline',
                'disconnected_at': None,
                'is_ready': False,
            },
        )

    def test_room_id_is_passed_through_to_active_room_ids(self):
        ports = _ports(
            active_room_ids=(12,),
            room_ids_with_in_progress_match=set(),
            now=NOW,
            reapable_participants_for_update=(),
        )
        vote_cancellation = Mock()

        reap_ghost_memberships(
            ports, vote_cancellation, grace_seconds=60, room_id=12
        )

        ports.active_room_ids.assert_called_once_with(room_id=12)

    def test_rooms_and_participants_are_processed_in_ascending_id_order(self):
        ports = _ports(
            active_room_ids=(12, 9),
            room_ids_with_in_progress_match=set(),
            now=NOW,
            reapable_participants_for_update=(
                _participant(participant_id=3, room_id=12),
                _participant(participant_id=20, room_id=12),
                _participant(participant_id=30, room_id=9),
                _participant(participant_id=9, room_id=9),
            ),
            room_snapshot=deque(
                (
                    {'revision': 9},
                    {'revision': 9},
                    {'revision': 12},
                    {'revision': 12},
                )
            ),
            has_active_participants=False,
        )
        vote_cancellation = Mock()
        vote_cancellation.participant_left.return_value = None

        outcome = reap_ghost_memberships(
            ports, vote_cancellation, grace_seconds=60
        )

        self.assertEqual(outcome, ReapOutcome(2, 4, 2))
        self.assertEqual(
            [argument.args[0] for argument in ports.save_reaped_changes.call_args_list],
            [9, 30, 3, 20],
        )
        self.assertEqual(
            [argument.args[0] for argument in ports.room_snapshot.call_args_list],
            [9, 9, 12, 12],
        )
        self.assertEqual(
            [argument.args[0] for argument in ports.delete_room.call_args_list],
            [9, 12],
        )


class StalenessRulesTests(SimpleTestCase):
    def test_cutoff_subtracts_the_grace_window_from_now(self):
        self.assertEqual(staleness_cutoff(NOW, 60), CUTOFF)

    def test_disconnected_inside_the_grace_window_is_not_stale(self):
        disconnected_at = NOW - timedelta(seconds=59)

        self.assertFalse(is_stale('reconnecting', disconnected_at, CUTOFF))
        self.assertFalse(is_stale('inactive', disconnected_at, CUTOFF))

    def test_disconnected_exactly_at_the_cutoff_is_stale(self):
        disconnected_at = NOW - timedelta(seconds=60)

        self.assertTrue(is_stale('reconnecting', disconnected_at, CUTOFF))
        self.assertTrue(is_stale('inactive', disconnected_at, CUTOFF))

    def test_connected_presence_is_never_stale(self):
        disconnected_at = NOW - timedelta(hours=1)

        self.assertFalse(is_stale('online', disconnected_at, CUTOFF))
        self.assertFalse(is_stale('offline', disconnected_at, CUTOFF))

    def test_missing_disconnection_moment_is_never_stale(self):
        self.assertFalse(is_stale('reconnecting', None, CUTOFF))
        self.assertFalse(is_stale('inactive', None, CUTOFF))

    def test_reap_changes_clears_membership_and_readiness(self):
        self.assertEqual(
            reap_changes(NOW),
            (
                ('left_at', NOW),
                ('presence', 'offline'),
                ('disconnected_at', None),
                ('is_ready', False),
            ),
        )


def _ports(**results):
    return ports_fake(ReapingPorts, **results)


def _participant(
    participant_id=24,
    room_id=12,
    presence='reconnecting',
    disconnected_at=NOW - timedelta(seconds=90),
):
    return ReapableParticipant(
        id=participant_id,
        room_id=room_id,
        session_id=uuid4(),
        presence=presence,
        disconnected_at=disconnected_at,
    )
