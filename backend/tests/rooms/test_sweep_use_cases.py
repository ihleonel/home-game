"""Fake-port tests for the reap-or-vote sweep (S3, S4).

The sweep is one idempotent evaluation per room: lock the room, skip it whole
when it holds an in-progress match, walk the expired absences in ``joined_at``
order deciding reap / leave / include in the automatic batch, and delete the
room when nothing active remains. The decision rules live in the expulsion
voting domain; these tests pin the orchestration and its exact port timeline.
"""

from collections import deque
from datetime import datetime, timedelta
from unittest.mock import Mock, call
from uuid import uuid4

from django.test import SimpleTestCase

from modules.rooms.features.expulsion_voting.application.ports import (
    ExpulsionVotingPorts,
)
from modules.rooms.features.expulsion_voting.domain.entities import VoteRecord
from modules.rooms.features.reaping.application.ports import ReapingPorts
from modules.rooms.features.reaping.application.use_cases import (
    reap_ghost_memberships,
    sweep_rooms,
)
from modules.rooms.features.reaping.domain.entities import (
    ReapableParticipant,
    ReapOutcome,
)
from modules.rooms.features.reaping.domain.rules import GRACE, STARTUP

from .support import ports_fake

NOW = datetime(2026, 10, 16, 12, 5, 0)
VOTE = VoteRecord(300, uuid4(), 'pending', (24, 25), None)


class SweepUseCaseTests(SimpleTestCase):
    def test_expired_batch_reaches_the_quorum_and_starts_one_automatic_vote(self):
        first = _expired(participant_id=24, joined_at=NOW - timedelta(minutes=10))
        second = _expired(participant_id=25, joined_at=NOW - timedelta(minutes=5))
        ports, voting = _sweep_ports(
            reapable_participants_for_update=(first, second),
            connected_voter_ids_for_update=(1, 2),
            pending_vote_target_ids_for_update=(),
            absence_is_spent_for_update=False,
            create_vote=VOTE,
            vote_snapshot={'status': 'pending'},
            room_snapshot={'revision': 1},
            has_active_participants=True,
        )
        vote_cancellation = Mock()

        outcome = sweep_rooms(
            ports, voting, vote_cancellation, grace_seconds=60
        )

        self.assertEqual(outcome, ReapOutcome(0, 0, 0))
        ports.save_reaped_changes.assert_not_called()
        vote_cancellation.participant_left.assert_not_called()
        voting.create_vote.assert_called_once_with(
            12, (24, 25), origin='automatic'
        )
        voting.create_ballots.assert_called_once_with(VOTE.id, (1, 2))
        ports.schedule_room_event.assert_called_once_with(
            12,
            'expulsion_vote_started',
            {'revision': 1},
            vote={'status': 'pending'},
        )
        self.assertEqual(
            ports.timeline,
            [
                'begin',
                'active_room_ids',
                'room_ids_with_in_progress_match',
                'now',
                'reapable_participants_for_update',
                'pending_vote_target_ids_for_update',
                'connected_voter_ids_for_update',
                'absence_is_spent_for_update',
                'absence_is_spent_for_update',
                'create_vote',
                'create_ballots',
                'vote_snapshot',
                'room_snapshot',
                'schedule_room_event',
                'commit',
            ],
        )

    def test_a_single_connected_voter_falls_back_to_reaping(self):
        first = _expired(participant_id=24, joined_at=NOW - timedelta(minutes=10))
        second = _expired(participant_id=25, joined_at=NOW - timedelta(minutes=5))
        ports, voting = _sweep_ports(
            reapable_participants_for_update=(first, second),
            connected_voter_ids_for_update=(7,),
            pending_vote_target_ids_for_update=(),
            absence_is_spent_for_update=False,
            room_snapshot=deque(({'revision': 1}, {'revision': 2})),
            has_active_participants=True,
        )
        vote_cancellation = Mock()
        vote_cancellation.participant_left.return_value = None

        outcome = sweep_rooms(
            ports, voting, vote_cancellation, grace_seconds=60
        )

        self.assertEqual(outcome, ReapOutcome(1, 2, 0))
        voting.create_vote.assert_not_called()
        self.assertEqual(
            [argument.args[0] for argument in ports.save_reaped_changes.call_args_list],
            [24, 25],
        )

    def test_an_empty_electorate_falls_back_to_reaping(self):
        ghost = _expired(participant_id=24)
        ports, voting = _sweep_ports(
            reapable_participants_for_update=(ghost,),
            connected_voter_ids_for_update=(),
            pending_vote_target_ids_for_update=(),
            absence_is_spent_for_update=False,
            room_snapshot={'revision': 1},
            has_active_participants=True,
        )
        vote_cancellation = Mock()
        vote_cancellation.participant_left.return_value = None

        outcome = sweep_rooms(
            ports, voting, vote_cancellation, grace_seconds=60
        )

        self.assertEqual(outcome, ReapOutcome(1, 1, 0))
        voting.create_vote.assert_not_called()
        ports.save_reaped_changes.assert_called_once()

    def test_a_spent_absence_is_reaped_even_with_the_quorum(self):
        spent = _expired(participant_id=24)
        candidate = _expired(participant_id=25, joined_at=NOW + timedelta(minutes=1))
        ports, voting = _sweep_ports(
            reapable_participants_for_update=(spent, candidate),
            connected_voter_ids_for_update=(1, 2),
            pending_vote_target_ids_for_update=(),
            absence_is_spent_for_update=deque((True, False)),
            create_vote=VOTE,
            vote_snapshot={'status': 'pending'},
            room_snapshot=deque(({'revision': 1}, {'revision': 2})),
            has_active_participants=True,
        )
        vote_cancellation = Mock()
        vote_cancellation.participant_left.return_value = None

        outcome = sweep_rooms(
            ports, voting, vote_cancellation, grace_seconds=60
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
        voting.create_vote.assert_called_once_with(12, (25,), origin='automatic')

    def test_a_target_of_a_pending_vote_is_left_alone(self):
        pending = _expired(participant_id=24)
        ports, voting = _sweep_ports(
            reapable_participants_for_update=(pending,),
            connected_voter_ids_for_update=(1, 2),
            pending_vote_target_ids_for_update=(24,),
            absence_is_spent_for_update=False,
            room_snapshot={'revision': 1},
            has_active_participants=True,
        )
        vote_cancellation = Mock()

        outcome = sweep_rooms(
            ports, voting, vote_cancellation, grace_seconds=60
        )

        self.assertEqual(outcome, ReapOutcome(0, 0, 0))
        ports.save_reaped_changes.assert_not_called()
        voting.create_vote.assert_not_called()
        vote_cancellation.participant_left.assert_not_called()

    def test_a_pending_vote_blocks_a_second_vote_and_leaves_the_new_absence(self):
        # Only one pending vote per room is allowed (S5): while a vote is open,
        # an absence it does not cover waits for the next sweep rather than
        # racing ``one_pending_room_vote``.
        covered = _expired(participant_id=24)
        uncovered = _expired(
            participant_id=25, joined_at=NOW + timedelta(minutes=1)
        )
        ports, voting = _sweep_ports(
            reapable_participants_for_update=(covered, uncovered),
            connected_voter_ids_for_update=(1, 2),
            pending_vote_target_ids_for_update=(24,),
            absence_is_spent_for_update=False,
            room_snapshot={'revision': 1},
            has_active_participants=True,
        )
        vote_cancellation = Mock()

        outcome = sweep_rooms(
            ports, voting, vote_cancellation, grace_seconds=60
        )

        self.assertEqual(outcome, ReapOutcome(0, 0, 0))
        ports.save_reaped_changes.assert_not_called()
        voting.create_vote.assert_not_called()

    def test_a_votable_candidate_is_not_reaped(self):
        # The vote decision precedes the reap: the candidate joins the batch
        # and is never written as a left membership.
        candidate = _expired(participant_id=24)
        ports, voting = _sweep_ports(
            reapable_participants_for_update=(candidate,),
            connected_voter_ids_for_update=(1, 2),
            pending_vote_target_ids_for_update=(),
            absence_is_spent_for_update=False,
            create_vote=VOTE,
            vote_snapshot={'status': 'pending'},
            room_snapshot={'revision': 1},
            has_active_participants=True,
        )
        vote_cancellation = Mock()

        sweep_rooms(ports, voting, vote_cancellation, grace_seconds=60)

        ports.save_reaped_changes.assert_not_called()
        voting.create_vote.assert_called_once_with(12, (24,), origin='automatic')

    def test_a_never_socketed_offline_row_is_reaped_never_voted(self):
        never_socketed = ReapableParticipant(
            id=24,
            room_id=12,
            session_id=uuid4(),
            presence='offline',
            disconnected_at=None,
            updated_at=NOW - timedelta(seconds=90),
            joined_at=NOW - timedelta(minutes=10),
        )
        ports, voting = _sweep_ports(
            reapable_participants_for_update=(never_socketed,),
            connected_voter_ids_for_update=(1, 2),
            pending_vote_target_ids_for_update=(),
            absence_is_spent_for_update=False,
            room_snapshot={'revision': 1},
            has_active_participants=True,
        )
        vote_cancellation = Mock()
        vote_cancellation.participant_left.return_value = None

        outcome = sweep_rooms(
            ports, voting, vote_cancellation, grace_seconds=60
        )

        self.assertEqual(outcome, ReapOutcome(1, 1, 0))
        ports.save_reaped_changes.assert_called_once()
        voting.create_vote.assert_not_called()
        voting.absence_is_spent_for_update.assert_not_called()

    def test_in_progress_match_skips_the_whole_room(self):
        ports, voting = _sweep_ports(
            active_room_ids=(12,),
            room_ids_with_in_progress_match={12},
        )
        vote_cancellation = Mock()

        outcome = sweep_rooms(
            ports, voting, vote_cancellation, grace_seconds=60
        )

        self.assertEqual(outcome, ReapOutcome(0, 0, 0))
        self.assertEqual(
            ports.timeline,
            ['begin', 'active_room_ids', 'room_ids_with_in_progress_match', 'commit'],
        )
        voting.pending_vote_target_ids_for_update.assert_not_called()

    def test_second_sweep_over_the_same_state_is_a_noop(self):
        ports, voting = _sweep_ports(
            reapable_participants_for_update=(),
            connected_voter_ids_for_update=(1, 2),
            pending_vote_target_ids_for_update=(),
        )
        vote_cancellation = Mock()

        outcome = sweep_rooms(
            ports, voting, vote_cancellation, grace_seconds=60
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
        voting.pending_vote_target_ids_for_update.assert_not_called()
        voting.create_vote.assert_not_called()

    def test_startup_policy_reaps_everything_and_never_votes(self):
        online = ReapableParticipant(
            id=24,
            room_id=12,
            session_id=uuid4(),
            presence='online',
            disconnected_at=None,
            updated_at=NOW,
            joined_at=NOW - timedelta(minutes=10),
        )
        ports, voting = _sweep_ports(
            reapable_participants_for_update=(online,),
            room_snapshot={'revision': 1},
            has_active_participants=False,
        )
        vote_cancellation = Mock()
        vote_cancellation.participant_left.return_value = None

        outcome = sweep_rooms(
            ports,
            voting,
            vote_cancellation,
            grace_seconds=60,
            policy=STARTUP,
        )

        self.assertEqual(outcome, ReapOutcome(1, 1, 1))
        ports.delete_room.assert_called_once_with(12)
        voting.pending_vote_target_ids_for_update.assert_not_called()
        voting.create_vote.assert_not_called()

    def test_expired_absences_are_walked_in_joined_at_order(self):
        older = _expired(participant_id=91, joined_at=NOW - timedelta(minutes=30))
        newer = _expired(participant_id=17, joined_at=NOW - timedelta(minutes=1))
        ports, voting = _sweep_ports(
            reapable_participants_for_update=(newer, older),
            connected_voter_ids_for_update=(),
            pending_vote_target_ids_for_update=(),
            absence_is_spent_for_update=False,
            room_snapshot=deque(({'revision': 1}, {'revision': 2})),
            has_active_participants=True,
        )
        vote_cancellation = Mock()
        vote_cancellation.participant_left.return_value = None

        sweep_rooms(ports, voting, vote_cancellation, grace_seconds=60)

        self.assertEqual(
            [argument.args[0] for argument in ports.save_reaped_changes.call_args_list],
            [91, 17],
        )

    def test_vote_cancellation_of_a_reaped_voter_is_published(self):
        # A reaped membership that was the target/voter of a pending vote still
        # cancels it exactly as the bare reaper did.
        ghost = _expired(participant_id=24)
        ports, voting = _sweep_ports(
            reapable_participants_for_update=(ghost,),
            connected_voter_ids_for_update=(),
            pending_vote_target_ids_for_update=(),
            absence_is_spent_for_update=False,
            room_snapshot={'revision': 3},
            has_active_participants=True,
        )
        vote_cancellation = Mock()
        vote_cancellation.participant_left.return_value = {'status': 'cancelled'}

        sweep_rooms(ports, voting, vote_cancellation, grace_seconds=60)

        self.assertEqual(
            ports.schedule_room_event.call_args_list,
            [
                call(
                    12,
                    'player_left',
                    {'revision': 3},
                    departed_session_id=ghost.session_id,
                ),
                call(
                    12,
                    'expulsion_vote_cancelled',
                    {'revision': 3},
                    vote={'status': 'cancelled'},
                ),
            ],
        )


class ReapOnlyWrapperTests(SimpleTestCase):
    def test_reap_ghost_memberships_never_touches_the_vote_ports(self):
        ghost = _expired(participant_id=24)
        ports = ports_fake(
            ReapingPorts,
            active_room_ids=(12,),
            room_ids_with_in_progress_match=set(),
            now=NOW,
            reapable_participants_for_update=(ghost,),
            room_snapshot={'revision': 1},
            has_active_participants=True,
        )
        vote_cancellation = Mock()
        vote_cancellation.participant_left.return_value = None

        outcome = reap_ghost_memberships(
            ports, vote_cancellation, grace_seconds=60
        )

        self.assertEqual(outcome, ReapOutcome(1, 1, 0))
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
                'commit',
            ],
        )


def _sweep_ports(**overrides):
    defaults = dict(
        active_room_ids=(12,),
        room_ids_with_in_progress_match=set(),
        now=NOW,
        reapable_participants_for_update=(),
        save_reaped_changes=None,
        room_snapshot={'revision': 1},
        has_active_participants=True,
        delete_room=None,
        schedule_room_event=None,
        pending_vote_target_ids_for_update=(),
        connected_voter_ids_for_update=(),
        absence_is_spent_for_update=False,
        create_vote=None,
        create_ballots=None,
        vote_snapshot=None,
    )
    defaults.update(overrides)
    ports = ports_fake(ReapingPorts, ExpulsionVotingPorts, **defaults)
    return ports, ports


def _expired(
    participant_id=24,
    room_id=12,
    disconnected_at=NOW - timedelta(seconds=90),
    joined_at=NOW - timedelta(minutes=10),
):
    return ReapableParticipant(
        id=participant_id,
        room_id=room_id,
        session_id=uuid4(),
        presence='reconnecting',
        disconnected_at=disconnected_at,
        updated_at=NOW - timedelta(seconds=90),
        joined_at=joined_at,
    )
